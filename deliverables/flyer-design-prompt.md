# Flyer design prompt — "Can You Fool the Robot?"

For the ExplAIned Consulting booth at Alive Center STEM Exploration Day,
Sat Aug 15 2026. Copy the block below into your design tool of choice.

**Tool note:** this flyer is text-heavy (90 words, a labelled diagram, exact
percentages). Image generators — Midjourney, DALL·E, Firefly, Nano Banana —
will mangle every one of those. Use a layout tool: Canva, Figma, InDesign, or
ask Claude to build it as an HTML page and print to PDF. Give an image
generator only the robot-face illustration, if you want one at all.

**Assets:**
- Logo: `~/projects/explained-consulting-website/public/Explained_logo.png`
- Brand blue `#0077FF` · near-black `#0A0A0A` · white
- Headings Poppins (600/700) · body Inter (400/500)

---

## THE PROMPT

Design a single-sided letter-size (8.5 × 11 in) portrait flyer, print-ready at
300 dpi with 0.25 in bleed, explaining how an AI image-recognition booth works.

**Audience:** high school students and their parents, read while standing at a
booth. Reading level: 9th–10th grade. Explain the mechanism plainly, no jargon
without an immediate plain-English gloss, no hype, no exclamation marks outside
the title.

**Brand:** ExplAIned Consulting. Primary blue #0077FF, near-black #0A0A0A,
white. Headings in Poppins SemiBold, body in Inter Regular at 11pt minimum.
Print on a white background with dark ink and blue accents — not the dark web
theme — so it stays readable under fluorescent gym lighting and doesn't drink
toner. Logo bottom-left in the footer, roughly 1.2 in wide, with the line
"Built by ExplAIned Consulting · explainedconsulting.com" beside it. One
accent rule of #0077FF across the top edge. Generous white space; this is an
explainer, not a poster.

### Layout, top to bottom

**1. Title block (~15%)**
Headline: **Can You Fool the Robot?**
Subhead: *An AI that guesses what you're holding — and shows you how sure it is.*
Small kicker above the headline in blue caps: HOW IT ACTUALLY WORKS

**2. The diagram (~35%) — the centrepiece, give it the most room**

A left-to-right flow with five labelled stages. Clean vector line art, blue and
black on white, no drop shadows, no 3D, no stock photography.

```
  [ camera ]        [ the picture becomes         [ 100 written
      |               a list of numbers ]           descriptions ]
      |                      |                       |
   your object  ------->  IMAGE VECTOR   <---->   TEXT VECTORS
                                |                       |
                                +-----------+-----------+
                                            |
                                    [ which is closest? ]
                                            |
                          +-----------------+------------------+
                          |                                    |
                 WHICH ONE IS IT?                    DOES IT LOOK FAMILIAR?
                 ranked bars, always                 a separate dial that can
                 adds to 100%                        drop even when a bar wins
```

Caption each stage in one short sentence:
- **Camera** — Takes a picture of just the box on the table. Nothing is saved.
- **Image → numbers** — The model turns the picture into a list of ~512
  numbers that describe its visual features. A photo of anything becomes a
  point in the same space.
- **Words → numbers** — Every object the robot knows is written as a short
  sentence, *"a photo of a sneaker,"* and turned into numbers the same way.
- **Compare** — The robot measures which sentence lands closest to the
  picture. Closest wins.
- **Two answers, not one** — The bars rank its guesses against each other, so
  something always wins. The dial asks a different question: does this look
  like *anything* it has seen? Show it something new and the dial drops while
  the bars still look confident. That gap is the whole point.

Pull-quote in blue beside the diagram:
> It has never held a shoe. It matches pictures to words — and it will always
> pick something, even when the right answer isn't on its list.

**3. What it knows (~25%)**

Header: **It knows 90 things. Here are a few.**
Sub-line: *Bring it a 91st.*

Do **not** print the full list — a complete list turns the booth into a
checklist and hands away every answer. Show a sample instead, set as three or
four columns of short chips or a light-ruled grid, generously spaced, at body
size rather than fine print.

*Shoes:* sneaker · dress shoe · boot · sandal
*School:* pencil · marker · scissors · notebook
*Toys:* LEGO brick · toy dinosaur · yo-yo · dice
*Kitchen:* mug · water bottle · spoon
*Pocket:* key · coin · wallet · watch
*Tech:* phone · earbuds · calculator

Directly beneath, a boxed callout in blue — this is the flyer's hook, so give
it real weight:

> **The other 84 are a mystery.** Part of the game is working out where the
> gaps are. Some categories it knows well. Others it has never heard of at all.

Footnote in small italics: *Plus 10 hidden "none of the above" descriptions
that catch things the robot doesn't recognise.*

**4. Where this shows up in the real world (~20%)**

Header: **The same trick, outside this booth**
Four to six short items, each one line of bold label + one sentence. Use small
blue line icons, not photographs.

- **Photo search** — Typing "dog on a beach" into your camera roll works
  because your phone matched those words against pictures, exactly like this.
- **Alt-text for blind users** — Screen readers describe images by finding the
  words that fit them best.
- **Content moderation** — Platforms flag images by comparing them against
  written descriptions of what isn't allowed.
- **Shopping** — "Find me this jacket" from a photo is the same
  closest-match search over a product catalogue.
- **Medical imaging** — Models rank likely findings on a scan. A radiologist
  decides; the model ranks.
- **Self-driving cars** — Perception systems classify what's ahead, and a
  wrong confident answer is the dangerous kind.

Closing line under the group, set in blue:
> Every one of these systems always returns an answer. Knowing how sure it is
> — and whether it has ever seen anything like this before — is what separates
> a useful AI from a confident wrong one. That's what this booth lets you test
> with your own hands.

**5. Footer strip**
Logo + "Built by ExplAIned Consulting · "https://explained.consulting" on the left.
On the right, in small type: **This camera doesn't record.** Nothing is saved,
nothing is uploaded, no internet connection. The model runs entirely on the
laptop in front of you.

### Constraints
- Body text never below 11pt; the word list never below 8pt.
- Dark text on white throughout. No gradient fills behind text.
- No AI-generated humans, no stock-photo children, no robot mascot with a
  bubble head. Line art only.
- Everything fits one side. Do not spill to a second page.

---

## Before you print — check these

- **The 90 count.** If `config/labels.yaml` changes again, three lines go
  stale: "It knows 90 things", "bring it a 91st", and "the other 84 are a
  mystery". Verify with
  `./.venv/bin/python -c "import yaml;d=yaml.safe_load(open('config/labels.yaml'));print(len(d['display']),len(d['anchors']))"`
- **Sample items must stay in vocabulary.** Every object named on the flyer is
  a promise the robot can recognise it. Re-check them against `labels.yaml` if
  the vocabulary is edited.
- ~~`docs/signage.md`, `docs/runbook.md`, `README.md` and
  `config/challenges.yaml` still say 42~~ — **fixed 2026-08-11**, all now read
  90 display + 10 anchors.
- **No percentages on the flyer.** Deliberate — the calibration round isn't
  finished, so any specific number printed today may be wrong on the day.
