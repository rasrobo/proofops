# Meme brief — "I'm a real dev" (by golly)

## The joke, precisely

The meme is **Pinocchio (1940) with the subtitle swapped**: "I'm… I'm a real developer!" Every
frame of it is a *claim*. ProofOps exists to put a receipt next to a claim. So the meme and the
product are the same picture from two sides, and the image set writes itself:

> **The puppet boasts. The cricket reads the receipt.**

Jiminy Cricket is the conscience who keeps score of the lies — that is the product. He is also the
only character in the frame holding a document. Do not make him cute; make him bored and factual.
The comedy is the temperature difference: 1950s ad-man enthusiasm above, flat machine output below.

Lineage to cite if anyone asks: Pinocchio "I'm a real boy" → subtitle-swap "I'm a real developer"
(the meme as used on Yarn/Reddit); "by golly" is a minced oath from US print English (Lowell, 1848);
the modern echo is the parody O'Reilly cover *Vibe Coding: I'm a Developer Now*.

## Three rules that decide whether it lands

1. **Claim on top, receipt at the bottom.** Never the reverse, never side by side. The eye reads the
   boast, laughs, drops to the bottom, and stops laughing.
2. **The receipt is a real string from the tool.** `claimable: false`. `observed_status: null`.
   `INCOMPLETE — 2 of 2 checks could not be performed`. `Ran 0 tests ... OK`. Invented evidence
   would be the exact sin the product catches, in the product's own marketing.
3. **Never explain the joke in the caption.** No "this is why verification matters". If the image
   needs the explanation, the image is wrong.

## Character sheet — reuse verbatim, or the set stops looking like a set

> a wooden marionette with visible ball joints and strings running up out of frame, painted
> cheerful face, slightly too confident, wearing a short-sleeved button-up shirt and a too-big
> necktie, seated at a mechanical keyboard

Style block (append to every prompt):

> 1950s American print advertising illustration, gouache with halftone dot texture, warm cream
> paper, teal and rust palette, soft studio lighting, slight paper grain, mid-century composition,
> flat painted background — **no text, no letters, no logos**

**Text policy: generate zero text.** Image models misspell, and a meme with a broken word reads as
sloppy. Compose the caption and the receipt strip in HTML/Canva over the art. It also means one
generation serves every language and every receipt line.

## The eight prompts

Each: one idea, one composition, no text. Copy the style block in every time.

### 1 · "By golly, I'm a real dev" — the hero (4:5)
```
Wooden marionette with visible ball joints and strings running out of frame, painted cheerful
face, short-sleeved shirt and too-big necktie, seated at a mechanical keyboard, one hand raised
mid-boast, mouth open, chest out, laptop screen glowing on his face. Three-quarter shot, eye
level, strings visible against a plain wall.
[style block] --ar 4:5 --no text, letters, watermark, extra fingers
```
Receipt strip: `[FAIL] health-reachable · observed_status: null`

### 2 · "Shipped it" — the nose (1:1)
```
Same marionette in profile, nose extended unnaturally straight like a wooden ruler with faint
measurement marks, pointing at a terminal window, other hand on hip. Waist-up, side-on,
background a plain painted wall.
[style block] --ar 1:1 --no text
```
Receipt strip: `ProofOps run PO-… INCOMPLETE · not_run: health-reachable, says-ok`

### 3 · "All tests passing" — the empty scoreboard (4:5)
```
Same marionette standing proudly in front of a huge blank mid-century scoreboard, arms
outstretched, presenting it. Low angle so the board dominates the frame, puppet small at the
bottom, scoreboard panels empty.
[style block] --ar 4:5 --no text, numbers
```
Receipt strip: `Ran 0 tests in 0.00s · OK` (exit 0 with nothing collected — the real overclaim)

### 4 · "Trust me, I tested it" — the certificate (1:1)
```
Same marionette receiving an empty framed certificate from an arm entering frame at the edge,
shaking hands, beaming. Frontal, mid-shot, the frame glass catching a highlight, certificate
blank.
[style block] --ar 1:1 --no text
```
Receipt strip: `claimable: false`

### 5 · "We all agree it works" — the committee (16:9)
```
Three identical wooden marionettes around a mid-century boardroom table, all strings running up
out of frame to the same point above, one raising a hand to vote, papers scattered, coffee cups.
Wide shot, slightly above table height, empty boardroom wall behind.
[style block] --ar 16:9 --no text
```
Receipt strip: `not_verified: 3 checks could not be performed`

### 6 · "Vibe coding since Tuesday" — the hobby horse (4:5)
```
Same marionette riding a child's rocking horse that has a keyboard nailed to its neck, holding
the reins like a cowboy, hat askew. Full body, slight low angle, plain wall, spotlight pool on
the floor.
[style block] --ar 4:5 --no text
```
Receipt strip: `[NOT RUN] deploy-check: commands are disabled for this run`

### 7 · "The cricket" — the turn (1:1) — *use this one to introduce the product*
```
A small cricket in a top hat and tails sitting on the corner of the marionette's keyboard,
holding a long printed paper strip with both hands, reading it without expression. The
marionette's huge painted face blurred in the background behind him, out of focus. Macro
framing, shallow depth of field, cricket sharp, warm desk lamp from the left.
[style block] --ar 1:1 --no text on the paper strip
```
Receipt strip (composite): `[PASS] reachable` above `[FAIL] says-ok · observed: "degraded"`
This is the whole product in one frame: the endpoint answers 200 *and* the body admits the truth.

### 8 · "Back in my day" — the grandpa (4:5)
```
Same marionette aged up: grey painted hair, suspenders, reading glasses, holding a chunky
1980s mobile phone, finger raised mid-lecture, standing behind a workbench of hand tools and a
modern laptop pushed to the side. Waist-up, three-quarter angle.
[style block] --ar 4:5 --no text
```
Receipt strip: `plan sha256:eb01b6d8… · unchanged since the claim`

## Expression bank (for captions, never in the art)

by golly · gee willikers · land sakes · hot dog · well, I'll be · jumpin' Jehoshaphat ·
great Scott · by jingo · criminy · hold your horses · now we're cooking with gas · she's a beaut ·
the bee's knees · jiminy cricket

Pair each with a receipt that contradicts it, in one line, no punctuation drama:

| caption | receipt |
|---|---|
| "By golly, it's deployed." | `[FAIL] health-reachable · observed_status: null` |
| "Gee willikers, all tests pass." | `Ran 0 tests in 0.00s · OK` |
| "Land sakes, I'm a real dev." | `claimable: false` |
| "Hot dog, shipped it." | `INCOMPLETE — 2 of 2 checks could not be performed` |
| "Trust me, I tested it." | `[NOT RUN] the command was never approved` |
| "Well, I'll be — it works." | `observed: {"status": "degraded"} · http_status: 200` |

## Where each asset goes

- **1, 3, 6** → X post images (4:5 crops well to 16:9 for the timeline).
- **7** → the post that introduces the product; it is the only one that explains nothing and still
  explains everything.
- **2, 4, 5, 8** → replies and quote-tweets; keep the main post to one image.
- **Alt text for every image** — it is also the caption the screen-reader user gets, and it is where
  the joke can be told in words when the image fails to load: "A wooden puppet in a necktie,
  hand raised mid-boast, above a printed line reading claimable: false."

## Guardrails

- **Marketing only.** These never go in `plugin-catalog/proofops.yaml`, the README hero or the docs:
  a maintainer reviewing a verification tool does not want a puppet in the diff.
- **No real receipts.** No hostnames, no plan names from a live service, no customer data. Use the
  shipped demo's own outputs (`says-ok`, `health-reachable`, `observed: degraded`) which are already
  public and already staged.
- **No third-party characters on the image.** The Pinocchio resemblance is a wooden puppet and a
  cricket in a top hat — a type, not a Disney still. Do not prompt for "Pinocchio", "Disney",
  "Jiminy Cricket" or a film still: it is both a rights problem and a bad generation.
- **Do not put a FAIL in the art that the product never produced.** If a receipt line is invented,
  the joke becomes the thing ProofOps catches.
- **One puppet, one cricket, one palette** for the whole set, or it reads as eight unrelated memes.

## Production notes

- Generate at 4:5 and 1:1 at 2× (2048px long edge); crop, do not re-generate, for 16:9.
- Keep a fixed seed per character once you like one — the set's cohesion is worth more than any
  single better frame.
- Halftone overlay at 8–12% on the final composite, so the composited caption sits in the same
  grain as the illustration.
- Caption type: condensed mid-century grotesque, all caps, tracked wide; receipt type: monospace,
  lowercase, 60% opacity — it must look like a terminal, not a poster.
