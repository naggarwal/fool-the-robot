# Setting up the backup laptop

The booth runs on one laptop. If that laptop dies at 10am on event day, there
is no booth. This is how to build a second one that can take over.

Do this **at home, with wifi**, not at the venue. The whole point is that event
day needs no network.

**Target:** an Apple Silicon Mac (M-series). An Intel Mac will probably work but
has not been tried. Windows will not — `run.sh` and `stop.sh` are bash scripts,
and the `.bat` equivalents do not exist yet.

---

## 1. Install it

```bash
git clone https://github.com/naggarwal/fool-the-robot.git
cd fool-the-robot
./setup.sh
```

Allow twenty minutes and about 1.7 GB of download. `setup.sh` will:

1. Check the machine — macOS, Apple Silicon, Python 3.12. If Python 3.12 is
   missing it stops and tells you to run `brew install python@3.12`. It will
   not install it for you: that touches the system toolchain, and a surprise
   install on a machine that is supposed to be a known-good backup is the wrong
   move.
2. Build `.venv` and install from `requirements-lock.txt`.
3. Download the CLIP weights (~700 MB) into the local Hugging Face cache, so
   the booth never needs the network again.
4. Prove it works: load the model, classify a frame, find a camera, start the
   real server, and answer `/health`.

It finishes with either **"This laptop is ready to run the booth"** or a list of
what is wrong. There is no middle state, on purpose.

Re-check any time, without reinstalling:

```bash
./setup.sh --verify
```

Start and stop it the same way as the main laptop:

```bash
./run.sh
./stop.sh
```

---

## 2. Why the lockfile

`requirements.txt` says what the booth needs (`torch>=2.2`, and so on).
`requirements-lock.txt` says exactly what the working, calibrated laptop has,
and that is what `setup.sh` installs.

Those are different things. Built from the loose file three weeks from now, the
backup could pull a newer torch and behave subtly differently from the machine
the thresholds were measured on — and a backup that behaves differently is not
a backup.

When you deliberately upgrade the main laptop, refresh the lock:

```bash
./.venv/bin/pip freeze | sort >> requirements-lock.txt   # then tidy the header
```

---

## 3. What does NOT come across

The clone gets you the code and the calibration file. It does not get you a
finished booth. Three things need a human:

### Calibration — the important one

`config/settings.yaml` carries thresholds measured on the *other* laptop, with
*its* webcam, at *its* desk, under *its* lighting. They are a starting point on
a new machine, not an answer.

Run a capture round on the backup with real objects in hand:

```bash
FOOLBOT_DEBUG=1 ./run.sh                             # in one terminal
./.venv/bin/python scripts/capture_round.py          # in another
```

Then read `docs/STATUS.md` for how to turn that into a temperature.

Worth knowing: the temperature in `settings.yaml` is currently `70`, which is
an **estimate**, not a measurement — the vocabulary grew from 42 labels to 90
and the old measured value of `55` no longer holds. Both laptops inherit that
same open question. The file says so in a comment at the top.

### Camera index

`camera.index: 0` in `settings.yaml` is whatever the main laptop's USB webcam
landed on. A different Mac, a different USB port, or a Continuity Camera in
range can shuffle that.

Preflight lists every working camera it finds. If it reports more than one,
check that the configured index is the USB webcam aimed down at the table — not
the laptop's built-in one, which is aimed at faces.

### Voice

The pre-generated audio cache (`cache/`) is not in the repo; it is ~1161 files
and regenerable. Without it the robot falls back to the built-in macOS voice,
which is perfectly good — **the backup will not be silent**. If you want the
nicer voice, set `ELEVENLABS_API_KEY` and run
`scripts/pregenerate_voice.py`, but this is the last thing to worry about.

---

## 4. Before you call it a backup

Do these on the backup laptop itself, not from memory:

- [ ] `./setup.sh` ends with "ready to run the booth"
- [ ] `./run.sh` opens Chrome and the booth page loads
- [ ] Hold an object up — the bars move and the guess changes
- [ ] The screen does **not** show the red "DEMO MODE — guesses are random"
      banner (that means CLIP failed and you are looking at a fake booth)
- [ ] Press `O` — the robot goes to "Robot is resting"; press it again
- [ ] `./stop.sh` — and the webcam light actually goes out
- [ ] Run it once on battery, unplugged, for ten minutes

The fourth one is the one people skip. The stub classifier produces confident,
plausible, entirely random guesses, and from across a table it looks like a
working booth.
