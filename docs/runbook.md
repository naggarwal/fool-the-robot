# Operator runbook — "Can You Fool the Robot?"

**Alive Center STEM Exploration Day · Saturday, August 15 · Booth open 1:00–4:00 PM**

You do not need to know anything about AI to run this booth. Everything you need
is on this page. If something breaks, nothing you do can make it worse — the
whole system restarts in about ten seconds.

---

## 1. Setup (about 10 minutes)

1. **Table.** Laptop at the back, screen facing you. External monitor at the
   front, facing the kids.
2. **Camera.** On its gooseneck, aimed **down at the taped square on the table**.
   Never at faces. About a forearm's length from the table — 30–45 cm.
3. **Backdrop.** Lay the grey card inside the taped square. Clip the LED light so
   it points at the square.
4. **Props.** Basket of objects within a child's reach. Disinfectant wipes beside
   it.
5. **Signs.** Privacy sign at the front of the table where parents can read it.
   Leaderboard sign above the monitor.
6. **Start it.** On the laptop, open Terminal and type:

   ```
   cd ~/projects/vision
   ./run.sh
   ```

   Chrome opens by itself. **Wait about 10 seconds** — the AI takes a moment to
   wake up and the screen says "Show me something!" the whole time it's loading.
7. **Fullscreen.** Click on the Chrome window, press **Cmd+Ctrl+F**. Drag the
   window onto the big monitor first if it isn't there.
8. **Test it.** Hold a shoe in the taped square. You should see bars and a
   familiarity dial move. If they do, you're open.

> **Don't touch the sliders** at the bottom of the screen. Those are the
> calibration and they took a day to get right. If someone nudges one, just
> restart (§5) — that puts everything back.

---

## 2. The ten-second pitch

Say this to every child as they walk up. Word for word is fine.

> "This robot looks through the camera and guesses what you're holding. But it's
> only a guesser, not a know-it-all. **Your job is to trick it.** Want to try?"

Then hand them an object from the basket, or let them use their own.

---

## 3. The loop (aim for 90 seconds)

1. **Let it guess.** Child holds the object in the taped square. Bars appear.
   Read the top guess out loud with the number: *"It's 74% sure that's a mug."*
2. **Point at the dial.** *"And this one says whether it's ever seen anything
   like it before."*
3. **Give them a challenge card.** Read the card out loud, exactly as printed.
   One instruction, nothing more.
4. **Watch for the fool.** Any of these counts, and all three are wins:
   - the top two bars end up close together → *"it can't decide!"*
   - the top bar drops low → *"it's lost!"*
   - the familiarity dial drops to LOW → *"it's never seen anything like that!"*
5. **Ask the questions** in §4. This is the actual point of the booth.
6. **Wipe the object**, put it back, next child.

If a card produces nothing interesting after about 20 seconds, say *"tough
robot!"* and draw a different card. Never let a child stand there feeling like
they failed. **They cannot fail — only the robot can.**

---

## 4. The three questions

Ask these every time. The middle one is the whole activity.

1. **Before:** *"What do you think it'll say?"*
2. **After it gets confused:** *"Why do you think it got confused?"*
   Wait. Let the silence sit. Do not answer for them.
3. **To land it:** *"So does it actually know what that is — or is it guessing?"*

**The answer you're steering toward:** *it only knows the things it was shown
before, and it's never been shown one like that.* Any version of that sentence
from a child is a win. Say so out loud.

**If a parent asks how it works:** "It compares the picture to about fifty short
written descriptions and picks whichever one is closest. It has no idea what a
shoe actually is — it's matching pictures to words." Each challenge card has a
one-line explanation on the back for exactly this.

---

## 5. When something goes wrong

**There is no panic key yet.** *(TBD — a mute key and an operator panel are
specified and being built.)* If the robot is talking and you need it quiet right
now, pull the plug on the powered speaker. The restart below silences it too.

**Your recovery, for absolutely anything:**

1. Click the Terminal window. Press **Ctrl+C**.
2. Type `./run.sh` and press Enter.
3. Wait about 10 seconds. Press **Cmd+Ctrl+F** in Chrome for fullscreen.

If it complains about the camera, first run:

```
pkill -f "uvicorn server:app"
```

then `./run.sh` again. Only one copy can use the webcam at a time.

While you wait, hand the queue a challenge card and ask them to guess what the
robot will say. Dead air is the only real failure.

---

## 6. Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| Screen stuck on "Show me something!" right after starting | The AI is still waking up (~7s). That screen also shows when nothing is in the square, so it looks identical either way | Wait 10 seconds before touching anything |
| Still stuck after 15 seconds, with an object in the square | Object may be too small, too pale, or outside the taped square | Move it into the centre of the square, closer to the camera |
| A pale or shiny object gets no reaction at all | Not enough contrast against the backdrop | Angle the LED light at it, or swap in a darker prop |
| Video is frozen | Camera dropped out | Restart (§5). If it repeats, reseat the USB plug |
| Video is black | Lens cap, or camera aimed at the table edge | Check the aim points into the taped square |
| Numbers look wrong; everything reads 99% or everything reads 5% | Someone dragged a slider | Restart (§5) — that reloads the saved calibration |
| Bottom panel is cut off / needs scrolling | Known issue below 1080px screen height | Ignore it; it's for the operator, not the kids |
| Page is blank or won't load | Server not running | Restart (§5) |
| It guesses right every single time | Camera too close, or props too easy | Reach for the hard cards: close-up, wrapped, in shadow, or something not in the basket at all |
| It's wrong on everything, and it's not fun | Lighting shifted | Re-aim the LED, put the grey backdrop card back flat |
| A child gets upset that it guessed wrong | Framing slipped | "No no — wrong is the *goal*. You just beat the robot." |
| A face appears on screen | Camera has drifted upward | Re-aim it down at the table. **Do not classify faces.** |
| Laptop hot, everything sluggish | Thermals | Make sure it's on the stand with air underneath, not flat on the tablecloth |

---

## 7. Things to say, and things not to say

**Do say:** "it's guessing" · "it only knows what it was shown" · "you fooled
it!" · "that's a really good question"

**Don't say:** "it's smart" · "it knows" · "it's broken" · "you did it wrong"

The robot can be wrong. A child cannot.

---

## 8. What isn't built yet

If a visitor asks about any of this, "that's the next version" is a perfectly
good answer.

| Feature | Status |
|---|---|
| Robot speaks its guess out loud | **TBD** — being wired up. If it's talking on the day, that's expected, not a fault |
| Animated robot face | **TBD** — not built |
| Challenge cards on screen | **TBD** — run them off printed cards for now |
| "Objects That Fooled Me Today" leaderboard on screen | **TBD** — keep a tally on the whiteboard |
| Confetti / celebration when a fool lands | **TBD** — you are the celebration |
| Operator panel and panic key | **TBD** — restart is the recovery |
| Automatic "that's a person!" deflection | **TBD** — camera aim is what keeps faces out of frame |

---

## 9. Numbers to call

- **Naveen Aggarwal (ExplAIned Consulting)** — booth owner: ________________
- **Alive Center event lead** — ________________

*Fill these in before event day.*
