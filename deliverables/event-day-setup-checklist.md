# Setup checklist — "Can You Fool the Robot?"

**Alive Center STEM Exploration Day · Saturday, Aug 15 · Setup 12:00 PM · Booth 1:00–4:00 PM**

The venue setup is unknown, so this is split by deadline: what has to happen
**tonight** (physical or risky), and what fits the **12:00–1:00 window** on site.

---

## A. Tonight — software (≈45 min, blocking)

**The booth is currently running on an uncalibrated guess.** `temperature: 70.0`
is an estimate that has never been checked against a real object. If it's wrong,
every percentage on screen is wrong, and the whole activity is percentages.

Do one capture round with the actual props, backdrop card and LED light you're
taking — set it up on a table the way it'll be at the booth:

```
cd ~/projects/vision
./stop.sh                                   # make sure nothing holds the webcam
FOOLBOT_DEBUG=1 ./run.sh                    # debug flag is required for capture
# in a second terminal:
./.venv/bin/python scripts/capture_round.py
```

It walks you through 9 objects and tells you immediately if a take is bad. You need:
mug · scissors · water bottle · sneaker · dress shoe · **stapler** · **roll of tape** ·
a rock/leaf/pinecone · and one empty-zone shot. The last three are the foolers —
they are deliberately *not* in the vocabulary, so don't substitute them.

Then sweep and write:

```
./.venv/bin/python scripts/calibrate.py --write
./stop.sh && ./run.sh                       # restart WITHOUT the debug flag
```

**Target:** a clear object reads ~70–75% and lands on "Pretty sure!", the
sneaker/dress-shoe pair splits close, and the stapler or tape produces two
near-tied guesses.

### If the sweep doesn't produce a clean winner

You have a known-good fallback: revert to the last **measured** state — set
`temperature: 55.0` in `config/settings.yaml` and remove the 48 labels added
2026-07-26 from `config/labels.yaml`. That configuration was verified live (mug
74%). The cost is a smaller vocabulary, so more of what kids bring will fool the
robot — the fool rate goes *up*, past the 50–75% target, and some fools land on
ordinary objects rather than clever ones.

**A measured 55 beats an unmeasured 70.** Don't run the booth on the estimate.

---

## B. Tonight — printing and paper (can't be fixed at 12:00)

- [ ] **16 challenge cards** from `config/challenges.yaml` — the "why this works"
      note goes on the **back** of each card. Nothing on screen reads this file;
      the cards *are* the deck.
- [ ] **4 signs** from `docs/signage.md` — privacy notice (front edge of the
      table, never behind the basket), leaderboard header, "What is this?" panel,
      table tent. Dark on white, 18pt minimum.
- [ ] **Runbook**, one copy per volunteer — `docs/runbook.md`.
- [ ] **Fill in the two phone numbers** in runbook §9 (yours and the Alive Center
      event lead) before you print. They're still blank.

---

## C. Tonight — the M1 backup

The M1 is only a backup if it can start **with no network**:

- [ ] Repo pulled and current
- [ ] `.venv` built, `./run.sh` starts clean
- [ ] **CLIP weights already cached** (~350 MB). Start it once offline — Wi-Fi
      off — and confirm it classifies. If it downloads at the venue, it isn't a backup.
- [ ] Same `config/settings.yaml` as the M5 **after** tonight's calibration

---

## D. Pack list

**Compute** — M5 laptop + charger · M1 backup + charger · laptop stand (thermals:
it must have air underneath, not flat on a tablecloth)

**Vision** — USB webcam on its gooseneck · **spare USB cable** · grey backdrop
card · clip LED light (this is what makes tonight's calibration transfer)

**Display & sound** — external monitor + its power brick + **the right video
cable and adapter for it** · powered speaker + cable

**Power** — power strip · **extension cord ≥ 15 ft**. You have four draws
(laptop, monitor, LED, speaker) and no idea where the outlet is. Assume it's far.

**Table** — painter's tape for the object zone · basket of props · disinfectant
wipes · whiteboard or big sticky pad + markers for the leaderboard tally

**Paper** — challenge cards · 4 signs · runbook copies

---

## E. On site, 12:00–1:00

1. **Table.** Laptop at the back facing you, monitor at the front facing kids.
2. **Power first.** Find the outlet, run the extension, strip on the floor taped down.
3. **Tape the object zone** on the table. Grey card flat inside it.
4. **Camera** on the gooseneck, aimed **down at the square**, 30–45 cm. Never at faces.
5. **LED light** clipped and pointed at the square.
6. `cd ~/projects/vision && ./run.sh` — wait ~10 s, then `Cmd+Ctrl+F` for fullscreen.
7. **The one check that matters:** hold the mug in the square. *Does the picture
   look like it did last night, and does the mug read ~70%?*
   - **Video blown out or too dark** → the exposure is deliberately locked, so it
     won't self-correct. Edit `camera.exposure_value` in `config/settings.yaml`
     (currently `-6`; **less** negative = brighter) and restart. Change nothing else.
   - **Percentages way off but the picture looks fine** → someone nudged a slider.
     Restart; that reloads the saved calibration.
8. Signs up. Props in the basket. Cards in a stack, face down.
9. Walk each volunteer through runbook §2 (the pitch) and §4 (the three questions).

---

## F. Two things you don't have to worry about

- **No network needed.** Model weights are cached locally, and the cloud voice
  short-circuits cleanly with no API key — the robot speaks through the Mac's
  built-in voice. Venue Wi-Fi being terrible changes nothing.
- **It cannot silently fake it.** If the AI fails to load, the server refuses to
  start rather than serving random guesses. A booth that starts is a real booth.

---

## G. Known gaps — decide how you'll live with them

| Gap | What you do instead |
|---|---|
| **No panic key / mute.** The robot talks and there's no way to silence it fast | Pull the plug on the powered speaker. Restart also silences it |
| **The tuning sliders are visible on the child-facing screen** | If there's no external monitor and the laptop faces the kids, this is a real hazard — a curious hand destroys the calibration. Keep the laptop turned toward you and let kids read the monitor, or stand between them and the keyboard |
| **No leaderboard / confetti on screen** | Whiteboard tally, and you are the celebration |
| **No "that's a person!" deflection** | Camera aim is the only thing keeping faces out of frame. Check it after every bump |

**Recovery for anything at all:** `Ctrl+C` in Terminal → `./run.sh` → wait 10 s →
`Cmd+Ctrl+F`. If it complains about the camera or the port, `./stop.sh` first.
Ten seconds, and nothing you do can make it worse.
