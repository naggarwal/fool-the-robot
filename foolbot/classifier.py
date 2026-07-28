"""CLIP zero-shot classifier with calibrated confidence + familiarity meter.

Implements the "Fool the Robot" confidence core (PRD 5.2 / 5.2b, build-brief 1).

Key correctness properties:
  * Text prompts for ALL labels (display + anchors) are encoded ONCE in
    __init__, L2-normalized, and cached. classify() only ever runs the image
    encoder.
  * Confidence uses a tunable temperature applied to cosine similarities, NOT
    CLIP's built-in ~100 logit_scale (which makes everything read 99%).
  * A raw-similarity floor + anchor labels provide an explicit "I don't know"
    path. The same raw top-label similarity drives the familiarity meter.
"""

from __future__ import annotations

import os

import numpy as np
import yaml

import torch
import open_clip
from PIL import Image


def _pick_device(device: str | None = None) -> str:
    if device is not None:
        return device
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Classifier:
    def __init__(
        self,
        labels_path: str = "config/labels.yaml",
        settings_path: str = "config/settings.yaml",
        device: str | None = None,
    ):
        with open(labels_path, "r") as f:
            labels_cfg = yaml.safe_load(f)
        with open(settings_path, "r") as f:
            settings = yaml.safe_load(f)

        self.settings = settings
        model_cfg = settings["model"]
        calib = settings["calibration"]
        bands = settings["bands"]

        # --- Calibration params (live-tunable via set_tuning) ---
        self.temperature = float(calib["temperature"])
        self.floor = float(calib["similarity_floor"])
        self.fam_low_sim = float(calib["fam_low_sim"])
        self.fam_high_sim = float(calib["fam_high_sim"])
        # Familiarity signal selection (PRD 5.2b, calibration doc Finding 1).
        # "absolute"      -> familiarity from raw top DISPLAY similarity (default)
        # "anchor_margin" -> familiarity from (best display sim - best ANCHOR sim)
        # The margin is self-normalising per image, which absolute cosine
        # similarity is not; measured out-of-vocab objects (0.259-0.270) and real
        # ones (0.274-0.332) are separated by only ~0.004 on the absolute scale.
        # Default stays "absolute" until the margin is validated against objects.
        self.familiarity_mode = str(calib.get("familiarity_mode", "absolute"))
        self.fam_margin_low = float(calib.get("fam_margin_low", 0.0))
        self.fam_margin_high = float(calib.get("fam_margin_high", 0.05))
        self.confident_min = float(bands["confident_min"])
        self.confused_max = float(bands["confused_max"])

        # --- Device + model ---
        self.device = _pick_device(device)
        # force_quick_gelu=True: OpenAI's CLIP weights were trained with QuickGELU.
        # open_clip 3.3 builds a plain "ViT-B-32" with standard GELU by default,
        # which mismatches the "openai" weights and degrades the raw cosine-sim
        # distribution that the floor / familiarity map / softmax all depend on.
        # The flag keeps the contract's model name while loading the correct
        # activation (equivalent to the "ViT-B-32-quickgelu" config).
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_cfg["name"], pretrained=model_cfg["pretrained"], force_quick_gelu=True
        )
        model = model.to(self.device).eval()
        self.model = model
        self.preprocess = preprocess
        self.tokenizer = open_clip.get_tokenizer(model_cfg["name"])

        # --- Build prompts for ALL labels (display first, then anchors) ---
        prompt_template = model_cfg["prompt_template"]
        self.display_labels: list[str] = []      # human-readable names, display only
        prompts: list[str] = []                  # text fed to CLIP, all labels
        self.is_display: list[bool] = []         # parallel to prompts

        for entry in labels_cfg.get("display", []):
            self.display_labels.append(entry["label"])
            prompts.append(prompt_template.format(entry["prompt"]))
            self.is_display.append(True)

        self.n_display = len(self.display_labels)

        for entry in labels_cfg.get("anchors", []):
            prompts.append(prompt_template.format(entry["prompt"]))
            self.is_display.append(False)

        self._display_mask = np.array(self.is_display, dtype=bool)

        # --- Encode ALL text ONCE, L2-normalize, cache ---
        with torch.no_grad():
            tokens = self.tokenizer(prompts).to(self.device)
            text_feats = self.model.encode_text(tokens)
            text_feats = text_feats / text_feats.norm(dim=-1, keepdim=True)
        # Cache as a float32 tensor on-device so the per-frame cosine-sim matmul
        # runs in torch (numpy's BLAS matmul spuriously raises FPU-flag warnings
        # on Apple Accelerate even for clean inputs).
        self.text_matrix = text_feats.float().to(self.device)  # (N_labels, D)

    # ------------------------------------------------------------------ #
    def set_tuning(
        self,
        temperature: float | None = None,
        floor: float | None = None,
        fam_low_sim: float | None = None,
        fam_high_sim: float | None = None,
        confident_min: float | None = None,
        confused_max: float | None = None,
        familiarity_mode: str | None = None,
        fam_margin_low: float | None = None,
        fam_margin_high: float | None = None,
    ) -> None:
        """Live-update calibration params. Never reloads model or re-encodes text."""
        if familiarity_mode is not None:
            mode = str(familiarity_mode)
            if mode not in ("absolute", "anchor_margin"):
                raise ValueError(
                    f"familiarity_mode must be 'absolute' or 'anchor_margin', got {mode!r}"
                )
            self.familiarity_mode = mode
        if fam_margin_low is not None:
            self.fam_margin_low = float(fam_margin_low)
        if fam_margin_high is not None:
            self.fam_margin_high = float(fam_margin_high)
        if temperature is not None:
            self.temperature = float(temperature)
        if floor is not None:
            self.floor = float(floor)
        if fam_low_sim is not None:
            self.fam_low_sim = float(fam_low_sim)
        if fam_high_sim is not None:
            self.fam_high_sim = float(fam_high_sim)
        if confident_min is not None:
            self.confident_min = float(confident_min)
        if confused_max is not None:
            self.confused_max = float(confused_max)

    # ------------------------------------------------------------------ #
    def sims(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Cosine similarity of one frame against ALL label embeddings.

        Display labels occupy [:n_display], anchors the remainder. This is the
        single numeric entry point: classify() builds on it, and
        scripts/calibrate.py uses it so an offline sweep and the live server can
        never drift apart on how an image is encoded.
        """
        # BGR (OpenCV) -> RGB -> PIL -> open_clip preprocess transform.
        rgb = frame_bgr[:, :, ::-1]
        pil = Image.fromarray(np.ascontiguousarray(rgb))
        img_t = self.preprocess(pil).unsqueeze(0).to(self.device)

        with torch.no_grad():
            img_feat = self.model.encode_image(img_t)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            # Cosine similarity vs ALL cached label embeddings (torch, on-device).
            sims_t = self.text_matrix @ img_feat.float().squeeze(0)  # (N_labels,)
        return sims_t.cpu().numpy()

    # ------------------------------------------------------------------ #
    def classify(self, frame_bgr: np.ndarray) -> dict:
        sims = self.sims(frame_bgr)

        # Calibrated probabilities: logits = sims * temperature, softmax over ALL.
        logits = sims * self.temperature
        logits = logits - logits.max()  # numerical stability
        exp = np.exp(logits)
        probs = exp / exp.sum()

        # --- top5: 5 highest-prob DISPLAY labels only ---
        display_probs = probs[: self.n_display]
        order = np.argsort(display_probs)[::-1][:5]
        top5 = [
            {"label": self.display_labels[i], "pct": float(display_probs[i] * 100.0)}
            for i in order
        ]

        # --- raw_top_label / raw_top_sim: display label with highest RAW cosine sim ---
        display_sims = sims[: self.n_display]
        raw_top_idx = int(np.argmax(display_sims))
        raw_top_sim = float(display_sims[raw_top_idx])
        raw_top_label = self.display_labels[raw_top_idx]

        # --- anchor margin: how much better does the best OBJECT label fit than
        # the best "none of the above" label? Always computed, even when it is
        # not the active signal, so it can be validated from live captures
        # without a code change. See calibration doc Finding 1.
        anchor_sims = sims[self.n_display:]
        if anchor_sims.size:
            raw_anchor_idx = int(np.argmax(anchor_sims))
            raw_anchor_sim = float(anchor_sims[raw_anchor_idx])
        else:
            raw_anchor_idx, raw_anchor_sim = -1, 0.0
        anchor_margin = float(raw_top_sim - raw_anchor_sim)

        # --- familiarity: map the active signal onto [0..100], clamped ---
        if self.familiarity_mode == "anchor_margin":
            value, lo, hi = anchor_margin, self.fam_margin_low, self.fam_margin_high
        else:
            value, lo, hi = raw_top_sim, self.fam_low_sim, self.fam_high_sim
        span = hi - lo
        if span <= 0:
            familiarity = 100.0 if value >= hi else 0.0
        else:
            familiarity = (value - lo) / span * 100.0
        familiarity = float(max(0.0, min(100.0, familiarity)))

        # --- band ---
        top_pct = top5[0]["pct"] if top5 else 0.0
        if raw_top_sim < self.floor:
            band = "unknown"
        elif top_pct >= self.confident_min:
            band = "confident"
        elif top_pct < self.confused_max:
            band = "confused"
        else:
            band = "hedging"

        return {
            "top5": top5,
            "familiarity": familiarity,
            "band": band,
            "raw_top_sim": raw_top_sim,
            "raw_top_label": raw_top_label,
            # instrumentation for the anchor-margin familiarity signal
            "raw_anchor_sim": raw_anchor_sim,
            "anchor_margin": anchor_margin,
            "familiarity_mode": self.familiarity_mode,
            "temperature": float(self.temperature),
            "floor": float(self.floor),
            "fam_low_sim": float(self.fam_low_sim),
            "fam_high_sim": float(self.fam_high_sim),
        }


if __name__ == "__main__":
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    labels_path = os.path.join(root, "config", "labels.yaml")
    settings_path = os.path.join(root, "config", "settings.yaml")

    print("Loading classifier (first run downloads CLIP weights ~350MB)...")
    clf = Classifier(labels_path=labels_path, settings_path=settings_path)
    print(f"Device: {clf.device}  |  labels: {clf.n_display} display + "
          f"{len(clf.is_display) - clf.n_display} anchors")

    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, size=(720, 1280, 3), dtype=np.uint8)  # BGR
    result = clf.classify(frame)
    print("\nclassify() result:")
    print(json.dumps(result, indent=2))

    # Exercise set_tuning: verify live update with no reload.
    clf.set_tuning(temperature=8.0, confident_min=60, confused_max=30)
    result2 = clf.classify(frame)
    print(f"\nAfter set_tuning(temperature=8.0): band={result2['band']} "
          f"top1={result2['top5'][0]['pct']:.2f}% temp={result2['temperature']}")
