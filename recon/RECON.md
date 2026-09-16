# Recon — higgsfield.ai

Notes taken while walking the product on 2026-09-16. Screenshots in `recon/screens/`.

## What it actually is

An AI-native creative suite. Text or reference images in, images / video / audio out.
Commercially it is a credit subscription wrapped around a rotating catalogue of
third-party and in-house models, and the thing that makes it spread is not the models —
it is the **preset library**. "Floating fall", "Earth zoom", "Monster dab". Named,
art-directed, one-click viral video recipes.

## Information architecture

Top nav, left to right:

| Route | Surface |
|---|---|
| `/` | Explore — masonry feed of community generations, auto-playing video |
| `/ai/image?model=…` | Image composer |
| `/ai/video` | Video composer |
| `/audio` | Audio / voice |
| `/mcp` | MCP + CLI ("turn Claude into a creative engine") |
| `/gpt-astra` | Motion Designer — After Effects via ChatGPT |
| `/ai/video?model=genjutsu` | Genjutsu — motion transfer / reality manipulation |
| `/effects` | Effects library |
| `/effects/examples/<slug>` | One effect: name, description, example reel, "Try for free" |
| `/effects/use/<slug>` | Apply that effect (auth-gated) |
| `/generate` | Cinema Studio |
| `/marketing-studio` | Marketing Studio |
| `/supercomputer` | Agent, "powered by GPT-6 Astra" |
| `/3d-jutsu` | 3D assets |
| `/layers` | Canvas / layer editor |
| `/academy`, `/community`, `/contests` | Education, social, competitions |
| `/pricing`, `/enterprise` | Commerce |

That is **fourteen** top-level product surfaces. It is an enormous menu and it is the
first thing a new user has to parse.

## The model catalogue

Surfaced as cards on the home page, each tagged Image or Video:

- **Seedance 2.5** — flagship video, 1080p, tagged TOP
- **Seedance 2.0 / 2.0 Fast / 2.0 Mini** — cheaper video tiers, up to 4K
- **Nano Banana Pro / Nano Banana 2** — image
- **Kling 3.0** — video
- **GPT Image 2** — image (default on `/ai/image`)
- **Genjutsu** — in-house, motion transfer
- **GPT-6 Astra** — the agent behind Supercomputer

Models rotate. The UI treats a model as a first-class selectable object with its own
price, capabilities and badges.

## Commercial model

Credits, monthly, three individual tiers plus business:

| Plan | Credits/mo | Annual price | Notes |
|---|---|---|---|
| Starter | 270 | $19 | no Seedance 2.5, max 2 videos / 4 images in parallel |
| Plus | 1,200 | $47 (from $59) | all Seedance models, unlimited parallel |
| Ultra | 3,000 (slider to 6k / 9k) | $99 (from $129) | lowest cost per credit, unlimited marketplace |

Their own conversion, stated on the card: **270 credits ≈ 135 Nano Banana Pro images**
(2 credits an image) **≈ 15 Seedance 2.0 Fast videos** (~18 credits a video). That ratio
— video costs roughly 9× an image — is the single most important number in the product
and it is buried in small grey text on the pricing page.

Also sold: "unlimited & free gens" on specific models for 7-day windows, which is the
real hook on the upgrade path.

## What the product does well

- The **effects library** is the best idea in here. A named, described, visually
  demonstrated preset removes the blank-prompt problem entirely.
- The masonry feed of real output is a better advert than any hero copy.
- Model choice is a first-class citizen, not buried in a settings drawer.

## What is bad, and what I am going to do differently

1. **Fourteen top-level surfaces.** Cinema Studio, Marketing Studio, Supercomputer,
   Genjutsu, 3D Jutsu, Layers, MCP, Academy, Contests. Several are the same generate
   loop with different chrome. A first-time user cannot tell where to start.
   → **One composer.** Mode and model are controls inside it, not separate apps.

2. **Prompts are hidden.** The feed is full of output you cannot learn from. You can
   see a beautiful clip and have no idea how it was made.
   → **Every feed item exposes its full prompt, model and parameters, and has a Remix
   button that loads them straight into the composer.** This is the change I would
   argue hardest for.

3. **Cost is invisible until it is spent.** Nothing in the composer tells you what a
   generation will cost before you press the button; you reverse-engineer it from a
   footnote on the pricing page.
   → **Live credit cost on the button**, itemised, before you commit. Plus a real
   ledger you can audit.

4. **The signed-out state is a wall.** `/ai/image` renders an empty black page when
   you are not logged in. `/effects/use/<slug>` silently bounces back to the examples
   page. No explanation, no preview of the thing you are being asked to pay for.
   → **The composer works signed out.** You get free credits, you generate, you are
   asked to make an account only when you want to keep the work.

5. **Jobs are modal.** Generation ties you to the page you started it on.
   → **A persistent job tray.** Start a render, keep browsing, get it when it lands.

## What I am cutting, deliberately

Audio, 3D, the canvas/layers editor, MCP + CLI, the ChatGPT plugin, Academy, Contests,
Community profiles, Enterprise, and both "Studios". They are either a different product
(3D, audio), a distribution channel rather than a product (MCP, ChatGPT plugin), or the
same generate loop re-skinned (Cinema Studio, Marketing Studio).

Building the generate → job → library → remix loop properly is worth more than
fourteen shallow surfaces.
