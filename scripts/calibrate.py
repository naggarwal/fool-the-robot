#!/usr/bin/env python
"""Offline calibration sweep for the Fool the Robot confidence core (PRD #8).

WHY THIS EXISTS
---------------
The 2026-07-26 calibration pass (docs/calibration-2026-07-26.md) was done by
hand: read percentages off the UI, reconstruct the underlying similarity
distribution from the top-5 percentages, and sweep temperature analytically.
That worked, but it carried two known biases (EMA-smoothed p1 paired with an
unsmoothed s1, plus a flat-background model) and it cannot be repeated quickly
when the vocabulary, the lighting or the lens changes.

This script does the same thing exactly instead of approximately. It re-runs
the real CLIP image encoder over the saved calibration crops, recovers the FULL
cosine-similarity vector per frame (all display labels + all anchors), and then
sweeps the calibration knobs numerically. Because the similarity vector is
independent of every knob being swept, the image encoder runs ONCE per crop and
the entire grid is pure arithmetic on top of it -- no reconstruction, no bias.

INPUT is calib/manifest.json, written by GET /debug/capture in server.py, which
saves the exact classified crop plus operator-supplied ground truth (`cls`).

WHAT IS SWEPT
-------------
  temperature       logit scale before softmax (higher = peakier)
  similarity_floor  raw-sim floor below which the band is "unknown"
  fam_low_sim       PINNED to similarity_floor -- see below
  fam_high_sim      raw sim that maps to familiarity 100

fam_low_sim is deliberately not a free parameter. The band ("unknown") and the
familiarity gauge are BOTH always on screen, so if the floor and the bottom of
the gauge disagree the booth can show "I don't know" next to a half-full
familiarity meter, or a confident guess next to an empty one. Pinning them
makes those two readouts one decision.

SCORING (per frame, from the manifest's `cls`)
----------------------------------------------
  clear          top-1 label == true_label AND top-1 pct in 75-90
  near-neighbor  true_label in top-2       AND top-1 pct in 40-60
  out-of-vocab   familiarity < 33 (the model should signal unfamiliarity)
  empty          raw top sim < floor (presence/floor rejects it)

Plus one condition the PRD wording omits but the physics demands: `clear` and
`near-neighbor` frames must ALSO clear the floor. Without it the sweep is
degenerate -- since fam_low == floor, raising the floor both lowers familiarity
(helping out-of-vocab) and rejects more frames (helping empty), while nothing
in the clear/near-neighbor rules pushes back. The optimizer's best move would
be to shove the floor to the top of the grid and reject every real object.

Every frame is scored on its own; frames are never averaged into a per-object
number before ranking, because the frame-to-frame variance is the thing that
decides whether a setting survives a school gym.

Usage:
    ./.venv/bin/python scripts/calibrate.py                     # dry run
    ./.venv/bin/python scripts/calibrate.py --top 20
    ./.venv/bin/python scripts/calibrate.py --write             # writes YAML
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

log = logging.getLogger("calibrate")

# --- Scoring windows (PRD 5.2b targets; see module docstring) ---------------
CLEAR_PCT = (75.0, 90.0)
NEAR_PCT = (40.0, 60.0)
FAM_UNFAMILIAR_MAX = 33.0

VALID_CLS = ("clear", "near-neighbor", "out-of-vocab", "empty")

# Keys rewritten by --write. fam_low_sim is pinned to the floor.
_YAML_KEYS = ("temperature", "similarity_floor", "fam_low_sim", "fam_high_sim")


# --------------------------------------------------------------------------- #
# CLI value parsing
# --------------------------------------------------------------------------- #
def parse_grid(spec: str, name: str) -> list[float]:
    """Parse "1,2,3" or "start:stop:step" (stop inclusive) into a value list."""
    spec = spec.strip()
    if ":" in spec:
        parts = spec.split(":")
        if len(parts) != 3:
            raise argparse.ArgumentTypeError(
                f"--{name}: range must be start:stop:step, got {spec!r}"
            )
        start, stop, step = (float(p) for p in parts)
        if step <= 0:
            raise argparse.ArgumentTypeError(f"--{name}: step must be > 0")
        n = int(round((stop - start) / step)) + 1
        vals = [round(start + i * step, 6) for i in range(max(n, 1))]
    else:
        vals = [round(float(p), 6) for p in spec.split(",") if p.strip()]
    if not vals:
        raise argparse.ArgumentTypeError(f"--{name}: empty grid")
    return sorted(set(vals))


# --------------------------------------------------------------------------- #
# Frame model
# --------------------------------------------------------------------------- #
@dataclass
class Frame:
    """One calibration crop, with its recomputed similarity vector."""

    file: str
    true_label: str
    cls: str
    sims: np.ndarray  # full vector: display labels first, then anchors
    raw_top_sim: float  # max over DISPLAY sims only (what classify() reports)
    raw_top_label: str
    # per-temperature cache: T -> (top1_label, top1_pct, top2_labels)
    _by_temp: dict[float, tuple[str, float, tuple[str, ...]]] = field(
        default_factory=dict, repr=False
    )

    def at_temp(self, temp: float, display_labels: list[str], n_display: int):
        """Top-1 label, top-1 pct and top-2 label set at this temperature.

        Mirrors classify(): softmax over ALL labels (display + anchors), then
        slice the display labels. No display-only renormalization -- the anchor
        mass is precisely what keeps percentages honest.
        """
        hit = self._by_temp.get(temp)
        if hit is not None:
            return hit
        logits = self.sims * temp
        logits = logits - logits.max()
        exp = np.exp(logits)
        probs = exp / exp.sum()
        display_probs = probs[:n_display]
        order = np.argsort(display_probs)[::-1][:5]
        top1_label = display_labels[int(order[0])]
        top1_pct = float(display_probs[int(order[0])] * 100.0)
        top2 = tuple(display_labels[int(i)] for i in order[:2])
        hit = (top1_label, top1_pct, top2)
        self._by_temp[temp] = hit
        return hit

    def familiarity(self, floor: float, fam_high: float) -> float:
        span = fam_high - floor
        if span <= 0:
            return 100.0 if self.raw_top_sim >= fam_high else 0.0
        fam = (self.raw_top_sim - floor) / span * 100.0
        return float(max(0.0, min(100.0, fam)))

    def rank_ok(self, display_labels: list[str], n_display: int) -> bool:
        """Is this frame's ranking correct at all? Temperature-invariant.

        Softmax is monotonic, so the identity of the top-1 (and the top-2 set)
        does not depend on temperature. A ranking failure fails at EVERY tuple
        in the grid and can never be tuned away -- worth separating from a
        percentage-window miss, which is exactly what the sweep can fix.
        """
        top1, _, top2 = self.at_temp(1.0, display_labels, n_display)
        if self.cls == "clear":
            return top1 == self.true_label
        if self.cls == "near-neighbor":
            return self.true_label in top2
        return True  # out-of-vocab / empty have no ranking requirement


# --------------------------------------------------------------------------- #
# Manifest + similarity recomputation
# --------------------------------------------------------------------------- #
def load_manifest(manifest_path: Path) -> list[dict]:
    if not manifest_path.is_file():
        raise SystemExit(
            f"no manifest at {manifest_path}\n"
            "Capture some frames first, e.g.:\n"
            "  FOOLBOT_DEBUG=1 ./run.sh   # then, in another shell:\n"
            "  curl 'http://127.0.0.1:8000/debug/capture?"
            "label=scissors&cls=clear&n=10&seconds=3'"
        )
    records = json.loads(manifest_path.read_text())
    if not isinstance(records, list):
        raise SystemExit(f"{manifest_path}: expected a JSON list of records")
    return records


def compute_frames(records: list[dict], calib_dir: Path, clf) -> list[Frame]:
    """Run the image encoder once per crop and keep the full sim vector.

    Deliberately does NOT reuse the manifest's stored raw_top_sim: those were
    recorded under whatever tuning was live at capture time, and only the top
    value was kept. The sweep needs the whole vector, exactly.
    """
    import cv2  # local import: keeps --help fast
    import torch
    from PIL import Image

    frames: list[Frame] = []
    # /debug/capture derives its filename counter from a glob over calib/, so if
    # the PNGs are cleared but manifest.json is not, filenames get reused while
    # the stale records survive. Cache by filename: one encode per unique image,
    # and a warning so silent double-weighting in the ranking is visible.
    sims_cache: dict[str, np.ndarray] = {}
    seen: set[str] = set()
    for rec in records:
        # Records from a capture whose classify() threw carry file/true_label/
        # cls and an error, but no sims -- they are still perfectly usable here
        # because we recompute everything from the PNG anyway.
        missing = [k for k in ("file", "true_label", "cls") if k not in rec]
        if missing:
            log.warning("skipping record, missing %s: %r", ",".join(missing), rec)
            continue
        if rec["cls"] not in VALID_CLS:
            log.warning("skipping %s: unknown cls %r", rec["file"], rec["cls"])
            continue
        path = calib_dir / rec["file"]
        if not path.is_file():
            log.warning("skipping %s: crop not found at %s", rec["file"], path)
            continue
        if rec["file"] in seen:
            log.warning("%s appears more than once in the manifest -- it will be "
                        "scored (and weighted) once per record", rec["file"])
        seen.add(rec["file"])

        sims = sims_cache.get(rec["file"])
        if sims is None:
            bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if bgr is None:
                log.warning("skipping %s: unreadable PNG", rec["file"])
                continue
            # Byte-for-byte the preprocessing in Classifier.classify(). The crops
            # were written by cv2.imwrite, so they are BGR on disk; reading them
            # with PIL instead would silently swap the channels and shift the sims.
            rgb = bgr[:, :, ::-1]
            pil = Image.fromarray(np.ascontiguousarray(rgb))
            img_t = clf.preprocess(pil).unsqueeze(0).to(clf.device)
            with torch.no_grad():
                img_feat = clf.model.encode_image(img_t)
                img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
                sims_t = clf.text_matrix @ img_feat.float().squeeze(0)
            sims = sims_t.cpu().numpy()
            sims_cache[rec["file"]] = sims

        display_sims = sims[: clf.n_display]
        top_idx = int(np.argmax(display_sims))
        frames.append(
            Frame(
                file=rec["file"],
                true_label=rec["true_label"],
                cls=rec["cls"],
                sims=sims,
                raw_top_sim=float(display_sims[top_idx]),
                raw_top_label=clf.display_labels[top_idx],
            )
        )
        log.debug(
            "%s: cls=%s raw_top=%s %.4f",
            rec["file"], rec["cls"], frames[-1].raw_top_label, frames[-1].raw_top_sim,
        )
    return frames


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_frame(
    frame: Frame,
    temp: float,
    floor: float,
    fam_high: float,
    display_labels: list[str],
    n_display: int,
) -> tuple[bool, str]:
    """Return (passed, human-readable reading) for one frame under one tuple."""
    top1, pct, top2 = frame.at_temp(temp, display_labels, n_display)
    fam = frame.familiarity(floor, fam_high)
    above_floor = frame.raw_top_sim >= floor

    if frame.cls == "clear":
        ok = above_floor and top1 == frame.true_label and CLEAR_PCT[0] <= pct <= CLEAR_PCT[1]
        why = f"top1={top1} {pct:.1f}%"
        if not above_floor:
            why += " REJECTED-by-floor"
    elif frame.cls == "near-neighbor":
        ok = above_floor and frame.true_label in top2 and NEAR_PCT[0] <= pct <= NEAR_PCT[1]
        why = f"top1={top1} {pct:.1f}% top2={'/'.join(top2)}"
        if not above_floor:
            why += " REJECTED-by-floor"
    elif frame.cls == "out-of-vocab":
        ok = fam < FAM_UNFAMILIAR_MAX
        why = f"fam={fam:.1f} (guess {top1} {pct:.1f}%)"
    else:  # empty
        ok = not above_floor
        why = f"sim={frame.raw_top_sim:.4f} vs floor {floor:.3f}"
    return ok, why


@dataclass
class Result:
    temp: float
    floor: float
    fam_high: float
    passed: int
    total: int
    obj_rate: float  # mean per-object pass rate (tiebreak)
    failing_objects: list[str]

    @property
    def key(self) -> tuple[int, float]:
        return (self.passed, self.obj_rate)


def sweep(
    frames: list[Frame],
    temps: list[float],
    floors: list[float],
    fam_highs: list[float],
    display_labels: list[str],
    n_display: int,
) -> list[Result]:
    objects = sorted({(f.true_label, f.cls) for f in frames})
    results: list[Result] = []
    for temp in temps:
        for floor in floors:
            for fam_high in fam_highs:
                if fam_high <= floor:
                    continue  # degenerate gauge: nothing to map onto
                per_obj: dict[tuple[str, str], list[bool]] = {o: [] for o in objects}
                passed = 0
                for fr in frames:
                    ok, _ = score_frame(
                        fr, temp, floor, fam_high, display_labels, n_display
                    )
                    per_obj[(fr.true_label, fr.cls)].append(ok)
                    passed += ok
                rates = [sum(v) / len(v) for v in per_obj.values() if v]
                failing = [
                    f"{lbl} ({cls})"
                    for (lbl, cls), v in sorted(per_obj.items())
                    if v and not all(v)
                ]
                results.append(
                    Result(
                        temp=temp,
                        floor=floor,
                        fam_high=fam_high,
                        passed=passed,
                        total=len(frames),
                        obj_rate=float(np.mean(rates)) if rates else 0.0,
                        failing_objects=failing,
                    )
                )
    results.sort(key=lambda r: r.key, reverse=True)
    return results


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def pick_winner(
    results: list[Result],
    temps: list[float],
    floors: list[float],
    fam_highs: list[float],
) -> tuple[Result, list[Result]]:
    """Best-scoring tuple, tie-broken toward the CENTRE of the tied plateau.

    Sorting alone hands back the corner of the grid (lowest temp, lowest floor,
    lowest fam_high), which is the single worst member of a tied set: it is one
    lighting change from falling off the plateau. Distance is measured in grid
    INDEX space so the three axes, which have wildly different units, are
    commensurate.
    """
    best_key = results[0].key
    tied = [r for r in results if r.key == best_key]
    idx = (
        {v: i for i, v in enumerate(temps)},
        {v: i for i, v in enumerate(floors)},
        {v: i for i, v in enumerate(fam_highs)},
    )
    med = (
        float(np.median([idx[0][r.temp] for r in tied])),
        float(np.median([idx[1][r.floor] for r in tied])),
        float(np.median([idx[2][r.fam_high] for r in tied])),
    )

    def dist(r: Result) -> float:
        return ((idx[0][r.temp] - med[0]) ** 2
                + (idx[1][r.floor] - med[1]) ** 2
                + (idx[2][r.fam_high] - med[2]) ** 2)

    return min(tied, key=dist), tied


def print_ranked(
    results: list[Result], tied: list[Result], winner: Result, top_n: int
) -> None:
    print("\n=== RANKED PARAMETER TUPLES "
          "(fam_low_sim is pinned == similarity_floor) ===")
    print(f"{'rank':>4}  {'temp':>6}  {'floor':>6}  {'fam_high':>8}  "
          f"{'frames':>9}  {'obj rate':>8}  failing objects")
    best_key = results[0].key
    for i, r in enumerate(results[:top_n], 1):
        mark = "<-" if r is winner else (" *" if r.key == best_key else "  ")
        fails = ", ".join(r.failing_objects) or "-"
        print(f"{i:>4}{mark}{r.temp:>6.1f}  {r.floor:>6.3f}  {r.fam_high:>8.3f}  "
              f"{r.passed:>4}/{r.total:<4}  {r.obj_rate * 100:>7.1f}%  {fails}")
    if len(tied) > 1:
        temps = sorted({r.temp for r in tied})
        floors = sorted({r.floor for r in tied})
        highs = sorted({r.fam_high for r in tied})
        print(f"\n  TIE: {len(tied)} tuples all score {results[0].passed}"
              f"/{results[0].total} frames (obj rate "
              f"{results[0].obj_rate * 100:.1f}%). Rows marked * are tied,")
        print("  '<-' is the chosen winner. The tied plateau spans:")
        print(f"      temperature      {temps[0]:g} .. {temps[-1]:g}")
        print(f"      similarity_floor {floors[0]:g} .. {floors[-1]:g}")
        print(f"      fam_high_sim     {highs[0]:g} .. {highs[-1]:g}")
        print("  The winner is the plateau's CENTRE, not the first row -- a "
              "corner tuple is one\n  lighting change from falling off. If the "
              "plateau runs to a grid edge, widen the grid.")
    print("\n  Ranking is by total FRAMES passed, so objects captured more times "
          "carry more weight.\n"
          "  'obj rate' (mean per-object pass rate) is the tiebreak and is the "
          "capture-count-neutral view.")


def print_winner_breakdown(
    winner: Result, frames: list[Frame], display_labels: list[str], n_display: int
) -> list[str]:
    """Print the per-object reading under `winner`; return objects at 0 passes."""
    print(f"\n=== WINNER: temperature={winner.temp:g}  similarity_floor="
          f"{winner.floor:g}  fam_low_sim={winner.floor:g}  "
          f"fam_high_sim={winner.fam_high:g} ===")
    by_obj: dict[tuple[str, str], list[Frame]] = {}
    for fr in frames:
        by_obj.setdefault((fr.true_label, fr.cls), []).append(fr)

    hard_fails: list[str] = []
    soft_fails: list[str] = []
    zero_pass: list[str] = []
    for (label, cls), group in sorted(by_obj.items()):
        n_ok = 0
        lines = []
        for fr in sorted(group, key=lambda f: f.file):
            ok, why = score_frame(
                fr, winner.temp, winner.floor, winner.fam_high,
                display_labels, n_display,
            )
            n_ok += ok
            fam = fr.familiarity(winner.floor, winner.fam_high)
            margin = fam - FAM_UNFAMILIAR_MAX
            fam_note = ""
            if cls == "out-of-vocab":
                # Print the number and its distance to the threshold: a
                # 32.9-vs-33.1 outcome is fragile, not a clean pass.
                fam_note = f"  [fam margin {margin:+.1f}]"
                if abs(margin) < 5.0:
                    fam_note += " FRAGILE"
            lines.append(
                f"      {'PASS' if ok else 'FAIL'}  {fr.file:<28} "
                f"sim={fr.raw_top_sim:.4f}  {why}{fam_note}"
            )
        if n_ok == 0:
            zero_pass.append(f"{label} ({cls})")
        rank_bad = [fr for fr in group if not fr.rank_ok(display_labels, n_display)]
        status = "OK " if n_ok == len(group) else "FAIL"
        print(f"\n  [{status}] {label}  ({cls})  {n_ok}/{len(group)} frames pass")
        for line in lines:
            print(line)
        if rank_bad:
            print(f"      ^ {len(rank_bad)} frame(s) have the WRONG RANKING "
                  "(true label not in top-1/top-2).")
            print("        Ranking is temperature-invariant, so no tuple in any "
                  "grid can fix this --")
            print("        it needs a vocabulary/prompt/framing change, not a "
                  "calibration change.")
            hard_fails.append(f"{label} ({cls})")
        elif n_ok < len(group):
            soft_fails.append(f"{label} ({cls})")

    print("\n  Objects the winner FAILS:")
    if not hard_fails and not soft_fails:
        print("    none -- every frame passes its class rule.")
    if soft_fails:
        print(f"    tunable (pct/familiarity window miss): {', '.join(soft_fails)}")
    if hard_fails:
        print(f"    NOT tunable (ranking failure): {', '.join(hard_fails)}")
    return zero_pass


# --------------------------------------------------------------------------- #
# --write
# --------------------------------------------------------------------------- #
def write_settings(settings_path: Path, winner: Result) -> None:
    """Write the winning values back into settings.yaml, keeping comments."""
    values = {
        "temperature": winner.temp,
        "similarity_floor": winner.floor,
        "fam_low_sim": winner.floor,  # pinned; see module docstring
        "fam_high_sim": winner.fam_high,
    }
    try:
        from ruamel.yaml import YAML  # type: ignore
    except ImportError:
        log.info("ruamel.yaml not installed -- using line-anchored regex "
                 "replacement instead (comments preserved verbatim)")
        text = settings_path.read_text()
        for key, val in values.items():
            # Anchored on the key at line start so a bare value replace can't
            # hit the wrong key (0.24 appears as both floor and fam_low).
            pattern = re.compile(rf"^(\s*{key}:\s*)[-+0-9.eE]+(.*)$", re.MULTILINE)
            text, n = pattern.subn(rf"\g<1>{val:g}\g<2>", text)
            if n != 1:
                raise SystemExit(
                    f"refusing to write {settings_path}: expected exactly one "
                    f"'{key}:' line, found {n}. Edit by hand."
                )
        settings_path.write_text(text)
    else:
        log.info("using ruamel.yaml round-trip writer")
        yaml = YAML()
        yaml.preserve_quotes = True
        with settings_path.open("r") as f:
            data = yaml.load(f)
        for key, val in values.items():
            data["calibration"][key] = val
        with settings_path.open("w") as f:
            yaml.dump(data, f)
    print(f"\n  WROTE {settings_path}: " +
          ", ".join(f"{k}={v:g}" for k, v in values.items()))
    print("  Restart the server for these to take effect.")


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Grid-sweep CLIP calibration against captured crops.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Grids accept '1,2,3' or 'start:stop:step' (stop inclusive).",
    )
    p.add_argument("--manifest", type=Path, default=REPO_ROOT / "calib" / "manifest.json",
                   help="capture manifest written by /debug/capture")
    p.add_argument("--settings", type=Path, default=REPO_ROOT / "config" / "settings.yaml")
    p.add_argument("--labels", type=Path, default=REPO_ROOT / "config" / "labels.yaml")
    p.add_argument("--temps", default="20:100:5", help="temperature grid")
    p.add_argument("--floors", default="0.20:0.30:0.005",
                   help="similarity_floor grid (fam_low_sim is pinned to it)")
    p.add_argument("--fam-highs", default="0.30:0.40:0.005", help="fam_high_sim grid")
    p.add_argument("--top", type=int, default=10, help="rows in the ranked table")
    p.add_argument("--device", default="mps", help="torch device (mps|cpu|cuda)")
    p.add_argument("--write", action="store_true",
                   help="write the winner into settings.yaml (default: dry run)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    temps = parse_grid(args.temps, "temps")
    floors = parse_grid(args.floors, "floors")
    fam_highs = parse_grid(args.fam_highs, "fam-highs")

    records = load_manifest(args.manifest)
    log.info("manifest: %d records from %s", len(records), args.manifest)

    from foolbot.classifier import Classifier

    log.info("loading CLIP on %s (~7s)...", args.device)
    clf = Classifier(
        labels_path=str(args.labels),
        settings_path=str(args.settings),
        device=args.device,
    )
    log.info("loaded: %d display labels + %d anchors",
             clf.n_display, len(clf.is_display) - clf.n_display)

    frames = compute_frames(records, args.manifest.parent, clf)
    if not frames:
        raise SystemExit("no usable frames in the manifest -- nothing to sweep")
    by_cls: dict[str, int] = {}
    for fr in frames:
        by_cls[fr.cls] = by_cls.get(fr.cls, 0) + 1
    log.info("scored %d frames: %s", len(frames),
             ", ".join(f"{k}={v}" for k, v in sorted(by_cls.items())))
    for cls in VALID_CLS:
        if cls not in by_cls:
            log.warning("no '%s' frames captured -- that rule is unconstrained "
                        "and the sweep may drift on it", cls)

    n_tuples = sum(1 for _ in temps for _ in floors for fh in fam_highs)
    log.info("sweeping %d x %d x %d = %d tuples (fam_high <= floor skipped)",
             len(temps), len(floors), len(fam_highs), n_tuples)
    results = sweep(frames, temps, floors, fam_highs, clf.display_labels, clf.n_display)
    if not results:
        raise SystemExit("empty grid: every fam_high was <= every floor")

    w, tied = pick_winner(results, temps, floors, fam_highs)
    print_ranked(results, tied, w, args.top)
    zero_pass = print_winner_breakdown(w, frames, clf.display_labels, clf.n_display)

    if args.write:
        # settings.yaml currently holds a LIVE-CONFIRMED calibration. A sweep
        # whose best tuple passes nothing has not found a better one -- it has
        # found that the grid or the capture set is wrong. Never let that
        # clobber a working booth.
        if w.passed == 0:
            raise SystemExit(
                "REFUSING to write: the best tuple passes 0 of "
                f"{w.total} frames. Widen the grid (--temps/--floors/"
                "--fam-highs) or re-capture; the current settings.yaml is "
                "left untouched."
            )
        if zero_pass:
            log.warning("winner leaves these objects at 0%% pass: %s -- writing "
                        "anyway, but check the breakdown above first",
                        ", ".join(zero_pass))
        write_settings(args.settings, w)
    else:
        print("\n  DRY RUN -- nothing written. To apply:")
        print(f"    temperature: {w.temp:g}   similarity_floor: {w.floor:g}   "
              f"fam_low_sim: {w.floor:g}   fam_high_sim: {w.fam_high:g}")
        print("    (re-run with --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
