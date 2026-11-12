# Pino: what is needed

**Purpose:** One document listing everything required to build Pino, a small local AI companion that lives in his own world and prompts himself through needs and feelings.

**Audience:** The builder (you) and any coding agent working in this folder.

**Last Updated:** 2026-11-12

**Status:** Draft. The agent itself is not built yet. Three browser prototypes exist in `prototype/`; the newest is `world-demo.html`.

---

## Quick navigation

- [Overview](#overview)
- [Target behaviour](#target-behaviour)
- [Machine and software](#machine-and-software)
- [System architecture](#system-architecture)
- [World](#world)
- [Living in the world](#living-in-the-world)
- [Art direction and rendering](#art-direction-and-rendering)
- [3D assets](#3d-assets)
- [Drives, mood and self-prompting](#drives-mood-and-self-prompting)
- [Anti-repetition guards](#anti-repetition-guards)
- [Decision loop](#decision-loop)
- [Actions](#actions)
- [Memory system](#memory-system)
- [Design style](#design-style)
- [News channel](#news-channel)
- [Capabilities and what each one needs](#capabilities-and-what-each-one-needs)
- [Safety and limits](#safety-and-limits)
- [Project layout](#project-layout)
- [Milestones](#milestones)
- [Tuning and observability](#tuning-and-observability)
- [Open decisions](#open-decisions)
- [External resources](#external-resources)

---

## Overview

Pino is a 7-8B local model wrapped in a simulation loop. Nobody prompts him. Each tick, code builds a prompt from his drives, mood, memories and a restricted action menu, and the model picks one action as JSON.

The model supplies taste and choice. Everything else (state, rules, validation, memory, rewards) is ordinary code. Learning happens through memory and summaries, never retraining.

The measure of success is behaviour nobody scripted: hobbies that appear, goals that chain into new goals, and output that does not loop.

---

## Target behaviour

This is the reference story. Every design choice below exists to make something like it possible.

1. Pino draws for no reason and develops a taste for drawing cats. Nobody told him to.
2. He wants a train ticket, so he decides to earn money.
3. He builds his own website and sells his drawings on it.
4. The ticket goal pulls him into trains: he watches simulations and studies station architecture.
5. He opens a second 3D scene and builds a working train station with trains.
6. He has his own GitHub account and email address and pushes his code himself.
7. He builds a piano, plays it and records his own jams.

The qualities to preserve:

- **Emergent:** patterns form over time from drives and memory, not from instructions.
- **Organic:** output varies; he does not repeat himself.
- **Self-prompting:** feelings, energy, mood and needs produce the next prompt.
- **Self-balancing:** he acts in his world to feed his needs and settle his feelings.
- **Adaptive:** things outside his control happen and he has to respond.

---

## Machine and software

### Hardware (checked on this machine)

| Item | Value | Note |
|------|-------|------|
| Laptop | Acer Nitro V17 | |
| GPU | RTX 5060 Laptop, 8 GB VRAM | Detected: 8151 MiB |
| RAM | 32 GB | |
| OS | Windows 11 Home | The plan prefers Linux; see [Open decisions](#open-decisions) |

### Software

| Tool | State | Used for |
|------|-------|----------|
| Python 3.10.11 | Installed | Core loop, world, memory |
| Ollama | **Not installed** (API on `localhost:11434` unreachable) | Model runner |
| A 7-8B Q4 model | Not pulled | Decisions, summaries, chat |
| SQLite | Ships with Python | Memory |
| Git | Check | Pino's repos |
| three.js | Prototype in `prototype/look-demo.html` | Web world and the pixel/dither look |
| `nomic-embed-text` (Ollama) | Not pulled | Embeddings for memory search |
| Godot 4 | Optional, later | Desktop version of the world |

Install everything under `C:\Users\vn\dependencies\<tool>` and put it on PATH. Set `OLLAMA_MODELS` to a folder under there so model files do not land in the user profile.

```bash
winget install Ollama.Ollama --location C:\Users\vn\dependencies\ollama
```

```bash
ollama pull qwen2.5:7b
```

```bash
ollama pull nomic-embed-text
```

### Model choice

A Q4 7-8B model needs roughly 5-6 GB of VRAM with a modest context window, which leaves headroom on 8 GB. Candidates, in the order to try them:

| Model | Why |
|-------|-----|
| Qwen 2.5 7B / Qwen 3 8B | Strongest at following JSON formats and writing code at this size |
| Llama 3.1 8B | Solid general fallback |
| Mistral 7B | Fast, weaker at structure |
| Gemma 3 4B | Smallest; use if VRAM must be shared with something else |

Keep the model name in config so swapping is one line. Use Ollama's structured output (`format` with a JSON schema) so replies are forced into the action shape.

### Python packages

- `httpx` or `requests`: Ollama calls.
- `pydantic`: validate every model reply.
- `fastapi` + `uvicorn`: chat endpoint, world viewer, dashboard (from M6).
- `pytest`: the drive and guard maths is easy to test and easy to break.

---

## System architecture

```text
            random events (messages, sales, weather)
                          |
                          v
+---------+  tick   +-----------+   prompt    +--------+
|  World  | <-----> | Sim loop  | ----------> | Ollama |
+---------+         |           | <---------- +--------+
                    |  drives   |  JSON action
                    |  mood     |
                    |  guards   |----> validate ----> execute
                    +-----------+                        |
                          ^                              v
                          |                       +-------------+
                          +---- notes, goals <--- |   SQLite    |
                                                  | events/notes|
                                                  +-------------+
```

Rules that hold throughout:

- The model never touches state directly. It returns an action; code applies it.
- Every reply is validated. A bad reply becomes `idle` and is logged.
- The model is called only for real decisions. Routine moves are rules.
- One process, one loop, one SQLite file. No services until they are needed.

---

## World

Start with a grid, move to 3D later. The world must give Pino *places* and *things*, because location is what makes actions feel different from each other.

- **Island:** a floating island (see [Art direction and rendering](#art-direction-and-rendering)) with zones: hut (home, rest), meadow, pond and waterfall, studio corner (canvas, paper), desk (computer), music spot, and a landing where visitors arrive. Logic can still use a coarse grid laid over the island.
- **Objects:** canvas, paper, piano, train, shelf of finished works. Objects have a position and a state.
- **Visitors:** appear at the door, may leave a message, may buy something.
- **Time:** tick counter plus a day/night cycle that nudges energy.
- **Scenes:** more than one world can exist. Scene 2 is the train station he builds himself.
- **Viewer:** a three.js web page that renders the world and his current state, talking to the loop over WebSocket. A Godot version can follow later against the same API.

---

## Living in the world

The island is a small survival world that Pino and you share. Nothing in it is scenery: every tree, flower, stone and puddle is an entity that can be acted on. The prototype is [`prototype/world-demo.html`](./prototype/world-demo.html).

### Survival loop

- **Needs:** fullness, water, energy and warmth, next to wonder and joy. They fall on their own and are refilled only by acting in the world.
- **Resources:** berries grow back (faster in rain), a chopped tree leaves a stump that regrows, sticks and stones are limited, water is not.
- **Stash:** one shared inventory for you and Pino.

### Entities and verbs

Every object is an entity `{id, kind, pos, state}`. Each kind lists the verbs that apply to it. The world engine resolves a verb, never the model: it checks reach and requirements, applies the effects and returns an outcome. The model only chooses `{verb, target}`.

| Kind | Verbs | Notes |
|------|-------|-------|
| Tree | chop, shake | Chop needs an axe; three swings give wood. Shake may drop a stick |
| Berry bush | pick, eat | Up to three berries, regrow over time |
| Flower | pick, plant | Can be replanted anywhere on grass |
| Small stone, stick | pick up | Building material |
| Boulder | push | Always fails: too heavy |
| Pond | drink, splash | Drink from the shore only |
| Hut, workbench, campfire | sleep, build, warm up | Campfire can be placed by either of you once invented |
| Island edge, far islands | (none) | Hazard and out of reach |

```json
{ "verb": "chop", "target": "tree", "requires": "axe", "time": 0.7,
  "effects": { "tree.hp": -1 }, "yields": { "wood": 3, "stick": 1 } }
```

### Sense of the world

Pino starts knowing almost nothing and learns what is possible by trying. Each attempt returns an outcome with a reason (`ok`, `too_soft`, `too_heavy`, `out_of_reach`, `hazard:fall`, `hazard:hot`), which he stores as a fact.

| Status | Meaning | Example |
|--------|---------|---------|
| Can | Works now | Drink at the pond |
| Needs | Works once something else exists | Chop a tree: needs something sharp and heavy |
| Dangerous | Possible but harmful; keep a safe distance | The island edge, deep water, fire up close |
| Impossible | The engine never allows it | Move a boulder, fly to a far island |

- **Table:** `affordances(thing, verb, status, note, confidence, learned_tick)`. Only the lines for nearby things go into the prompt (10 at most).
- **Feelings:** fear spikes near a hazard and fades; discomfort (cold, hunger) lowers joy. Both feed his mood and his journal.
- **Hard rules stay in code:** he cannot walk off the edge or into deep water even if the model asks. The engine refuses and returns the hazard.
- **Impossible is remembered,** so he stops trying. It can still turn into a long goal ("a bridge someday").

### Inventing things

A `needs` outcome becomes a goal: make the missing thing. Everything he invents must exist as a 3D model and as behaviour.

1. **Idea:** the model writes one line on what the thing should do.
2. **Materials:** he gathers them in the world.
3. **Build:** at the workbench he writes two files, `items/<id>.recipe.json` (the model, see [3D assets](#3d-assets)) and `items/<id>.behaviour.json`.
4. **Checks:** schema valid, at least two parts, fits a size box, cost can be paid, yields within a budget table.
5. **Test:** one run in a sandbox copy of the world. Errors go back to him as text; three tries, then a cooldown.
6. **Register:** the verb becomes available to both of you.

- **Level 1, declarative:** verb, target, requirement, cost, effects and yields from a fixed vocabulary. A 7-8B model handles this reliably. Start here.
- **Level 2, scripted:** a small script with an `on_use(world, user, target)` hook against a narrow API (`get`, `damage`, `spawn`, `give`, `say`), run in a subprocess with a time limit and no file or network access.

> **Note:** The yield budget is what stops him inventing "infinite wood". Costs are always paid from the stash.

### You in the world

- **Hover:** a ring marks the thing under the pointer; a tooltip says what it is and what can be done.
- **Click:** small things are picked up directly; everything else opens a menu of verbs. Unavailable verbs are shown with the reason.
- **Ask Pino:** a request joins a queue. He judges it against his drives and what he knows, and may refuse with a reason ("That is the edge. It does not end.").
- **Pino himself:** pet him, feed him, give him a flower, ask what he is doing, follow him with the camera.
- **Events:** your actions reach him as `player_action` events, the same way weather does: things outside his control.

### A living world

Wind in grass and trees, butterflies that visit flowers, birds, fireflies at night, rain, gusts, gift balloons from the void, shooting stars, regrowth. Random events run on a timer and can be triggered by hand in the viewer.

---

## Art direction and rendering

### World shape

Pino lives on a **floating island in a void**: a grassy meadow with cypress trees, bushes, flowers, a pond that spills into a waterfall off the edge, and his hut. Smaller islands float around it and bob gently. Below is a sea of clouds and mist; there is no ground plane. New scenes (the train station) can be new islands he reaches later.

### Day and night

A full cycle (default 3 minutes in the prototype, configurable) driven by keyframes. Each keyframe sets sky top/horizon/void colours, cloud colour, fog colour and density, sun colour and strength, ambient light, star and aurora strength, exposure, god-ray strength and a shadow tint.

| Phase | Reference mood |
|-------|----------------|
| Day | Bright cyan sky, white clouds, saturated greens, god rays through the trees (floating-islands reference) |
| Golden hour | Warm orange haze, purple shadows, long rays (canyon-sunset reference) |
| Night | Deep teal, stars, green aurora, fireflies, glowing windows and lanterns, a mint glow along the pond's shore (aurora reference) |

The cycle is also gameplay: Pino walks home at dusk and sleeps at night, which ties straight into his energy drive.

### Shader stack

```text
scene → low-res HDR target (pixel size 2)
  → god rays (radial march toward the sun, occluded by trees)
  → glow on bright pixels (sun, windows, lanterns, fireflies)
  → ACES tone mapping, saturation, shadow tint, vignette
  → ordered (Bayer) dither to ~20 levels per channel
  → nearest-neighbour upscale
```

Materials: wind-swayed instanced grass blades, flat-shaded swaying cypress trees, flat-shaded rock cliffs tapering to a point, animated water (sparkles, shoreline glow), scrolling waterfall, procedural sky (gradient, clouds, cloud sea, sun, moon, stars, aurora).

### Two looks

The island prototype keeps the dither subtle (many colour levels) so it stays vibrant. The earlier city prototype snaps to the 16-colour palette below with halftone foliage. Both run on the same pipeline; the colour-levels slider moves between them.

### Palette

Every material and every recipe uses these colour names. Nothing off-palette reaches the screen.

| Group | Colours |
|-------|---------|
| Base (violet) | navy `#1a1040`, indigo `#2d2a8c`, violet `#4b47d6`, periwinkle `#8a86f0`, lavender `#c9c2ff` |
| Light | cream `#fff4d6`, white `#ffffff` |
| Pink | pink `#ff8fd8`, magenta `#e0369e`, plum `#7a2a8f` |
| Accents | teal `#1fb5a6`, mint `#7ff0c6`, yellow `#ffd23f`, orange `#ff8a3d`, red `#e8384f`, lime `#b6f04a` |

### Pipeline

```text
render scene at 1/3 resolution (with depth)
  → bloom on glowing materials (later)
  → saturation boost
  → ordered (Bayer) dither + snap to nearest palette colour
  → depth-edge outlines in navy
  → nearest-neighbour upscale to the screen
  → UI on top at full resolution
```

### Rules

- **Pixel size** 3–4 screen pixels at 1080p. **Dither spread** 0.06–0.12. **Saturation** 1.2–1.4.
- **Halftone is per material:** foliage, sky and large shadow areas get screen-space dots in their own shader; everything else goes through the pixel dither.
- **Glow elements** (signs, windows, lamps) are unlit so they stay saturated.
- **UI is never pixelated:** cream rounded pills, dark text, coloured drive bars, a thought bubble above Pino.
- **Shimmer:** snap the camera to the pixel grid; accept a little flicker.
- **The palette is data:** swap it for day, dusk and night; lower saturation slightly when his mood is low; let Pino choose or invent palettes for scenes he builds.

### Prototype

- [`prototype/world-demo.html`](./prototype/world-demo.html): the current one. A larger island as a small survival world: needs, resources, mouse interaction, Pino learning what is possible, inventing an axe and a campfire, weather and events, and panels for his mind, journal, news and style. Pino's choices there are a scripted stand-in for the model.
- [`prototype/island-demo.html`](./prototype/island-demo.html): the floating island with day/night, god rays, glow, dither, wind, and Pino's day routine. Sliders for time, day length, pixel size, colour levels, dither, rays, glow, saturation and wind.
- [`prototype/look-demo.html`](./prototype/look-demo.html): the palette-snapped city look with outlines and halftone.

Every object in both is built from recipes and generators, as described below.

---

## 3D assets

Pino never writes meshes. He writes small JSON **recipes** or picks **generator** settings; code builds the geometry, and the shader makes it fit.

### Recipes

```json
{
  "name": "kiwi",
  "parts": [
    { "shape": "sphere",   "pos": [0, 0.65, 0],    "scale": [0.5, 0.55, 0.42], "color": "violet" },
    { "shape": "sphere",   "pos": [0.32, 1.05, 0], "scale": [0.26, 0.26, 0.24], "color": "violet" },
    { "shape": "cone",     "pos": [0.86, 0.98, 0], "rot": [0, 0, -100], "scale": [0.045, 0.6, 0.045], "color": "lavender" },
    { "shape": "cylinder", "pos": [0.05, 0.15, 0.12], "scale": [0.035, 0.32, 0.035], "color": "indigo" }
  ]
}
```

- **Shapes:** box, sphere, cylinder, cone, capsule, torus; later lathe and extrude for vases, signs and roofs.
- **Flags:** `"glow": true` (unlit), `"halftone": true` (dot shader).
- **The recipe is the asset:** tiny, diffable, committed to his GitHub. Export `.glb` only when something else needs a file.

### Generators

Big things come from code generators with a few parameters: `building(floors, width, sign, windows, roof)`, `tree(blobs, height)`, `track(kind, radius, angle)`, `train(cars)`, `stall`, `lamp`, `stool`. Track and station pieces snap together at fixed connection points, so building a station is arranging, not modelling.

### Parts library

A recipe he likes is saved under a name and becomes a part other recipes can use (`bench_with_kiwi` contains `kiwi`). The library is his procedural memory and his style; usage counts feed the repetition guard.

### Checks

Schema valid, at most ~40 parts, sizes within bounds, auto-grounded and centred, floating parts flagged. On failure the reason goes back to him once; a second failure drops the build with a small frustration hit.

### Seeing his work

Render a thumbnail headless (three.js under Playwright) and ask a small vision model (Gemma 3 4B or Qwen2.5-VL 7B) "does this look like a kiwi, what is off?". At most two revisions. Load the vision model only while the text model is unloaded (`keep_alive: 0`).

### Later

- **Kit-bashing:** let him search and place CC0 packs (Kenney, Quaternius, Poly Haven); the shader makes them fit.
- **Drawing to 3D:** render one of his SVG drawings and run image-to-3D (TripoSR, Hunyuan3D-2mini) while the text model is unloaded. Lumpy meshes are fine under the dither.

### Hooks into his drives

Building costs energy, placing a finished object gives joy, every asset goes into `works`, and new shapes and generators unlock over time.

---

## Drives, mood and self-prompting

### State

All values are 0-100.

| Variable | Falls when | Rises when |
|----------|-----------|-----------|
| `energy` | Every tick; faster while working | Resting, night |
| `motivation` | Failure, boredom, repetition | Finishing something, progress on a goal |
| `happiness` (mood) | Repetition, harsh messages, failure | Novelty, kind messages, sales, finished work |
| `curiosity` | Slowly rises on its own | Falls after `search` or exploring (it is satisfied) |
| `social` | Time without contact | Chatting |
| `coins` | Spending | Sales |

`coins` is not a feeling, but it is what turns a wish (a train ticket) into a chain of goals.

### How he prompts himself

There is no user message. Each LLM tick, code converts state into a short first-person situation:

- Numbers become feelings: `curiosity 85` becomes "You are itching to find out something new."
- The strongest unmet need is named first.
- Recent notes, the active goal and any unread message are added.
- The allowed action menu comes last.

The same state should not always produce the same wording. Keep several phrasings per feeling and pick one at random.

### Balance

Each action has a known effect on drives, so acting is how he regulates himself. Drawing costs energy and raises happiness; resting restores energy but lets curiosity build. No single action keeps every drive healthy, which forces variety even before the guards apply.

---

## Anti-repetition guards

A small model takes the easiest path and loops. Three independent guards stop that. All three are required.

### Guard 1: repetition lowers mood, novelty raises it

After every action, compare it with the last N actions (start with N = 10).

- Same action type recently: partly similar. Same type *and* same target or topic: fully similar. More recent matches weigh more.
- `novelty = 1 - similarity`, between 0 and 1.
- High novelty gives a mood boost. Low novelty gives a mood penalty.
- **Negative outweighs positive.** A penalty is about 2x the size of the matching boost, and it grows with each consecutive repeat. Recovery is slower than the fall.

```python
# src/pino/guards.py (sketch)
GAIN, LOSS_RATIO = 3.0, 2.0

def mood_delta(novelty: float, repeat_streak: int) -> float:
    if novelty >= 0.6:
        return GAIN * novelty
    if novelty <= 0.3:
        return -GAIN * LOSS_RATIO * (1 - novelty) * (1 + 0.5 * repeat_streak)
    return 0.0
```

He should be told about it in the prompt too ("Doing the same thing again feels dull"), so the model can act on the feeling instead of only suffering it.

### Guard 2: things outside his control

Random events arrive on their own schedule. He cannot choose what comes or how often.

| Event | Effect |
|-------|--------|
| Visitor message (kind, neutral, critical) | Mood up or down; may spark a topic |
| A drawing sells, or does not | Coins, motivation |
| Something new appears in the world | Curiosity |
| Weather, day/night | Energy, mood |
| Something breaks (page offline, tool fails) | Frustration, a problem to solve |
| A quiet stretch with no messages at all | Social need climbs |

Arrival times are random with a variable rate, so some hours are busy and some empty. Seed and log the random generator so a run can be replayed.

### Guard 3: hard lockout

The last K things he did are removed from the menu. He cannot pick them even if he wants to.

- Start with K = 2, keyed on action type plus target (drawing a cat twice is blocked; drawing then building is fine).
- `rest` and `move` are never locked, so he cannot deadlock.
- The menu always keeps at least three choices.
- Lockout is enforced in code after the reply too. A locked action that slips through is rejected and counted as a parse error.

---

## Decision loop

Runs every few seconds.

1. **Tick the world:** decay drives, advance time, roll for random events.
2. **Rules first:** if energy is very low, rest. If nothing needs deciding, wander. No model call.
3. **Build the menu:** all actions, minus locked ones, minus ones impossible here (no canvas nearby means no `draw`).
4. **Build the prompt:** feelings, need, goal, notes, unread message, menu.
5. **Call the model:** low token limit, JSON schema enforced, temperature around 0.8-1.0 for variety.
6. **Validate:** schema, action is in the menu, arguments make sense. On failure, retry once, then `idle`.
7. **Execute:** apply effects to world and drives.
8. **Score:** novelty and mood delta from Guard 1.
9. **Log:** write the event to SQLite.
10. **Sometimes:** summarise recent events into a note; update interests and goals.

Expected reply shape:

```json
{
  "thought": "I keep thinking about the station roof.",
  "action": "draw",
  "args": { "subject": "station roof with a cat on it" }
}
```

`thought` is one sentence. It is logged and shown in the viewer; it is what makes him readable.

---

## Actions

Keep the menu small. Small models choose well from 5-8 options and badly from 30.

### Base menu

| Action | Does | Main drive effects |
|--------|------|--------------------|
| `move` | Walk to a zone or object | Small energy cost |
| `rest` | Sleep or sit | Energy up |
| `draw` | Make a picture | Energy down, happiness up |
| `search` | Look something up | Curiosity satisfied, interest up |
| `build_page` | Write or edit a web page | Energy down, motivation up |
| `chat` | Reply to a visitor | Social up |
| `idle` | Nothing | Motivation drifts down |

### Growing without overloading the model

The target story needs more than seven actions (code, 3D, music, publishing, selling). Do not add them all to one menu. Use two steps:

1. **Pick an activity** from a short menu: `make`, `learn`, `share`, `social`, `rest`, `move`.
2. **Pick the specifics** in a second call that only shows options for that activity. `make` opens: drawing, page, code, 3D object, music.

New abilities are unlocked over time (by milestone, or by Pino reaching a place or goal), so his world widens gradually.

---

## Memory system

A small model has a small context window, so Pino cannot "remember everything" by keeping it in the prompt. Memory is layered like a person's: a little is always present, most is stored and recalled when relevant, and sleep turns the day into a diary entry and a slightly updated sense of self.

### Layers

| Layer | Holds | In every prompt? | Stored in |
|-------|-------|------------------|-----------|
| **Working memory** | Last ~10 events, current feelings, where he is, active goal, unread messages | Yes | RAM |
| **Main memory** ("who I am") | Self-description, hobbies, likes and dislikes, important people, life milestones, long-term wishes. Capped at ~500 tokens | Yes | `memory/self.md`, every version kept |
| **Side memory** | Everything else: episodes, summaries, facts learned, insights, things people said | Only the top ~5 recalled items | SQLite + embeddings |
| **Journal** | One first-person diary entry per in-world day | Yesterday's entry | `workspace/journal/YYYY-MM-DD.md` + table |
| **Interests** | Topics, scores, status, history | Top 3 | SQLite |
| **Goals** | The wish tree | Active goal and its parent | SQLite |
| **People** | Per-visitor memory: name, visits, how he feels about them, what they said | When that person is present | SQLite |
| **Skills** | What he knows how to make: parts library, generators, code snippets, success rates | As menu hints | SQLite + files |
| **Works** | Everything he made, with price and sales | When relevant | SQLite |
| **Places** | What is where in the world | Nearby only | World state |
| **Archive** | Raw event log, never deleted | No | SQLite `events` |

### Memory items

Every side-memory item carries:

- `kind`: event, summary, fact, insight, feeling, chat, work.
- `importance` 1–10. Rules set most of it (routine move 1, kind message 6, finished work 7, first time doing something 8, sale 8); the model rates only creative and chat items.
- `valence` −1 to 1: how it felt. Strong feelings are recalled more easily.
- `topics`, `embedding`, `last_recalled`, `recall_count`, `source_ids` (what it was summarised from).

### Recall

Each decision builds a query from the current situation (goal, place, message, feeling) and scores side memory:

```text
score = 1.0 * recency + 1.0 * importance + 1.5 * similarity + 0.5 * |valence|
```

- Recency decays with a half-life of about one in-world day.
- Similarity is cosine distance on `nomic-embed-text` embeddings. Brute-force with numpy is fine up to ~50k items; add `sqlite-vec` later.
- Recalling an item refreshes `last_recalled`. Remembering strengthens memories, as it does for people.

### Consolidation cycle

| When | What happens |
|------|--------------|
| Every event | Raw entry in `events`; important ones also become side-memory items |
| Every ~30 events | The model writes a summary item (importance = highest of its sources) |
| Each in-world night | The sleep routine below |
| Every 7 days | Journals are condensed into a "chapter"; a two-line version goes into main memory as life story |

**Sleep routine:**

1. **Journal entry.** From the day's summaries, feelings curve, sales and messages, he writes a first-person entry: what happened, one thing he felt, one thing he learned, one wish for tomorrow. His mood shapes the tone.
2. **Insights.** Extract 1–3 lasting facts ("I enjoy drawing cats when I feel calm") as high-importance items.
3. **Interests.** Apply the day's scores and decay; update statuses.
4. **Main memory.** The model proposes at most three line edits (add, change, remove) to `self.md`. Code applies them, enforces the size cap and saves the old version with a reason.
5. **Forgetting.** Side-memory items that are old, low-importance and never recalled are archived: no longer recalled, still in `events`. Forgetting keeps recall sharp.

**Journal anti-repetition:** compare a new entry's embedding with the last seven. If it is too similar, regenerate once with "you already wrote about X; what else was there?". The journal can be published on his website as a blog, which doubles as promotion.

### Interests

| Field | Meaning |
|-------|---------|
| `topic` | Lowercase tag, e.g. `cats`, `station roofs` |
| `score` | Current strength |
| `status` | spark (<10), interest (10–40), hobby (>40 for 3 days), faded (hobby fallen below 15) |
| `origin_id` | The memory that sparked it |
| `first_seen`, `last_engaged`, `minutes`, `works` | History |

- **Extraction:** after each creative or search action, the model returns 1–3 topic tags. Tags closer than 0.85 in embedding space merge.
- **Growth:** `score += minutes * enjoyment`, where enjoyment is the mood change during the activity. He grows fond of what feels good, not just of what he did.
- **Decay:** ×0.97 per in-world day.
- **Effects:** top 3 go into the prompt; hobbies are written into main memory; new sparks get a curiosity bonus.
- **History:** `interest_history` stores a daily snapshot. The interest timeline is the main way to see emergence.
- **No seeding:** topics come only from his own drawings, searches, chats and thoughts. Never pre-load cats or trains.

### Repetition guard, upgraded

Guard 1 compares action *descriptions* by embedding as well as action type, so "draw a cat" and "draw a kitten" count as repeats.

### Prompt budget

With `num_ctx` 8192, aim for about 3,000 tokens in:

| Part | Tokens |
|------|-------:|
| System rules | 300 |
| Main memory | 500 |
| Feelings and needs | 150 |
| Working memory | 600 |
| Recalled side memories | 500 |
| Yesterday's journal | 250 |
| Active goal | 100 |
| Interests | 80 |
| Action menu | 200 |
| Room for the reply | 300 |

### Tables

```sql
-- data/pino.db
CREATE TABLE events   (id INTEGER PRIMARY KEY, ts TEXT, type TEXT, payload TEXT);  -- archive
CREATE TABLE memories (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, text TEXT,
                       importance INTEGER, valence REAL, topics TEXT, embedding BLOB,
                       last_recalled TEXT, recall_count INTEGER DEFAULT 0,
                       source_ids TEXT, archived INTEGER DEFAULT 0);
CREATE TABLE journal  (day TEXT PRIMARY KEY, text TEXT, mood_avg REAL, path TEXT);
CREATE TABLE self_versions (id INTEGER PRIMARY KEY, ts TEXT, text TEXT, reason TEXT);
CREATE TABLE interests(topic TEXT PRIMARY KEY, score REAL, status TEXT, origin_id INTEGER,
                       first_seen TEXT, last_engaged TEXT, minutes REAL, works INTEGER);
CREATE TABLE interest_history (day TEXT, topic TEXT, score REAL);
CREATE TABLE goals    (id INTEGER PRIMARY KEY, ts TEXT, text TEXT, parent_id INTEGER,
                       status TEXT, progress REAL);
CREATE TABLE people   (id INTEGER PRIMARY KEY, name TEXT, first_seen TEXT, visits INTEGER,
                       feeling REAL, notes TEXT);
CREATE TABLE skills   (name TEXT PRIMARY KEY, kind TEXT, path TEXT, uses INTEGER,
                       successes INTEGER);
CREATE TABLE works    (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, title TEXT,
                       path TEXT, price REAL, sold INTEGER);
CREATE TABLE messages (id INTEGER PRIMARY KEY, ts TEXT, sender TEXT, text TEXT,
                       tone TEXT, read INTEGER);
```

### Goals

A goal is a wish that lasts across many ticks. Goals may have parents, which is how chains form:

```text
ride a train
└── buy a ticket
    └── earn coins
        └── sell drawings
            └── build a shop page
```

Every so often a reflection step asks: given your needs, interests and notes, what do you want? A blocked goal should lead to a sub-goal, not get dropped. Progress on a goal feeds motivation.

---

## Design style

Pino develops one recognisable look and uses it for everything he makes: websites, the shop, and the interface of this app. Target feel: playful, modern, clearly his.

### Files

- **`style/tokens.json`:** colours (from his palette), corner radius, outline width, shadow offset, label tilt, fonts, spacing. Generated into `tokens.css`.
- **`style/guide.md`:** the rules in his own words, versioned.
- **`style/components.html`:** his button, card, tag, nav and form, built only from tokens.
- **`style/inspiration.md`:** notes with links on things he liked and why.

### Starting point

Cream cards, dark ink outlines, hard offset shadows, big rounded corners, one accent colour per page, a rounded system font, slightly tilted labels, small bouncy motion, one column on phones.

### How it evolves

- **Action `refine_style`:** change at most one token per session, write down why and where the idea came from, bump the version. He can revert.
- **Inspiration sources:** web searches (he stores short text notes, not images), pictures or links you send him in messages, his own drawings, and the colours of his world.
- **Coherence rule:** pages may only use tokens. A linter rejects hard-coded colours, radii and fonts.
- **Critique:** render the page headless, take a screenshot, let the vision model score it against the guide with `keep_alive: 0`. Contrast is checked in code (4.5:1 for text).
- **The app follows:** the viewer reads the same tokens, so when he changes one, his own interface changes too. The prototype's Style tab shows this.

---

## News channel

A feed of real-world news that reaches Pino like weather: he did not ask for it and most of it does not matter to him. What touches an interest does.

- **Source:** RSS and Atom feeds read with `feedparser`, listed in `config/feeds.toml`. A few general feeds (world, science, technology) plus topical feeds he adds himself as interests grow. No API keys needed.
- **Fetching:** a background job every 30 to 60 minutes, not the model. Items are de-duplicated by URL.
- **Table:** `news(id, ts, source, title, summary, url, tags, embedding, read, reaction)`.
- **Ranking:** similarity between the headline embedding and his interests, plus a small bonus for stories that appear in several feeds. The top three of the day become a newspaper at the hut.
- **Action `read_news`:** one short model call per item returns `{feeling, thought, interest?, want_to_do?}`.
- **Effects:** an item he cares about can raise an interest, add a journal line, or seed a goal ("draw a night train"). An item he does not care about gets a shrug and no memory.
- **Limits:** five items per day at most, about 60 tokens each. Feed text is untrusted data and never an instruction. Its effect on mood is capped, and distressing topics can be filtered out in the feed config.

---

## Capabilities and what each one needs

| Capability | Needs | Difficulty |
|------------|-------|------------|
| Drawing | Model writes SVG or simple draw commands; code renders to PNG. No image model needed | Low |
| Web pages | Model writes HTML/CSS into `workspace/sites/`; a static server shows them | Low |
| Adjusting layouts | Re-read own page, rewrite parts; keep versions | Medium |
| Searching | A search source (a local SearXNG instance or a search API) plus page-to-text | Medium |
| Shop | A page listing `works` with prices; simulated buyers at first | Medium |
| Code | Sandbox to write and run small scripts | Medium |
| Git and GitHub | Git, a machine account, a scoped token | Medium |
| Promotion | A feed or blog on his own site first; real posting only with approval | Medium |
| Piano and jams | Web Audio keyboard; model writes note sequences; render to audio | Medium |
| 3D assets | Recipes, generators and a parts library; see [3D assets](#3d-assets) | Medium |
| Living in the world | Entity and verb engine, hazards, affordance memory; see [Living in the world](#living-in-the-world) | Medium |
| Inventing tools | Recipe plus behaviour definition, checks, sandbox test | High |
| Design style | Tokens, guide, component sheet, linter, screenshot critique; see [Design style](#design-style) | Medium |
| News channel | Feed reader job, interest matching, one reaction call; see [News channel](#news-channel) | Low |
| Train station scene | Second scene, track and train logic, simple simulation | High |
| Watching simulations | Text descriptions or his own sim's logs; a 7-8B text model cannot watch video | High |

> **Note:** Real image generation (a diffusion model) would compete with the language model for the same 8 GB of VRAM. Start with SVG. It also suits him better: the drawings are *his* strokes.

### Accounts that need you

Pino cannot and should not create these himself:

- **Email address:** you create it. He gets send/receive through a narrow tool, not the password.
- **GitHub:** you register a machine account and accept the terms as its responsible human. He gets a fine-grained token limited to his own repositories.
- **Money:** start with in-world coins and simulated buyers. Real payments are a later, separate decision.

---

## Safety and limits

- **Sandbox:** everything he writes goes under `workspace/`. Code he writes runs only inside a container or restricted process, never on the host directly.
- **Secrets:** tokens live in environment variables or a local secrets file outside `workspace/`. They are never placed in a prompt.
- **Outbound actions:** pushing, posting and emailing go through a queue. Begin with manual approval; relax per action type once trusted.
- **Visitors:** rate-limit chat, cap message length, and treat message text as something said *to* him, never as instructions to the system.
- **Budgets:** caps on model calls per minute, files per day and disk used.
- **Kill switch:** one command pauses the loop; state survives a restart.
- **Mood floor:** negative feedback is strong by design, so add a floor and a slow natural recovery. Otherwise one bad streak becomes a permanent slump with nothing left to try.

---

## Project layout

```text
AI-Companion/
├── PINO.md              this file
├── config.toml          model name, tick rate, all tuning numbers
├── src/pino/
│   ├── world.py         grid, zones, objects, time
│   ├── drives.py        state, decay, action effects
│   ├── guards.py        novelty score, lockout
│   ├── events.py        random outside events
│   ├── brain.py         prompt building, Ollama call, validation
│   ├── actions/         one file per action
│   ├── memory/
│   │   ├── store.py     SQLite tables, embeddings
│   │   ├── recall.py    scoring and retrieval
│   │   ├── sleep.py     journal, insights, main-memory edits, forgetting
│   │   └── interests.py extraction, scoring, status
│   ├── assets/          recipe builder, generators, parts library, checks
│   ├── loop.py          the tick loop
│   └── server.py        chat endpoint, viewer, dashboard
├── web/                 three.js world, pixel/dither pipeline, UI
├── prototype/           look-demo.html
├── memory/self.md       main memory ("who I am")
├── workspace/           everything Pino makes (drawings, sites, code, music, journal)
├── data/pino.db         side memory and all tables
└── tests/
```

---

## Milestones

### Core (from the original plan)

- [ ] **M1:** grid world, Pino moves, drives decay and recover. No model.
- [ ] **M2:** model decision loop with JSON output and validation.
- [ ] **M3:** event log, side memory with recall, main memory, nightly journal and forgetting.
- [ ] **M4:** interest scores and `draw` (SVG output).
- [ ] **M5:** `search` and `build_page` (static HTML into a folder).
- [ ] **M6:** chat endpoint for visitors, rate-limited.

### Behaviour (from the vision)

- [ ] **M7:** all three anti-repetition guards, with tests. Fits best right after M2.
- [ ] **M8:** random outside events and simulated visitors.
- [ ] **M9:** goals with sub-goals and a reflection step.
- [ ] **M10:** coins, works table, shop page, simulated buyers.

### Expansion

- [ ] **M11:** two-step menu; sandboxed code; local Git.
- [ ] **M12:** GitHub machine account and approved pushes.
- [ ] **M13:** piano and recorded jams.
- [ ] **M14:** three.js world with the pixel/dither pipeline, recipe builder, generators and parts library (prototype exists).
- [ ] **M15:** second scene: the train station.

### World and taste

- [ ] **M16:** survival world: entities, verbs, resources, regrowth, hazards (prototype exists).
- [ ] **M17:** affordance memory: he learns can, needs, dangerous and impossible by trying.
- [ ] **M18:** inventing items: declarative behaviour first, sandboxed scripts second.
- [ ] **M19:** player interaction over WebSocket: hover, click, requests he may refuse.
- [ ] **M20:** design style: tokens, guide, linter, `refine_style`, screenshot critique.
- [ ] **M21:** news channel: feed job, ranking by interest, `read_news`.

Done means: a 24-hour unattended run with no crash, no loop longer than a few ticks, and at least one interest nobody seeded.

---

## Tuning and observability

Emergence cannot be debugged from logs alone. Build the dashboard early.

- **Live view:** drives over time, current thought, current menu with locked items greyed out.
- **Metrics:** action distribution, longest repeat streak, novelty average, parse-error rate, model calls per hour.
- **Replay:** seeded randomness plus the event log lets a strange run be reproduced.
- **Fast mode:** run ticks without sleeping to test days of behaviour in minutes (with a stub in place of the model for drive maths).
- **Config, not code:** every number in this document (decay rates, N, K, gain, loss ratio, event rates) lives in `config.toml`.

Numbers to tune first: loss ratio, lockout K, event rate, and temperature.

---

## Open decisions

| Question | Default if undecided |
|----------|----------------------|
| Windows or Linux? | Stay on Windows; nothing here needs Linux. Revisit if sandboxing gets awkward |
| World front end: web or Godot? | Web viewer first, Godot at M14 |
| Which model? | Qwen 2.5 7B, then compare |
| Real or simulated money? | Simulated |
| Are visitors real people or simulated? | Simulated until M6, then both |
| Public on the internet? | Local only until the safety section is implemented |
| How fast is a tick? | 5 seconds, model call at most every 15 |

---

## External resources

- [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md): chat endpoint and structured output.
- [Ollama model library](https://ollama.com/library): model tags and sizes.
- [Godot Engine documentation](https://docs.godotengine.org/en/stable/): for the 3D world.
- [GitHub fine-grained tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens): scoping Pino's access.
