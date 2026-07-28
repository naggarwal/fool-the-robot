#!/usr/bin/env python3
"""Render every possible utterance to the Tier 1 voice cache (PRD 5.4).

WHY: at the event, venue Wi-Fi will be shared with three hundred people. A cache
hit plays instantly from disk with zero network dependency, so the goal is that
~100% of lines are pre-rendered before the doors open. The copy constraints in
config/phrases.yaml (never speak a percentage, never speak two labels in one
line) exist precisely so the utterance set is finite: templates x display
labels, enumerable here in advance.

WHY INCREMENTAL: files are keyed by sha256(voice, model, format, text), so any
utterance already on disk is skipped. The phrase list and the label list get
edited repeatedly in the run-up to the event, and a full re-render each time
burns paid quota (a full pass is on the order of a hundred thousand characters).
Editing one phrase should cost one phrase, not one month.

Runs fine with NO API key: it reports exactly what it WOULD generate plus the
character count, which is the number you need to pick an ElevenLabs plan tier.
The key is read from $ELEVENLABS_API_KEY and is never printed or logged.

Usage:
    ./.venv/bin/python scripts/pregenerate_voice.py            # dry run summary
    ./.venv/bin/python scripts/pregenerate_voice.py --generate # actually render
    ./.venv/bin/python scripts/pregenerate_voice.py --generate --limit 20
    ./.venv/bin/python scripts/pregenerate_voice.py --prune    # delete orphans
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from foolbot.voice import (  # noqa: E402
    ELEVEN_FORMAT,
    ELEVEN_MODEL,
    ELEVEN_VOICE,
    cache_path,
    elevenlabs_synthesize,
    enumerate_utterances,
    format_ext,
    load_display_labels,
    load_phrases,
    write_cache_atomic,
)

log = logging.getLogger("pregenerate_voice")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--phrases", default=os.path.join(REPO_ROOT, "config", "phrases.yaml"))
    p.add_argument("--labels", default=os.path.join(REPO_ROOT, "config", "labels.yaml"))
    p.add_argument("--cache-dir", default=os.path.join(REPO_ROOT, "cache", "voice"))
    p.add_argument("--voice", default=ELEVEN_VOICE, help="ElevenLabs voice id")
    p.add_argument("--model", default=ELEVEN_MODEL)
    p.add_argument("--format", dest="fmt", default=ELEVEN_FORMAT)
    p.add_argument("--generate", action="store_true",
                   help="actually call the API (default is a dry run)")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after N generations (quota safety valve)")
    p.add_argument("--deadline", type=float, default=20.0,
                   help="per-request seconds; generous here, unlike the 1.2s "
                        "runtime deadline -- this is a batch job, not the booth")
    p.add_argument("--sleep", type=float, default=0.05,
                   help="pause between requests, to be polite to the API")
    p.add_argument("--prune", action="store_true",
                   help="delete cache files no longer reachable from phrases x labels")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    phrases = load_phrases(args.phrases)          # validates the copy rules
    labels = load_display_labels(args.labels)     # anchors are never spoken
    utterances = enumerate_utterances(phrases, labels)

    os.makedirs(args.cache_dir, exist_ok=True)
    ext = format_ext(args.fmt)

    wanted: dict[str, tuple[str, str]] = {}       # path -> (state, text)
    for state, text in utterances:
        path = cache_path(args.cache_dir, args.voice, args.model, args.fmt, text)
        wanted[path] = (state, text)

    missing = [(p, s, t) for p, (s, t) in wanted.items() if not os.path.exists(p)]
    have = len(wanted) - len(missing)
    chars_all = sum(len(t) for _, t in utterances)
    chars_missing = sum(len(t) for _, _, t in missing)

    per_state: dict[str, list[int]] = {}
    for state, text in utterances:
        per_state.setdefault(state, [0, 0])
        per_state[state][0] += 1
        per_state[state][1] += len(text)

    print(f"phrases   : {args.phrases}")
    print(f"labels    : {len(labels)} display labels (anchors excluded, never spoken)")
    print(f"cache dir : {args.cache_dir}  (voice={args.voice} model={args.model} "
          f"format={args.fmt} ext={ext})")
    print()
    print(f"{'state':<12}{'templates':>10}{'utterances':>12}{'chars':>10}")
    for state in per_state:
        n_tmpl = len(phrases[state])
        print(f"{state:<12}{n_tmpl:>10}{per_state[state][0]:>12}{per_state[state][1]:>10}")
    print(f"{'TOTAL':<12}{sum(len(v) for v in phrases.values()):>10}"
          f"{len(utterances):>12}{chars_all:>10}")
    print()
    print(f"already cached : {have}")
    print(f"to generate    : {len(missing)}  ({chars_missing} characters)")
    print(f"full re-render : {len(utterances)} files ({chars_all} characters)")

    if args.prune:
        n = prune(args.cache_dir, set(wanted), ext)
        print(f"pruned         : {n} orphaned file(s)")

    if not missing:
        print("\nCache is complete. Nothing to do.")
        return 0

    api_key = os.environ.get("ELEVENLABS_API_KEY") or None
    if not args.generate:
        print("\nDRY RUN. Re-run with --generate to render the missing files.")
        if not api_key:
            print("(ELEVENLABS_API_KEY is not set; generation would be impossible.)")
        for path, state, text in missing[:10]:
            print(f"  would generate [{state}] {text!r} -> {os.path.basename(path)}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")
        return 0

    if not api_key:
        print("\nERROR: --generate requires ELEVENLABS_API_KEY in the environment.")
        print("Set it in the shell that runs this script; never commit it.")
        return 2

    todo = missing[: args.limit] if args.limit else missing
    print(f"\nGenerating {len(todo)} file(s)...")
    ok = fail = 0
    t0 = time.monotonic()
    for i, (path, state, text) in enumerate(todo, 1):
        data = elevenlabs_synthesize(
            text, api_key=api_key, voice=args.voice, model=args.model,
            fmt=args.fmt, deadline_s=args.deadline,
        )
        if data:
            write_cache_atomic(path, data)
            ok += 1
            log.debug("[%d/%d] %s -> %s", i, len(todo), text, os.path.basename(path))
        else:
            fail += 1
            log.warning("[%d/%d] FAILED (left uncached, safe to re-run): %r",
                        i, len(todo), text)
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}  ok={ok} failed={fail}  "
                  f"{time.monotonic() - t0:.0f}s")
        if args.sleep:
            time.sleep(args.sleep)

    print(f"\nDone. generated={ok} failed={fail}. "
          "Re-run to retry failures (successful files are skipped).")
    return 0 if fail == 0 else 1


def prune(cache_dir: str, keep: set[str], ext: str) -> int:
    """Delete cache files not reachable from the current phrases x labels set."""
    removed = 0
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if not os.path.isfile(path):
            continue
        if name.endswith(".part"):
            os.remove(path)          # truncated leftover from a killed run
            removed += 1
            continue
        if not name.endswith(ext):
            continue                 # a different format's cache; leave it alone
        if path not in keep:
            os.remove(path)
            removed += 1
    return removed


if __name__ == "__main__":
    raise SystemExit(main())
