# Honk: what is needed

**Purpose:** One document listing everything required to build Honk, a small local AI companion that lives in his own world and prompts himself through needs and feelings.

**Audience:** The builder (you) and any coding agent working in this folder.

**Last Updated:** 2026-11-12

**Status:** Draft. The newest prototype, `World/main-hub.html`, runs Honk on a local model through `src/honk/server.py`: he explores the island, searches and reads the web, writes programs and builds objects. The Python sim loop, embeddings and the rest of the plan are not built yet.

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

Honk is a 7-8B local model wrapped in a simulation loop. Nobody prompts him. Each tick, code builds a prompt from his drives, mood, memories and a restricted action menu, and the model picks one action as JSON.

The model supplies taste and choice. Everything else (state, rules, validation, memory, rewards) is ordinary code. Learning happens through memory and summaries, never retraining.

The measure of success is behaviour nobody scripted: hobbies that appear, goals that chain into new goals, and output that does not loop.

---

## Target behaviour

This is the reference story. Every design choice below exists to make something like it possible.

1. Honk draws for no reason and develops a taste for drawing cats. Nobody told him to.
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
- **Self-balancing:** he acts in his world to settle his feelings: curiosity, energy, joy, comfort and calm. Everything in the world pushes on them (see [How things make him feel](#how-things-make-him-feel)).

> **Note:** The story above is an example of the kind of chain that should emerge, not a script. Nothing in it (cats, trains, shops) is ever put into his prompt. He is told only that he is curious, knows almost nothing and can look, think, research, make and build; what he does with that is his.
- **Adaptive:** things outside his control happen and he has to respond.

---

## Machine and software

### Hardware (checked on this machine)

| Item | Value | Note |
|------|-------|------|
| Laptop | Acer Nitro V17 | |
| GPU | RTX 5060 Laptop, 8 GB VRAM | Detected: 8151 MiB |
| RAM | 32 GB | |
| OS | Arch Linux | Was Windows 11 Home when this was first checked |

### Software

| Tool | State | Used for |
|------|-------|----------|
| Python 3.14 | Installed | Server (`src/honk/server.py`), later the core loop |
| Ollama | **Not installed** (API on `localhost:11434` unreachable) | Model runner |
| A 7-8B Q4 model | Not pulled | Decisions, summaries, code |
| SQLite | Ships with Python | Memory |
| Git | Check | Honk's repos |
| three.js | Prototype in `World/look-demo.html` | Web world and the pixel/dither look |
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
- `fastapi` + `uvicorn`: world viewer and dashboard, if the stdlib server outgrows itself.
- `pytest`: the drive and guard maths is easy to test and easy to break.

---

## System architecture

```text
            random events (weather, sales, news)
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

Start with a grid, move to 3D later. The world must give Honk *places* and *things*, because location is what makes actions feel different from each other.

- **Island:** a floating island (see [Art direction and rendering](#art-direction-and-rendering)) with places he discovers: the desk with his computer, the pond, the waterfall, the woods, the rocky hill, the meadow, the edge and the far side. Logic uses a coarse grid laid over the island.
- **Objects:** canvas, paper, piano, train, shelf of finished works. Objects have a position and a state.
- **Time:** tick counter plus a day/night cycle. Night makes him tire faster; it does not send him to bed.
- **Scenes:** more than one world can exist. Scene 2 is the train station he builds himself.
- **Viewer:** a three.js web page that renders the world and his current state. The watcher does not act in it: the builder changes the world in code, never by interacting. The watcher is present in it, though, as a human Honk can see. A Godot version can follow later against the same API.

---

## Living in the world

The island is a place to live, not a survival game. Honk does not eat, drink, gather, chop or craft. He walks around, notices things, thinks about them, researches them on his computer and comes up with something to do, the way a person with free time does. The prototype is [`World/main-hub.html`](./World/main-hub.html), run through the local server (see [Running the prototype](#running-the-prototype)).

### What he starts with

- **Knows:** his name is Honk, he lives on a floating island, where his desk is, and that the desk has a computer connected to the internet.
- **Does not know what he is.** He is a chubby, long-necked cartoon goose, but nothing tells him so. Looking at himself or at his reflection in the pond gives plain impressions (white feathers, a long bendy neck, a flat orange mouth, webbed orange feet, a loud HONK); working out what kind of creature that is, is his to do.
- **Does not know:** what things are called, how they work, or anything about the world beyond the island. He finds that out himself.
- **Senses, not facts:** looking at something returns a plain impression ("a small tree with a round, puffy crown", "waves of green and violet light ripple across the sky"), never a name or an explanation. The questions that raises are his to research.
- **Nothing is seeded:** no interests, facts, goals or project ideas. The trains and the shop in [Target behaviour](#target-behaviour) are examples of the kind of chain that should emerge, never content for the prompt.

### Actions

The model chooses one of these each step. Code carries it out and writes the result back as a first-person line in his recent events.

| Action | Target | Where | What code does |
|--------|--------|-------|----------------|
| `wander` | a known place, or "somewhere new" | anywhere | Walks there; "somewhere new" heads for parts of the island he has not seen |
| `look` | something nearby, the sky, the clouds, himself | anywhere | Walks up to it and returns what he perceives; some sights move him a little (flowers, the night sky, his own builds) |
| `use` | a thing nearby, "grass" or "myself", plus what he does ("sit on it", "smell it", "splash", "clean my feathers") | at the thing | Walks there, does it with his body and feels it: each kind of thing has weights per verb (see [How things make him feel](#how-things-make-him-feel)) |
| `think` | a topic | anywhere | Second model call: a reflection, and optionally an insight (stored as learned), an idea or a new goal |
| `search` | a query | desk | Real web search; the top five results go into his next prompt |
| `read` | a URL (from search results or the last page's links), or `random` | desk | Fetches the page as text; a second call returns a summary, 1–3 learned facts, a feeling and a new question. The page's links (up to 8) go into his next prompt so he can follow them; `random` opens a random encyclopedia page |
| `code` | a project name, plus what to make or change | desk | Second call writes a complete `index.html`; saved under `workspace/projects/<name>/`, run for five seconds in a hidden sandbox. Errors and whatever it prints with `console.log` are fed back, so a program can be an experiment. It may fetch free public data that needs no key or login |
| `share` | a project name | desk | Only on the menu once he has an account. Puts the program in a repository on his GitHub account, after your OK in the Works panel unless sharing is set to `auto` (see [Accounts that need you](#accounts-that-need-you)) |
| `build` | an object name, plus what it looks like and why | where he stands | Second call writes a recipe of simple shapes; checked and placed next to him (see [3D assets](#3d-assets)) |
| `rest` | (none) | the best seat within reach, or the grass | A little energy back; sitting on a good seat feels good, a hard one does not |
| `sleep` | where: "right here", "under a tree", "among the flowers", a known place | anywhere | Picks a comfortable spot, walks there and sleeps until rested (see [Sleeping](#sleeping)) |

Every decision also carries a `thought` (his inner voice, shown above his head), optional `goal` and up to three `topics`, which become his interests. A thought that says nearly the same as one he had in the last two in-world hours is dropped: it is not shown, not stored and not fed back into his next prompt.

### How a step works

0. **Does this need thought?** Most of living does not. Unless his goal, some news (a new place, rain, a shooting star) or five everyday choices in a row with nothing to aim at call for it, code picks the next thing from his feelings and the model is not asked: look at something he has not looked at, try something he has not tried, go back to what felt good, walk somewhere new, rest when worn out, sleep when tired. He stays with the thing he is finding out about, and these steps have no inner voice. With a goal the model decides every step, except that a worn-out body gets up to two everyday choices first. With no model connected he lives this way all the time. The logic is `attention`, `routine` and `pickRoutine` in `honk-mind.js`.
1. **Situation:** code writes his situation in the second person: time, place, feelings in words, his self-description, goal, top interests, learned facts (the newest plus older ones that share words with what is on his mind), his programs and their last test, things he built, what he feels around him right now ("the sun warms your back", "the wooden stool is hard under you"), how things have made him feel so far (his likes and dislikes, with a few words each), last night's journal entry, the last ten events, his last thoughts, what is nearby, the places he knows, how much he has explored, his last search results and the action menu minus locked actions.
2. **Choice:** the model answers under a JSON schema. A bad or locked answer gets one retry with the reason; after that he wanders.
3. **Doing:** he walks where the action happens (computer actions at the desk), then the action runs. While the model works, he shows it (typing at the screen, thinking).
4. **Remembering:** results go into recent events, facts into what he has learned, everything into `data/events.jsonl`.
5. **Journal:** he scribbles a short note (2-3 sentences) every three in-world hours when enough has happened, and sooner (after at least an hour) when something big happened: a goal taken on, reached or let go, a new place, a finished build. When he lies down in the evening or at night he writes the longer entry for the day, which also rewrites his self-description. If a day ends at dawn without one, he writes it the next time he is free.

The guards from [Anti-repetition guards](#anti-repetition-guards) apply: the last two action+target pairs are off the menu, and repeats cost joy at about twice what novelty gives. Steady work on his goal is the exception: he may code, build or think about the same thing up to three times running, and repeating goal work costs only a third of the usual joy.

### His mind

Who he is and how he keeps his focus live in [`World/honk-mind.js`](./World/honk-mind.js): pure logic with no rendering, tested by `node --test tests/`.

- **Personality** (in the system prompt): curious, clever, clumsy, soft-hearted and persistent. Clumsy is also physical: walking, he sometimes trips over his own feet (more often when tired, in the rain or turning sharply), flops forward with his wings out, says "oops!" and laughs it off.
- **One goal at a time, with steps.** When he takes a goal on, he plans 2 to 5 small concrete steps. Each decision says whether the action is `for_goal` and how the last one went (`step done`, `goal done`, `stuck`, `none`). A step only counts if the previous action was for the goal. When the steps run out he plans the next ones or declares the goal reached (a happy HONK). A step that fails twice gets rethought.
- **Commitment versus feelings.** A new goal the model proposes is never simply taken. If it is the current goal or one of its steps in other words, nothing changes. Otherwise his commitment (persistence trait, work and steps already done, recent progress; lowered by setbacks, hours without progress and getting distracted) is weighed against his feelings' pull (boredom, being stuck, restless curiosity about something new, unease). The idea wins only if the pull beats commitment by a margin; otherwise it goes on his list of ideas for later, and his next prompt tells him he chose to stick with his goal.
- **Breaks are not switches.** Rest, sleep, journalling and planning count neither for nor against the goal. A run of six unrelated choices, or commitment falling very low, makes the goal slip: he lets it go, and if he had worked on it, it waits on his list as unfinished. Picking it up again later brings back the steps he already did.
- **Hobbies.** An interest he keeps feeding for two days becomes a hobby. Hobbies fade far more slowly than ordinary interests, add to his commitment to goals about them, and are where he looks when he has no goal.
- **Wishes.** Things he cannot get or make himself, such as an account somewhere, go on a wish list in the Mind panel.
- **Getting used to things.** Every thing he pays attention to builds familiarity, which halves each in-world day. Familiar things lose their pull: looking at them again does less, and the human drops out of his thoughts (see [The viewer](#the-viewer)).

### Exploring

Named places are found by walking near them: the pond, the waterfall, the woods, the rocky hill, the meadow, the edge and the far side. Each discovery is an event with a first impression. A coarse grid records what he has seen, which drives "somewhere new" and the explored percentage. Hard rules stay in code: he cannot walk into the pond or off the edge.

### Getting around

Walking uses a grid of half-unit cells over the island. Water, the edge and everything solid (trunks, boulders, bushes, lanterns, the desk, things he built) block cells; flowers, pebbles and grass do not. A path is planned with A*, kept a little away from obstacles, and smoothed into straight runs. If the target is inside something (a tree, the pond), he goes as close as he can. If he barely moves for a few seconds he plans again from where he stands, and after a few failed tries he gives up and remembers that he could not get there. Building something rebuilds the grid. Flat stepping stones cross the stream between the pond and the waterfall, so the island is not cut in two; he hops across them.

### Sleeping

He has no house, no bed and no bedtime, and he is always visible. Energy drains while he is awake (faster when working and at night) and comes back while he sleeps (faster on a daytime nap).

- **Falling asleep:** he can choose `sleep` at any time. If he is not actually sleepy (energy above 0.6, or 0.85 in the evening), he lies down, cannot sleep and gets up again. Below 0.06 energy he nods off within a few steps of where he is. With no model connected, he sleeps when energy is low, or at night when he is tired.
- **Where:** he scores spots around him (or around a place he names): shelter under a tree (worth more when it rains), next to a bush, among flowers, a lantern at night, flat ground, away from the edge and the water, and spots he slept well in before. Beds he built (and soft seats, for a nap) compete with these by how soft and warm they are; he lies on top of them.
- **How well he slept:** every spot has a quality (grass about 0.4; a built bed from its materials: a cushion bed is near 1, a stone slab near 0.1). Better beds give energy back faster and he wakes up cosy; a bad one leaves him stiff and sore. That goes into his likes and into the spot's memory.
- **Waking:** he wakes when he is rested; at night he stays down a while longer. Rain wakes him if he is not under a tree, and he remembers that spot as a bad one.
- **Memory:** `M.beds` keeps up to ten spots with how often he slept there and whether he liked it. His prompt says where he slept last, and the Mind panel lists his spots.
- **Days** start at dawn whether he is asleep or awake.

### How things make him feel

Every object and creature in his world pushes on how he feels, and every push is weighted. That is the reward and the punishment his mind learns from.

- **Five feelings:** curiosity, energy, joy, **comfort** (sore to cosy) and **calm** (scared to at peace). Comfort and calm settle back slowly on their own, and both pull his joy along.
- **Nearby (`ambient()`, every half second):**
  - **Good:** sunshine (comfort), tree shade (calm), staying dry under a tree or a roof in the rain, a lantern or something glowing he built at night (calm, warmth), flowers (joy), butterflies, the pond and the waterfall (calm), his own builds (joy).
  - **Bad:** rain on him (comfort), the dark far from any light (calm), cold night air (comfort), the edge of the island (calm, strongly).
  - **The human (you):** unsettling at first (curiosity up, calm down), and company once he has seen it a few times (joy, calm).
- **Doing things (`TOUCH`, the `use` action):** each kind of thing has weights per verb:
  - **Good:** smelling a flower, pecking grass, splashing in the pond, cleaning his feathers, leaning on a tree, sitting on a sun-warmed rock.
  - **Bad:** sitting in a bush, touching a lantern at night (hot), climbing a tree, biting a stone, sitting on a cold rock.
  - Some depend on time and weather.
- **Things he builds:** every part has a material (wood, stone, metal, glass, plastic, leather, fabric, cushion, wool, moss, straw, paper), and every build has a use (seat, bed, lamp, shelter, table, toy, art, other). `thingProps` works out from the parts:
  - how soft and warm it is where he touches it (the part he sits or lies on counts most)
  - the seat height, whether there is a backrest, a roof (rain shelter) or lights
  - **Seat quality:** wooden stool 0.27, wooden chair about 0.4, leather chair with a back about 0.7, cushioned gaming chair with a high back about 0.9.
- **His desk chair:**
  - **The stool:** he starts with a hard wooden stool at the desk. Working on it slowly costs comfort ("your back is starting to ache") and tires him faster; a good chair does the opposite.
  - **Building a better one:** a seat he builds near the desk goes to the desk, and the old one is moved aside.
  - **Balance:** a bad seat hurts about twice as much as a good one helps.
- **Reward:** every change is scored (joy 1, comfort 0.8, calm 0.8, energy 0.4, curiosity 0.3) and added to `M.likes` under what caused it ("sitting on the wooden stool", "splashing in the pond", "the edge"). His prompt lists his strongest likes and dislikes with a few words each, and every result ends with how it felt ("It felt really good.", "It did not feel good.").
- **Wearing off:** pleasant things are less exciting when repeated (`M.habit`; the joy halves after a few times and recovers over the days). Pain does not wear off, and old opinions soften a little every morning.

### Things outside his control

Day and night, rain, gusts and shooting stars arrive on their own timer. Nobody triggers them. When he is awake they reach him as events ("A strong wind rushed over the island."), and he can react or ignore them.

### The viewer

You are part of his world, but you do not run it. There are no event buttons, no time controls and no way to give him tasks. To change the world, change the code.

**You are in his world as a human.** You can be there in two ways (the 👣/✨ button at the top right toggles them, and the page remembers which you used last):

- **Fly (free camera):** you are wherever the camera is, up in the air, with a faint shadow on the ground under you when you are low enough.
- **Walk (first person):** you are a person on the ground and the camera is your eyes, at eye height (1.7). You never see your own body or shadow; only Honk sees you. Drag to look around. You move the way he does, on the same walk grid, so you go around trees, rocks and the pond. Use <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> (<kbd>Shift</kbd> to hurry), or click a spot, a thing or Honk himself and you go there along a path. **Follow** makes you walk a few steps behind him.  Toggling switches between the two views.

Honk does not know much about humans; he only perceives you, as a tall creature on two legs:

- **Arriving:** the first time, he sees "a human, a tall creature that stands on two legs". After that, when you come back after being away (closed tab, hidden tab, reload) he notices "the human is back. They were gone for about 3 hours", turns to them and shows ❗. As he gets used to you this gets quieter, down to a plain "The human is around again." and a short glance. Blinks shorter than 45 seconds do not count as visits.
- **While you are there:** you are on his mind only while your arrival still feels new to him: about two in-world hours the first time, then shorter with each visit, down to a few minutes. During that time his decision prompt says where the human is and how they move. After that he only mentions you when you are right beside him (at most every 90 in-world minutes), or just after you asked him something. Being near you still warms him; it just stops being a topic. Looking at you again and again shows nothing new and becomes dull. He turns to you when you arrive or come close; otherwise he glances at you now and then while idle, thinking or resting.
- **Asleep:** if you arrive while he sleeps, he finds the human there when he wakes. He sleeps out in the open, so you can watch him: curled up with his head on his back, eyes shut, little "z"s rising.
- **Walking with him:** his prompt says the human is walking on the ground on two legs. When you come right up to him he notices them ("The human came right up to me. I held very still"). How often depends on how used to you he is: about every 45 seconds at first, every 7 minutes or more once he knows you. If you follow him around for a while, he notes it once a day. When you walk close, he can reach you with his beak (`use` → touch).
- **Asking him things:** the field at the bottom centre (<kbd>Enter</kbd> jumps to it). He turns to you, shows 💬, and answers in one to three sentences in his own voice, from what he knows and feels. He may say he doesn't know.
  - The answer comes from a separate small prompt (`SYSTEM_TALK`), not from his decision prompt. It is not an action: nothing goes into his plans, and his next decision only hears "a little while ago they asked you … and you answered".
  - If he is asleep he does not wake up. Talks are kept in `talks` (the last 60) and shown in the Thoughts panel.
- **Memory:** `watcher: { visits, firstDay, lastSeen, talks }` in his state, so returns are noticed across sessions. The Mind panel shows how often he has seen you and how often you spoke to him.
- It never touches anything. What he makes of it is up to him.

**Screen layout.** The page loads the Nunito and Noto Color Emoji fonts, so emoji show even where the system has no emoji font. The buttons are drawn as SVG icons.

- **Top left:** Honk, his mood and his five feelings.
- **Top centre:** alerts drop in for each new thought (💭), each answer to you (🪿, with your question above it), new goals and notable events. At most three show at once; answers and goals stay while older thoughts make room. Click one to dismiss it.
- **Top right:** the clock, Walk/Fly, Follow and View.
- **Bottom left:** Honk's buttons (Honk's Work, Journal, Ideas, Hobbies, Mind, Thoughts), with a red counter when something new came in since you last looked. His current goal sits at the very bottom left and jiggles when it changes.
- **Bottom centre:** the ask field.
- **Over his head:** a small sign shows what he is doing (or ❗ / 💬).

Everything pops, bounces and wiggles a little; with "reduce motion" set in the system, it doesn't.

- **Hover:** a ring and a label say what a thing is, what Honk built and when, and on the grass whether he has been there. A second line shows how it weighs on him: what being near it does, its best and worst use (`smell: joy++ calm+ · sit: comfort−− joy−`), what a build is made of, and whether Honk has come to like or dislike it. **Right-click turns every label and the ring off; right-click again turns them back on.**
- **Camera (flying):** <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> move, <kbd>Q</kbd>/<kbd>E</kbd> down and up, <kbd>Shift</kbd> faster, left-drag to orbit, middle-drag (or <kbd>Shift</kbd> + left-drag) to pan, scroll to zoom, **Follow** to track him.
- **Panels:** Honk's panels open from the bottom left, View from the top right; <kbd>Esc</kbd> closes them.
  - **Honk's Work:** what he is working on right now, his programs (opened sandboxed) and his builds.
  - **Journal**
  - **Ideas:** his current goal with its steps, ideas set aside for later, ideas from thinking, questions from reading, wishes, goals reached, earlier goals.
  - **Hobbies:** his hobbies, how often he chose each kind of action, what he loves and avoids (from his likes), and what has been on his mind.
  - **Mind:** connection, feelings, what he feels around him, who he thinks he is, you, places, learned facts.
  - **Thoughts:** inner voice, actions with the reward each gave, and your talks.
  - **View:** render settings only.

### Extending the world

| To add | Edit in `main-hub.html` |
|--------|---------------------------|
| A new kind of thing | A factory that calls `spawn(kind, x, z, mesh)`, a `SENSE` line (what Honk perceives), a `WORD` (what he calls it), a hover `NAMES` entry, a `TOUCH` entry (what each verb does to his feelings) and, if being near it matters, a line in `ambient()` |
| A new place | An entry in `PLACES` with a radius and a first impression |
| A new action | `ACTIONS` (menu text), `planFor` (what happens) and, if it needs the model, a `do…` function |
| Tuning | `CONFIG`: day length, lockout, build limits, temperature |

The console exposes `window.world` (`spawn`, `addTree`, `PLACES`, `SENSE`, `CONFIG`, `M` for his memory, `nav` for the walk grid, `feel` for the weights and `ambient()`, `plan({ action, target, detail })` to make him do one thing while testing, `setMode('walk' | 'fly')` and `me` for your own body, `ask(text)` to ask him something, `alert({ kind, text })` for a top alert, `skip(seconds)`, `draw()` for one frame, `reset()` to wipe it).

### Running the prototype

Install Ollama and pull the model (Arch Linux shown; see [Machine and software](#machine-and-software) for Windows):

```bash
sudo pacman -S ollama-cuda
```

```bash
sudo systemctl enable --now ollama
```

```bash
ollama pull qwen2.5:7b
```

Start the server and open the page it prints (`http://127.0.0.1:8765/`):

```bash
python3 src/honk/server.py
```

- **Settings:** `HONK_MODEL`, `OLLAMA_URL`, `HONK_PORT`, `HONK_SEARXNG`, and `HONK_DATA` / `HONK_WORKSPACE` to run a test copy without touching his real memory (environment variables). A day lasts `CONFIG.dayLength` seconds, 3 hours by default; his energy and sleep, and how often weather happens, scale with it.
- **Tests:** `node --test tests/` (his mind) and `python3 -m unittest discover -s tests` (links, accounts, sharing against a fake GitHub).
- **Search:** DuckDuckGo's results page often answers automated requests with a bot check; the server then backs off and uses DuckDuckGo's Instant Answer API and Wikipedia search, which are narrow. For real web search, run a local [SearXNG](https://docs.searxng.org/) with the JSON format enabled and set `HONK_SEARXNG` to it.
- **Without a model** the page still runs: Honk lives his everyday life (exploring, looking, trying things, resting, sleeping) and the Mind panel says what is missing. He never fakes thoughts, and he cannot set goals, research, program or build.
- **Memory** lives in `data/honk-state.json` (and the archive in `data/events.jsonl`); his programs in `workspace/projects/`. Both are git-ignored. **Erase everything** (bottom of the 👁️ View panel, or `world.reset()` in the console) deletes all three and starts him over; it asks first.
- **Safety:** pages are fetched only from public addresses, as text; files are written only under `workspace/projects/` with text extensions, old versions kept in `.history/`; his programs are served with a sandbox policy so they cannot reach the server's API; the server listens on 127.0.0.1 only and refuses requests from other origins.

---

## Art direction and rendering

### World shape

Honk lives on a **floating island in a void**: a grassy meadow with small stylized trees (round puffs, two-tier puffs, little stacked-cone pines, the odd pink one), bushes, flowers, a pond that spills into a waterfall off the edge, and his desk in the open. There is no house. Smaller islands float around it and bob gently. Below is a sea of clouds and mist; there is no ground plane. New scenes (the train station) can be new islands he reaches later.

### Day and night

A full cycle (3 hours of real time in the world prototype, `CONFIG.dayLength`) driven by keyframes. Each keyframe sets sky top/horizon/void colours, cloud colour, fog colour and density, sun colour and strength, ambient light, star and aurora strength, exposure, god-ray strength and a shadow tint.

| Phase | Reference mood |
|-------|----------------|
| Day | Bright cyan sky, white clouds, saturated greens, god rays through the trees (floating-islands reference) |
| Golden hour | Warm orange haze, purple shadows, long rays (canyon-sunset reference) |
| Night | Deep teal, stars, green aurora, fireflies, glowing lanterns, a mint glow along the pond's shore (aurora reference) |

The cycle is also gameplay: night tires him faster, so he usually sleeps some of it, but when and where is up to him.

### Shader stack

```text
in every lit material (Lambert, grass, water):
  light falling on the surface (sun + sky + shadow) → cut into a few brightness steps
  → blended with an 8×8 Bayer pattern in screen space (cell 4 px by default)
  → multiplied by the surface's own colour
  ~3.8 steps up close (bold pattern), 16 far away (calm); strength 0.7; the darkest step is never black

scene → full-resolution HDR target (no pixelation)
  → god rays (radial march toward the sun, occluded by trees)
  → glow on bright pixels (sun, windows, lanterns, fireflies)
  → ACES tone mapping, saturation, shadow tint, vignette
  → ink outlines on silhouettes (from the depth buffer; fade out with distance)
  → sky, clouds and cloud sea dithered in the same pattern
```

Materials: wind-swayed instanced grass blades; plants drawn by a shader (below); flat-shaded rock cliffs tapering to a point, animated water (sparkles, shoreline glow), scrolling waterfall, procedural sky (gradient, clouds, cloud sea, sun, moon, stars, aurora).

### Plants are shaders

Leaves, bushes and flowers are not modelled. Each is a flat card that turns to face the camera, and the fragment shader cuts the real shape out of it: a cluster of pointed leaves around a dense middle (thin needles on pines), or a bent stem with one leaf and a round head of five petals with a coloured middle. A tree is a low-poly trunk plus a few dozen leaf cards scattered over round crowns; the cards are lit as if they sat on the crown, so each crown shades like a ball, and the shadow pass uses the same cut-outs. All of Honk's flowers are drawn as one mesh that rebuilds when one is added. Hovering a plant hits an invisible stand-in sphere, since the cards only exist in the shader.

### Two looks

The island prototype renders at full resolution and uses dither only for light: sunlight, shading and shadows are the dither pattern, colours stay as they are, and closer things get the boldest pattern. The earlier city prototype snaps to the 16-colour palette below with halftone foliage. Both run on the same pipeline; the colour-levels slider moves between them.

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

- **No pixelation** in the island prototype; the dither cell is 4 screen pixels. (The older city look used pixel size 3–4.) **Saturation** 1.4. **Outlines** full strength.
- **Halftone is per material:** foliage, sky and large shadow areas get screen-space dots in their own shader; everything else goes through the pixel dither.
- **Glow elements** (signs, windows, lamps) are unlit so they stay saturated.
- **UI is never pixelated:** cream rounded pills, dark text, coloured drive bars, a thought bubble above Honk.
- **Shimmer:** the dither is in screen space, so it stays still while things move under it; accept a little crawl on moving objects.
- **The palette is data:** swap it for day, dusk and night; lower saturation slightly when his mood is low; let Honk choose or invent palettes for scenes he builds.

### Prototype

- [`World/main-hub.html`](./World/main-hub.html): the current one. A larger island Honk explores on his own, driven by the local model: places to discover, senses instead of facts, web search and reading, programs he writes, objects he builds, a daily journal, sleeping wherever he likes, A* walking, weather, and watch-only panels for his mind, thoughts, journal and works. See [Living in the world](#living-in-the-world).
- [`World/island-demo.html`](./World/island-demo.html): the floating island with day/night, god rays, glow, dither, wind, and Honk's day routine. Sliders for time, day length, pixel size, colour levels, dither, rays, glow, saturation and wind.
- [`World/look-demo.html`](./World/look-demo.html): the palette-snapped city look with outlines and halftone.

Every object in both is built from recipes and generators, as described below.

---

## 3D assets

Honk never writes meshes. He writes small JSON **recipes** or picks **generator** settings; code builds the geometry, and the shader makes it fit.

### Recipes

```json
{
  "name": "lamp",
  "parts": [
    { "shape": "cylinder", "pos": [0, 0.8, 0],  "scale": [0.06, 1.6, 0.06], "color": "navy" },
    { "shape": "box",      "pos": [0, 1.7, 0],  "scale": [0.26, 0.3, 0.26], "color": "yellow", "glow": true },
    { "shape": "pyramid",  "pos": [0, 1.95, 0], "rot": [0, 45, 0], "scale": [0.25, 0.2, 0.25], "color": "navy" }
  ]
}
```

- **Shapes:** box, rbox (soft edges), sphere, dome, cylinder, taper, cone, pyramid, wedge (roofs, ramps), torus; later lathe for vases.
- **What the model writes:** no coordinates. A `base` part (it stands at the middle of the build) and parts that each go `on` an earlier part by its `id`, on a `side` (top, bottom, left, right, front, back) with an optional `off` slide. `mirror` (`x`, `z`, `xz`) and `ring` (3 to 12) repeat a part for legs, windows and petals. Code (`World/honk-build.js`) turns that into positions, so parts really touch. Plain `pos` recipes (the lantern, the stool, old saves) still work. The prompt carries four worked examples (chair, flower, house, lamp).
- **Flags:** `"glow": true` (unlit), `"halftone": true` (dot shader).
- **Material and use:** each part has a `"material"` and the recipe has a `"use"`; together they decide how it feels to sit, lie on, touch or play with (see [How things make him feel](#how-things-make-him-feel)). Older recipes without them count as wood (bark and stone colours as bark and stone) and get a use from their name.
- **The recipe is the asset:** tiny, diffable, committed to his GitHub. Export `.glb` only when something else needs a file.

### Generators

Big things come from code generators with a few parameters: `building(floors, width, sign, windows, roof)`, `tree(blobs, height)`, `track(kind, radius, angle)`, `train(cars)`, `stall`, `lamp`, `stool`. Track and station pieces snap together at fixed connection points, so building a station is arranging, not modelling.

### Parts library

A recipe he likes is saved under a name and becomes a part other recipes can use (`porch_with_lamp` contains `lamp`). The library is his procedural memory and his style; usage counts feed the repetition guard.

### Checks

Schema valid, at most 40 parts, sizes within bounds, auto-grounded and centred. Checked in `honk-build.js`: floating parts, too few parts, parts piled in one place, a wrong `on` id, roofs on the bottom, one colour or one shape only, and a use that does not fit (a lamp with nothing glowing, a shelter with no roof, a seat with no seat). The reasons go back to him once; if floating parts remain they are dropped, a use that does not fit becomes `art`, and a build with under 3 parts left fails with a small frustration hit.

### Seeing his work

Render a thumbnail headless (three.js under Playwright) and ask a small vision model (Gemma 3 4B or Qwen2.5-VL 7B) "does this look like a lamp, what is off?". At most two revisions. Load the vision model only while the text model is unloaded (`keep_alive: 0`).

### Later

- **Kit-bashing:** let him search and place CC0 packs (Kenney, Quaternius, Poly Haven); the shader makes them fit.
- **Drawing to 3D:** render one of his SVG drawings and run image-to-3D (TripoSR, Hunyuan3D-2mini) while the text model is unloaded. Lumpy meshes are fine under the dither.

### Hooks into his drives

Building costs energy, placing a finished object gives joy, every asset goes into `works`, and new shapes and generators unlock over time. What it is made of decides what it does to him afterwards: a soft seat makes desk work comfortable, a glowing lamp keeps the dark away, a roof keeps the rain off.

---

## Drives, mood and self-prompting

### State

All values are 0-100.

| Variable | Falls when | Rises when |
|----------|-----------|-----------|
| `energy` | Every tick; faster while working | Resting, night |
| `motivation` | Failure, boredom, repetition | Finishing something, progress on a goal |
| `happiness` (mood) | Repetition, failure | Novelty, sales, finished work |
| `curiosity` | Slowly rises on its own | Falls after `search` or exploring (it is satisfied) |
| `coins` | Spending | Sales |

`coins` is not a feeling, but it is what turns a wish (a train ticket) into a chain of goals.

### How he prompts himself

There is no user message. Each LLM tick, code converts state into a short first-person situation:

- Numbers become feelings: `curiosity 85` becomes "You are itching to find out something new."
- The strongest unmet need is named first.
- Recent notes and the active goal are added.
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
# src/honk/guards.py (sketch)
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
| A drawing sells, or does not | Coins, motivation |
| Something new appears in the world | Curiosity |
| Weather, day/night | Energy, mood |
| Something breaks (page offline, tool fails) | Frustration, a problem to solve |

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
4. **Build the prompt:** feelings, need, goal, notes, menu.
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
| `idle` | Nothing | Motivation drifts down |

### Growing without overloading the model

The target story needs more than seven actions (code, 3D, music, publishing, selling). Do not add them all to one menu. Use two steps:

1. **Pick an activity** from a short menu: `make`, `learn`, `share`, `rest`, `move`.
2. **Pick the specifics** in a second call that only shows options for that activity. `make` opens: drawing, page, code, 3D object, music.

New abilities are unlocked over time (by milestone, or by Honk reaching a place or goal), so his world widens gradually.

---

## Memory system

A small model has a small context window, so Honk cannot "remember everything" by keeping it in the prompt. Memory is layered like a person's: a little is always present, most is stored and recalled when relevant, and sleep turns the day into a diary entry and a slightly updated sense of self.

### Layers

| Layer | Holds | In every prompt? | Stored in |
|-------|-------|------------------|-----------|
| **Working memory** | Last ~10 events, current feelings, where he is, active goal | Yes | RAM |
| **Main memory** ("who I am") | Self-description, hobbies, likes and dislikes, life milestones, long-term wishes. Capped at ~500 tokens | Yes | `memory/self.md`, every version kept |
| **Side memory** | Everything else: episodes, summaries, facts learned, insights, pages read | Only the top ~5 recalled items | SQLite + embeddings |
| **Journal** | One first-person diary entry per in-world day | Yesterday's entry | `workspace/journal/YYYY-MM-DD.md` + table |
| **Interests** | Topics, scores, status, history | Top 3 | SQLite |
| **Goals** | The wish tree | Active goal and its parent | SQLite |
| **Skills** | What he knows how to make: parts library, generators, code snippets, success rates | As menu hints | SQLite + files |
| **Works** | Everything he made, with price and sales | When relevant | SQLite |
| **Places** | What is where in the world | Nearby only | World state |
| **Archive** | Raw event log, never deleted | No | SQLite `events` |

### Memory items

Every side-memory item carries:

- `kind`: event, summary, fact, insight, feeling, work.
- `importance` 1–10. Rules set most of it (routine move 1, finished work 7, first time doing something 8, sale 8); the model rates only creative items and what he read.
- `valence` −1 to 1: how it felt. Strong feelings are recalled more easily.
- `topics`, `embedding`, `last_recalled`, `recall_count`, `source_ids` (what it was summarised from).

### Recall

Each decision builds a query from the current situation (goal, place, feeling) and scores side memory:

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

1. **Journal entry.** From the day's summaries, feelings curve and sales, he writes a first-person entry: what happened, one thing he felt, one thing he learned, one wish for tomorrow. His mood shapes the tone.
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
- **No seeding:** topics come only from his own drawings, searches, reading and thoughts. Never pre-load cats or trains.

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
-- data/honk.db
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
CREATE TABLE skills   (name TEXT PRIMARY KEY, kind TEXT, path TEXT, uses INTEGER,
                       successes INTEGER);
CREATE TABLE works    (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, title TEXT,
                       path TEXT, price REAL, sold INTEGER);
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

Honk develops one recognisable look and uses it for everything he makes: websites, the shop, and the interface of this app. Target feel: playful, modern, clearly his.

### Files

- **`style/tokens.json`:** colours (from his palette), corner radius, outline width, shadow offset, label tilt, fonts, spacing. Generated into `tokens.css`.
- **`style/guide.md`:** the rules in his own words, versioned.
- **`style/components.html`:** his button, card, tag, nav and form, built only from tokens.
- **`style/inspiration.md`:** notes with links on things he liked and why.

### Starting point

Cream cards, dark ink outlines, hard offset shadows, big rounded corners, one accent colour per page, a rounded system font, slightly tilted labels, small bouncy motion, one column on phones.

### How it evolves

- **Action `refine_style`:** change at most one token per session, write down why and where the idea came from, bump the version. He can revert.
- **Inspiration sources:** web searches and pages he read (he stores short text notes, not images), his own drawings, and the colours of his world.
- **Coherence rule:** pages may only use tokens. A linter rejects hard-coded colours, radii and fonts.
- **Critique:** render the page headless, take a screenshot, let the vision model score it against the guide with `keep_alive: 0`. Contrast is checked in code (4.5:1 for text).
- **The app follows:** the viewer reads the same tokens, so when he changes one, his own interface changes too. The prototype's Style tab shows this.

---

## News channel

A feed of real-world news that reaches Honk like weather: he did not ask for it and most of it does not matter to him. What touches an interest does.

- **Source:** RSS and Atom feeds read with `feedparser`, listed in `config/feeds.toml`. A few general feeds (world, science, technology) plus topical feeds he adds himself as interests grow. No API keys needed.
- **Fetching:** a background job every 30 to 60 minutes, not the model. Items are de-duplicated by URL.
- **Table:** `news(id, ts, source, title, summary, url, tags, embedding, read, reaction)`.
- **Ranking:** similarity between the headline embedding and his interests, plus a small bonus for stories that appear in several feeds. The top three of the day become a newspaper by his desk.
- **Action `read_news`:** one short model call per item returns `{feeling, thought, interest?, want_to_do?}`.
- **Effects:** an item he cares about can raise an interest, add a journal line, or seed a goal ("draw a night train"). An item he does not care about gets a shrug and no memory.
- **Limits:** five items per day at most, about 60 tokens each. Feed text is untrusted data and never an instruction. Its effect on mood is capped, and distressing topics can be filtered out in the feed config.

### The feed (built)

The island page has a **Feed** panel. It is a social feed of made-up accounts (`World/honk-feed.js`): a pixel artist, a harsh critic, a hype founder, a gardener, a troll, a kid and others. Each account has its own voice and temper.

- **Posts:** a new post arrives every 2 to 6 minutes. Half come from templates; the other half are written by the everyday model while Honk's own mind is idle. Many posts carry a picture drawn by `honk-art.js`.
- **What Honk can do:** `feed` (scroll), `post` (optionally showing one of his drawings), `reply` (to a post by its id) and `message` (a direct message to an @handle). He writes everything in **his own voice**, which he redescribes himself in his nightly journal (`M.voice`: style, temper, quirks), coloured by his mood.
- **Replies to him:** the accounts reply to his posts and answer his messages after 20 to 90 seconds, in character. They also write to him first now and then, more often once he sells something.
- **What it does to him:** what he reads pushes his feelings (kind words lift him, meanness about his own work stings) and may leave an idea for later. It never sets his goals.
- **Later:** any source with `next(feed, rnd) -> post` can replace the bots, for example x.com.

### Drawing, design and purpose (built)

- **Drawing (`draw`, `improve`):** he writes a JSON recipe, and `honk-art.js` turns it into an SVG in `workspace/projects/art-<series>/`. A recipe uses motifs that code draws well (butterfly, cat, flower and so on), plus shapes, symmetry and a palette. A critique pass catches empty, tiny or low-contrast pictures, and he fixes them once. Drawings belong to a series and show in the Work panel.
- **Design (`honk-design.js`):** pages and apps (a gallery, a shop, a tool) start with a design brief: who it is for, what they can do, which sections, what tone. The design guide goes into the prompt. A design check (placeholder text, no viewport, too many colours or fonts, no hover states and so on) feeds problems back for `improve`.
- **Purpose:** when he has no goal, he is told what his work could become instead of being handed random ideas. A series of four becomes a gallery page, six with a gallery becomes a shop, and a working page becomes something to share. Goals carry a "for whom".

### Models and resets

- **The 🧠 14b button**, and the same switch under View settings → AI models, turns the big code model on or off. Off stops what it is writing at once and unloads it from memory. Programs, drawings and builds then use the everyday model.
- **Reset the AI models** (View settings) stops everything the models are writing and unloads them; his memory stays. **Erase everything** (View settings → Start over) deletes his memory and starts him fresh.
- **One page at a time:** only one open page lives Honk's life. A second tab, or a page running older code, has its saves, model calls and file writes refused, and only watches. Its pill shows 🔒.

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

Honk browses, searches, reads and experiments freely, but he never pays, never types a password and never signs up anywhere himself. Sign-ups need an email inbox, CAPTCHAs and someone to accept the terms; GitHub's terms also require a human to register a machine account. So when he wants an account, it shows up as a wish in his Mind panel, and you make it:

- **GitHub:** you register a machine account and accept the terms as its responsible human. Create a fine-grained personal access token limited to that account's repositories, with *Administration* and *Contents* set to read and write. Put it in `config/accounts.json` (git-ignored):

  ```json
  { "github": { "user": "his-github-name", "token": "github_pat_...", "share": "ask" } }
  ```

  Restart the server. He sees only "github (his-github-name)", never the token, and `share` appears on his menu. With `"share": "ask"` every share waits in the Works panel for **Share it** or **Keep it private**; `"auto"` lets him share on his own.
- **Email address:** you create it. He gets send/receive through a narrow tool, not the password (not built yet).
- **Money:** start with in-world coins and simulated buyers. Real payments are a later, separate decision.

---

## Safety and limits

- **Sandbox:** everything he writes goes under `workspace/`. Code he writes runs only inside a container or restricted process, never on the host directly.
- **Secrets:** tokens live in environment variables or a local secrets file outside `workspace/`. They are never placed in a prompt.
- **Outbound actions:** pushing, posting and emailing go through a queue. Begin with manual approval; relax per action type once trusted.
- **Budgets:** caps on model calls per minute, files per day and disk used.
- **Kill switch:** one command pauses the loop; state survives a restart.
- **Mood floor:** negative feedback is strong by design, so add a floor and a slow natural recovery. Otherwise one bad streak becomes a permanent slump with nothing left to try.

---

## Project layout

```text
AI-Companion/
├── HONK.md              this file
├── config.toml          model name, tick rate, all tuning numbers
├── src/honk/
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
│   └── server.py        serves the viewer; model, web search, page reading, workspace, memory (exists)
├── web/                 three.js world, pixel/dither pipeline, UI
├── World/               main-hub.html (current), island-demo.html, look-demo.html
├── memory/self.md       main memory ("who I am")
├── workspace/           everything Honk makes (drawings, sites, code, music, journal)
├── data/honk.db         side memory and all tables
└── tests/
```

---

## Milestones

### Core (from the original plan)

- [ ] **M1:** grid world, Honk moves, drives decay and recover. No model.
- [ ] **M2:** model decision loop with JSON output and validation.
- [ ] **M3:** event log, side memory with recall, main memory, nightly journal and forgetting.
- [ ] **M4:** interest scores and `draw` (SVG output).
- [ ] **M5:** `search` and `build_page` (static HTML into a folder).
- **M6:** dropped. There is no chat with Honk and no visitors; the builder only watches (as a human he can see) and changes the world in code.

### Behaviour (from the vision)

- [ ] **M7:** all three anti-repetition guards, with tests. Fits best right after M2.
- [ ] **M8:** random outside events (weather, sky, news).
- [ ] **M9:** goals with sub-goals and a reflection step.
- [ ] **M10:** coins, works table, shop page, simulated buyers.

### Expansion

- [ ] **M11:** two-step menu; sandboxed code; local Git.
- [ ] **M12:** GitHub machine account and approved pushes.
- [ ] **M13:** piano and recorded jams.
- [ ] **M14:** three.js world with the pixel/dither pipeline, recipe builder, generators and parts library (prototype exists).
- [ ] **M15:** second scene: the train station.

### World and taste

- [ ] **M16:** exploration world: places, senses, discovery, outside events, no survival (prototype exists).
- [ ] **M17:** the mind loop on the real model: menu of look, think, search, read, code, build, with validation and the guards (prototype exists in the browser; port to the Python loop).
- [ ] **M18:** objects he builds: recipes first (prototype exists), behaviour for them later.
- [ ] **M19:** viewer: the watcher as a human Honk notices, hover labels (right-click toggles them), WASD camera, panels (prototype exists).
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
| Public on the internet? | Local only until the safety section is implemented |
| How fast is a tick? | 5 seconds, model call at most every 15 |

---

## External resources

- [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md): chat endpoint and structured output.
- [Ollama model library](https://ollama.com/library): model tags and sizes.
- [Godot Engine documentation](https://docs.godotengine.org/en/stable/): for the 3D world.
- [GitHub fine-grained tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens): scoping Honk's access.
