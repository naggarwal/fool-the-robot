# Calibration pass — 2026-07-26

> **SUPERSEDED IN PART.** Every measurement below was taken against a
> **52-prompt** vocabulary (42 display + 10 anchors). The vocabulary later grew
> to **100 prompts** (90 display), which changes the shared softmax denominator
> and therefore every percentage here. The *method* below still stands and is
> what `scripts/calibrate.py` automates; the *numbers* are historical.
> `temperature` is currently an unverified estimate of 70. See `STATUS.md`.
>
> Also note **wallet is now in-vocabulary** (added by request), so its 0.259
> reading below is no longer an out-of-vocab data point.


Live objects held in the detection zone on the M5. All readings below were taken
at the **old** `temperature: 15.0`, which is what makes them directly comparable
to each other and lets the temperature be solved analytically.

## Raw measurements (T=15)

| Object | in vocab? | raw cosine sim | top-1 % | top-1 label |
|---|---|---|---|---|
| scissors | yes | **0.332** | 10% | scissors ✅ |
| water bottle | yes | **0.311** | 9% | water bottle ✅ |
| water bottle (2nd hold) | yes | 0.300 | 8% | water bottle ✅ |
| sneaker / rubber slide | yes | **0.290** | 6% | sneaker ✅ (dress shoe 5, boot 4, sandal 4) |
| pen | yes | **0.274** | 4% | pen ✅ (toothbrush 4, glasses 4, glue stick 4) |
| digital camera | **no** | 0.268 | 4% | phone |
| wallet | **no** | 0.259 | 4% | phone |
| coffee mug | yes | — | — | no result on first attempt (see Finding 3) |

Ranking was correct on every in-vocab object. The classifier is working; only
the calibration was wrong.

## Confirmation round (T=55, live)

| Object | in vocab? | sim | top-1 % | band | familiarity |
|---|---|---|---|---|---|
| **coffee mug** | yes | 0.303 | **74%** | `confident` — "Pretty sure!" | HIGH |
| **roll of tape** | **no** | 0.270 | 21% (water bottle), glasses 19% | `confused` | **LOW** |

**T=55 is confirmed.** The mug at 74% lands exactly in the 65–75% window
predicted for the reconstruction's known downward bias, against a naive
prediction of ~81%. The method was sound and the bias behaved as expected.
74% sits just under the 75–90% target band — close enough to keep, and if a
later round wants it centred, T=60 is the nudge.

The tape roll is the behaviour the whole booth is built to produce: two
near-tied guesses (21% / 19%) plus a LOW familiarity gauge. The robot is
visibly unsure *and* visibly says "this isn't like anything I know" — which is
the "you fooled me!" moment, on an object that genuinely isn't in the vocabulary.

## Finding 1 — temperature was ~3.5× too low (FIXED)

At T=15 everything landed in 4–10%, so the UI sat permanently on
"Wait… I'm confused!" even for a textbook-clear object. Uniform over the 52
labels is 1.9%, so 10% was only ~5× uniform.

Reconstructing the full similarity distribution from the observed top-5
percentages (`s_i - s_j = ln(p_i/p_j) / T`, with the unobserved 47 labels modelled
as a flat background fitted to reproduce p_1 exactly at T=15) and sweeping:

| Object | T=15 | T=45 | **T=55** | T=70 | T=100 |
|---|---|---|---|---|---|
| scissors | 10% | 76% | **90%** ✅ | 98% | 100% |
| water bottle | 8% | 62% | **81%** ✅ | 95% | 100% |
| sneaker vs shoe family | 6% | 30% | **41%** ✅ | 53% | 69% |
| pen (genuine 4-way tie) | 4% | 12% | 15% | 19% | 23% |

**T≈50–65 satisfies both PRD §5.2b targets at once** — clear objects 75–90%,
near-neighbour pair 40–60% — with **T=55 as the midpoint**, now in
`settings.yaml`. T≥70 is confident-wrong territory (95–99% on everything clear);
T≤45 leaves the near-neighbour case stuck under 30%.

**Confidence in that range, by row.** The clear-object row is robust: it depends
on total background mass (1 − Σtop5 ≈ 0.83), known to a few percent relative.
The near-neighbour row is not: it rests on a 6%-vs-5% ratio read off an
integer-rounded UI, and 6.4/4.6 vs 5.5/5.4 differ by ~20× in the recovered sim
gap, which swings the T=55 prediction across roughly 35–55%.

**Two known biases in the reconstruction, both in the same direction:**
1. The UI percentages are EMA-smoothed by `Engine._smooth()` while `raw_top_sim`
   passes through untouched — so each reconstruction paired a smoothed p₁ with
   an unsmoothed s₁.
2. The flat-background model is fitted to reproduce p₁ exactly at T=15, so it
   carries no error there, but by convexity a *varied* background yields a
   larger denominator at T=55 than a flat one.

Both mean the true T=55 percentages should land **at or below** the table above.
A bottle reading 65–75% live is the expected bias (nudge T toward 60–65); only a
wild value (≈40% or ≈97%) would mean the method itself is wrong.

Pen at 15% is not a failure: pen/toothbrush/glasses/glue stick all returned
within one point of each other, so a white cylinder held end-on genuinely is
ambiguous and low confidence is the honest answer.

## Finding 2 — out-of-vocab separation is thin (OPEN, highest risk)

This is the one that matters for the "you fooled me!" mechanic.

```
out-of-vocab:  wallet 0.259 ... camera 0.268 ... tape roll 0.270
in-vocab:                                        pen 0.274 ... sneaker 0.290 ...
                                                 mug 0.303 ... bottle 0.311 ... scissors 0.332
                                                 ^^^^^
                        only 0.004 between the best fake and the worst real object
```

**Ordering is perfect, margin is not.** Across 3 out-of-vocab and 5 in-vocab
objects, every fake sits below every real one — but the tape roll (0.270) and
the pen (0.274) are separated by 0.004, which is within frame-to-frame noise.

The first two fakes (wallet, camera) were both small dark rectangles that both
landed on "phone" — one failure mode sampled twice. The **roll of tape** is the
independent draw that was missing: transparent, round, nothing like a phone. It
came in at 0.270, right alongside them, which **confirms the finding rather than
dissolving it** — the thin margin is real, not an artifact of label adjacency.

### The evidence that settles it: an empty room scores 0.273

Captured via `/debug/capture` with the camera pointed at an empty room, no object
and no person in the zone:

```
empty room:   raw_top_sim = 0.2732      anchor_margin = -0.0502
roll of tape: raw_top_sim = 0.270       (a real object, out-of-vocab)
pen:          raw_top_sim = 0.274       (a real object, IN vocab)
```

**Absolute similarity rates an empty room as more familiar than a roll of tape,
and level with a pen.** The signal the familiarity gauge currently rides on
cannot distinguish "a real object I don't know" from "literally nothing." That
is not a thin margin any more — it is the wrong measurement.

The anchor margin separates the same frames cleanly and with sign, not degree:
empty room **−0.050** (the "none of the above" labels win outright) versus
positive margins for real objects. Synthetic probes agree — blank wall −0.025,
random noise +0.011, a crude banana shape +0.022.

This makes switching `familiarity_mode` to `anchor_margin` the recommended fix
rather than a speculative one. It is still **not** switched on by default,
because the mapping bounds (`fam_margin_low` / `fam_margin_high`) must be set
from real objects before the gauge means anything.

There is *some* separation, but the bands nearly touch. Any `similarity_floor`
set high enough to reject the wallet and camera (≥0.27) would also reject the
pen, a real in-vocab object. Absolute CLIP cosine similarity is known to be
poorly scaled across images, so this is expected rather than surprising.

**Correction (found while building `scripts/calibrate.py`): the floor at 0.24 is
inert — it never fires at all.** An empty zone measures `raw_top_sim`
0.2696–0.2732, *above* 0.24, so nothing in normal operation ever trips it. The
claim below that it is "set LOW to catch a genuinely empty zone" is wrong: it
catches nothing. Raising it far enough to reject an empty zone (0.275+) would
reject every real object too, because an empty zone scores higher than a roll of
tape. **Empty-zone detection therefore rides entirely on `edge_density`** (which
reads a clean 0.000 on a real empty room and is doing the whole job), and the
floor should be treated as vestigial until it is either repurposed against
`anchor_margin` or removed.

**Consequence:** `similarity_floor` cannot carry out-of-vocab detection. It is
therefore set LOW (0.24) to catch only a genuinely empty zone, and the
"unfamiliar" signal is carried by the familiarity gauge instead, whose range was
widened to `0.24 → 0.33` so the observed spread maps across the full gauge:

| Object | sim | familiarity at 0.24→0.33 |
|---|---|---|
| wallet (fake) | 0.259 | 21% → LOW ✅ |
| camera (fake) | 0.268 | 31% → LOW ✅ |
| pen (real) | 0.274 | 38% → LOW-MED ⚠️ |
| sneaker (real) | 0.290 | 56% → MEDIUM |
| water bottle (real) | 0.311 | 79% → HIGH ✅ |
| scissors (real) | 0.332 | 100% → HIGH ✅ |

Observed live: **tape roll 0.270 → LOW ✅** and **mug 0.303 → HIGH ✅**, so the
gauge does the job on real objects at both ends.

That ordering is right, but the pen sits on the wrong side of the line and the
margin is ~1 gauge segment. **Proposed fix, not yet tested:** score familiarity
on the *margin between the best display label and the best anchor label*
(`max(display_sims) - max(anchor_sims)`) rather than absolute display sim. The
10 anchors ("a random object", "an unidentifiable thing", …) already exist for
exactly this purpose and are currently unused by the familiarity path. A margin
is self-normalising per image, which is precisely what absolute sim is not.
Requires exposing anchor sims from `classify()` and one more object round.

## Finding 3 — PARTLY RESOLVED: not a pale-object bug; cause still unknown

**What is settled:** the presence gate does not reject pale smooth objects.
Re-held at T=55, the same white mug against the same pale wall classified
immediately at 74% `confident`. Whatever happened the first time does not
reproduce, and `edge_density_min` needs no change on that account.

**A correction.** This was briefly written up as a "startup race" — the ~7s CLIP
load window showing an identical "Show me something!" screen. That explanation is
wrong as stated: `@app.on_event("startup")` completes *before* uvicorn accepts
connections, so no client can receive an idle frame while the model is loading.
The nearest surviving version is that an already-open tab sat on a stale idle
state across the server restart, but that was not verified either.

**Measured, for the record:**

| scene | edge_density | passes 0.02 gate |
|---|---|---|
| real empty room, nothing in zone | **0.00000** | no ✅ |
| real scene, person + wall art, no object held | 0.01584 | no |
| synthetic smooth mug + hand (clean gradients) | 0.00780 | no |

The empty case reads a true zero, so the gate has ample headroom on that side and
the synthetic probes understate real densities (real photographs carry texture
and sensor noise that synthetic fills do not). **What is still unmeasured is the
value for a real object filling the zone** — objects plainly do pass, since the
mug classified, but the actual number has never been recorded. One
`/debug/capture` with an object in the zone closes this.

Still worth doing regardless: the front end cannot currently distinguish
"connection dropped / server restarting" from "nothing in the zone". Both render
as "Show me something!", which is what made this ambiguous in the first place.

<details><summary>Original unverified writeup</summary>

<details><summary>Original unverified writeup</summary>

### mug was never classified (cause UNVERIFIED at time of writing)

A large white coffee mug filling the detection zone against a pale wall
produced no classification at all — the UI stayed on "Show me something!".

**Two candidate causes, not yet distinguished:**

1. *Presence gate.* The Canny gate (`edge_density_min: 0.02`, thresholds 80/160)
   sees too few edges on a smooth, low-contrast object. Weak supporting evidence:
   a routine scene measured `edge_density: 0.0158`, already under the 0.02
   threshold, so the gate is running close to the line in this room. Against it:
   the mug crop also contained a hand, glasses and beard, which ought to generate
   plenty of edges.
2. *Startup race.* That shot was taken shortly after the 13:51:56 restart, and
   CLIP takes ~7s to load. During that window the engine has no result and the UI
   shows exactly "Show me something!" — indistinguishable from a presence
   rejection at the front end.

Cause 1 would be booth-breaking (pale objects under diffuse gym lighting);
cause 2 is harmless. **Do not act on this until one mug capture settles it** —
`/debug/capture` now reports `edge_density` and `passes_presence` per frame.

</details>

This will happen at the booth with white/pale items and is worse under the
diffuse lighting of a school gym. `/debug/capture` now reports `edge_density`
and `passes_presence` per frame so the threshold can be set from measurements
rather than guessed. Needs: one mug capture + one genuinely-empty capture, then
set `edge_density_min` between the two.

### Consequence for `scripts/calibrate.py`

The sweep scores the `empty` class as `raw_top_sim < similarity_floor`, which is
the rule as originally specified — and by that rule every empty-room frame
**fails at any floor below 0.27**. That is the tool correctly reporting a broken
rule rather than a broken capture. Two things follow:

- Do not "fix" this by raising the floor. A floor above 0.27 rejects every real
  object, since an empty zone outscores a roll of tape.
- The `empty` rule should be rewritten against `edge_density` (clean 0.000 on a
  real empty room) or `anchor_margin` (−0.050 on the same frames) once the
  margin bounds are calibrated. Until then, expect `empty` frames to show as
  failures in the sweep output and read them as expected, not alarming.

## Tooling added this session

- `GET /debug/capture?label=X&cls=clear|near-neighbor|out-of-vocab|empty&n=10&seconds=3`
  saves the exact classified crop (pristine frame, no reticle) to `calib/`,
  appends ground truth to `calib/manifest.json`, and returns per-frame
  `raw_top_sim`, `edge_density`, `passes_presence`, `mean_px` so a bad capture
  is visible immediately.

## Still to do

1. Confirm T=55 live — every reading above is at T=15; the server reset to YAML
   defaults mid-session, so the T=55 numbers are predicted, not observed.
2. Mug + empty captures → set `edge_density_min` (Finding 3).
3. Test the anchor-margin familiarity signal (Finding 2).
4. `scripts/calibrate.py` — fold the reconstruct-and-sweep above into the PRD
   deliverable #8 sweep, running off `calib/manifest.json`.
