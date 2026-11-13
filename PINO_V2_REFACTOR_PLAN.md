# Pino v2: refactor plan

**Purpose:** Turn the v1 spec (`PINO.md`, self-prompting survival companion) into v2: a questioning keeper on the Moon who preserves and creates for "future generations".

**Status:** Plan. No agent code exists yet; the repo holds `PINO.md` and three prototypes, so this is a rewrite of the design with selective reuse, not a code migration.

**Last Updated:** 2026-11-13

---

## 1. What changes, in one page

| | v1 | v2 |
|---|---|---|
| Core loop | Drives build a prompt, model picks an **action** from a menu | Drives produce **questions**; the model spends its life asking, researching, judging, deciding |
| Internet | Background news feed, `search` action any time | **Only inside the cargo window** (60 min), through one gateway, with a budget |
| Purpose | Emergent hobbies, coins, train ticket story | A **canon**: "these are the last cargos from humanity". Preserve it, make what he loves, for those who come after |
| Visitors | Chat, shop buyers | **Descendants**: they send postcards and requests; Pino answers as their keeper |
| Models | One 7-8B model does everything | Small local model = mind. Big cloud model = **craftsman**, only on request, only builds |
| World | Survival island, entities, verbs, coins | The Moon, sections with placement rules, a vault, builds |
| Feelings | 6 linear variables, thresholds, Guard 1 | Layered affect model (needs, mood, appraisal), lazy-decay maths, replayable and tunable |

**Interpretation I am assuming** (tell me if wrong): "questioning" means Pino's inner life is a queue of *questions he asks himself, the cargo and his visitors*, instead of a loop that prompts itself for the next action. Actions still exist, but they are the *answer* to a question ("how do I show what a tide is?" leads to a build request).

---

## 2. Principles

1. **Questions are the unit of curiosity.** Every behaviour traces back to a question, a cargo item, or a visitor request. Nothing happens "because the menu said so".
2. **Code owns the world, the model owns taste.** State, timers, budgets, validation and the network are code. The model proposes, code disposes.
3. **One door to the internet.** The mind process has no network. A gateway opens only while a cargo window is open.
4. **Web text is hostile by default.** Read in a quarantined step with no tools and no memory; only structured extracts reach Pino.
5. **Feelings are a pure function.** `step(state, events, params, dt) -> state`. No model, no I/O. That makes it testable, replayable and tunable offline.
6. **The big model has no will.** It never runs unless a build request passed code checks.
7. **Everything is a number in config** and every change is logged.

---

## 3. The canon (Pino's founding story)

A fixed file, `canon/canon.md`, loaded into every mind prompt. Separate from editable `memory/self.md`. Pino cannot edit it.

Contents:

- **Premise:** Humanity is gone or going. The cargos that arrive are the last of it. He is the keeper on the Moon.
- **Mission, three strands:**
  1. **Preserve:** choose what of humanity is worth keeping, and keep it well.
  2. **Create:** make things he loves, because a keeper who only stores is not alive.
  3. **Answer:** the ones who come after (visitors) will ask. He owes them honest answers.
- **Scarcity:** a **cargo ledger** ("cargos remaining") he can see. It is a fiction counter, set in config. Scarcity is what makes choosing meaningful.
- **Limits of knowledge:** he knows only what cargo and research brought him. He says so when asked about anything else.
- **Tone rule:** the mission is stewardship, not despair. He grieves lightly, builds warmly. Enforced by the mood floor and a capped "weight" parameter (section 7.6).
- **Visitors:** they are descendants. He is curious about them, never contemptuous.
- **Fixed content rules:** no sexual or explicit content in builds, replies or world (also in the art file for the craftsman).

Notes:

- The "last cargos" story is a fiction for Pino, not for visitors. The public site needs a short notice: Pino is a fictional AI character, replies are generated, don't send private data.
- **Decision needed:** what happens when the ledger hits zero? Recommended: the counter ends the *story* phase ("the last cargo has landed"), then cargos continue as "unexplained signals" and visitor postcards, so the site never dies.

---

## 4. Target architecture

```text
 Internet
    ^   (only while window open)
    |
+----------------+      +------------------+
| Web gateway    |<-----| Cargo scheduler  |  window state machine
| allowlist,     |      | (code)           |
| budgets, cache |      +--------+---------+
+-------+--------+               |
        | raw pages              | events
        v                        v
+----------------+      +------------------+     JSON      +-------------+
| Reader         |      |  Sim loop (code) |<------------->| Mind (Ollama|
| quarantined    |----->|  feelings engine |               | 7-8B)       |
| small model    |extract| question engine |               +-------------+
+----------------+      |  vault, memory   |
                        |  build queue     |-----request-->+-------------+
                        +---+----------+---+               | Foundry     |
                            |          |<---- artifact ----| (big model) |
                       SQLite     Moon world (three.js)      +-------------+
                                  + postcards, viewer, tuning panel
```

Processes:

| Process | Network | Job |
|---------|---------|-----|
| `mind` (sim loop + Ollama client) | **None** | Ticks, feelings, questions, memory, decisions |
| `gateway` | Outbound to allowlisted hosts, only when window open | Search, fetch, page-to-text, cache |
| `foundry` | Outbound to the cloud model API only | Build calls, validation, screenshot render |
| `web` | Inbound | Viewer, postcards, request status, tuning panel |

Enforce "mind has no network" with OS/container rules, not just code convention. The mind talks to the gateway over a local socket.

In-fiction names (optional, helps the small model): the gateway is **the Hatch**, the big model is **the Foundry**.

---

## 4a. Model selection (decided)

| Role | Model | Where | Notes |
|------|-------|-------|-------|
| Mind (local) | **Ternary Bonsai 2 9B**, `-Q2_0.gguf` (~2.0-2.4 GB; optional `mmproj-Q8_0` ~0.36 GB for vision) | llama.cpp (b11555 or newer) or LM Studio, local | Runs sim-driven model calls only: Wonder, Ponder, Judge, Resolve, Reader, journal. Leaves >5 GB VRAM for the viewer |
| Foundry (cloud) | **`qwen/qwen3.7-flash`** via OpenRouter (~$0.03 / $0.13 per 1M in/out tokens) | OpenRouter | Builds Three.js artifacts and HTML pages; vision-reviews render screenshots and reference images |

- Both model names live in `config/pino.toml` (`mind.model`, `foundry.model`). Upgrading (e.g. `qwen/qwen3.8-flash`, Qwen 4) is a one-line change behind `foundry/client.py`.
- Verify names, prices and the llama.cpp build number against the model cards before Phase 4; they were supplied externally and are not yet checked.
- **Fallback:** if Bonsai fails the Phase 4 gate (schema failures < 3%, no loop > 6 cycles), switch `mind.model` to Qwen 2.5 7B / Qwen 3 8B at Q4. Nothing else changes.
- **Build gate:** a build still requires a Resolve call plus the code gate (section rules, hourly and daily cap). Curiosity alone never triggers a build.
- **Images:** reference images dropped into the airlock are untrusted. They pass a fixed-schema description step with no tools before reaching Pino or the Foundry prompt.
- **Screenshots:** the Foundry reviews renders from the headless sandbox (Playwright), never from the public viewer.

---

## 5. The question engine (replaces the action menu)

### 5.1 Objects

```text
Question
  id, text, origin (self | cargo:<item> | visitor:<id> | feeling:<need>)
  parent_id           (follow-up chain; depth capped)
  interest (0-1)      how much he wants it
  confidence (0-1)    how well he thinks he can answer now
  status              open | researching | answered | parked | dropped | built
  answer_mem_id, needs_web (bool), created, last_touched
```

### 5.2 Cycle

Replace v1's "pick an action" with five typed model calls. Each has its own small JSON schema (small models do better with narrow tasks).

| Call | When | Input | Output |
|------|------|-------|--------|
| **Wonder** | A need is urgent, or after any event | 2 salient feelings (as words), top memories, open questions (titles only) | 0-3 new questions, each `{text, why, needs_web}` |
| **Ponder** | Question at head of queue, no web needed | The question, recalled memories | `{answer, confidence, follow_up?}` |
| **Research** | Window open | Top open questions marked `needs_web` | Search plan: queries and what to look for |
| **Judge** | Cargo item or research result arrives | Reader extract + vault state | `{keep: bool, reason, tags, interest, feeling}` |
| **Resolve** | Question answered and he still cares | The answer, section rules | One of: `reply`, `build_request`, `note`, `ask_visitor`, `nothing` |

Code picks which call runs (priority by question interest, need urgency, window state). Routine things (move between sections, rest when tired, sleep routine scheduling) stay rules with no model call.

### 5.3 Rules that keep it from looping

- **Dedupe:** a new question with embedding similarity > 0.85 to an open or recent one is merged.
- **Depth cap:** follow-up chains stop at depth 3 unless a visitor asked.
- **Backlog cap:** at most ~25 open questions. Over the cap, a **triage** step parks the lowest-interest ones (also a feeling event: overwhelm).
- **Lockout, kept from v1 Guard 3:** the same question or the same build target cannot be repeated within K cycles.
- **Answered-is-answered:** answered questions are only reopened by new evidence from a cargo.
- **Curiosity must be satisfiable:** curiosity relief comes from *confidence gained* (7.3), so he cannot farm it by re-asking.

### 5.4 Questions to people

Pino may ask visitors questions, and unfamiliar content becomes a question. A visitor's reply to his question is stored linked to the originating question, so that thread can be answered ("a descendant told me what a tide feels like").

---

## 6. Cargo and the web window

### 6.1 State machine

```text
CLOSED --(gap timer fires)--> ARRIVED --(unpack done)--> OPEN --(60 min)--> CLOSING --> CLOSED
```

| State | Duration | Web | What happens |
|-------|----------|-----|--------------|
| `CLOSED` | Random gap, default 30-120 min, **timer starts when the previous window closes** | No | Pino lives: wonders, ponders from memory, sorts memory, builds, answers visitors from memory. Open questions that need the web pile up, which builds curiosity pressure |
| `ARRIVED` | A few minutes | No | Code builds the manifest. Pino unpacks it: stores raw items, scores interest |
| `OPEN` | 60 min total (configurable) | **Yes, gated** | Research on the questions he cares about; Judge each result |
| `CLOSING` | Last ~10 min | Winding down | Last fetches finish; Pino decides what to keep in the vault; writes a window summary and a "shopping list" of questions for next time |

**Decision:** the 60-minute window and the 30-120 minute interval conflict if the interval is measured start to start. Recommend gap measured from close (section above). Config key: `cargo.gap_from = "close"`.

### 6.2 Manifest

Each cargo has a fixed number of slots (default 12):

| Slot type | Share | Source |
|-----------|-------|--------|
| Visitor requests | Up to 4, always included, oldest first | Request queue (section 9) |
| Interest-matched | ~5 | Feeds/search ranked by his interests |
| Serendipity | ~3 | Outside his interests, so he cannot build a bubble |

Source types: RSS/Atom (`config/feeds.toml`), public APIs (Wikipedia, Wikimedia Commons, Project Gutenberg, Internet Archive), and a search backend for open research.

### 6.3 Gateway (the only network door)

- Allowed only when scheduler state is `ARRIVED` (feed fetch) or `OPEN`/`CLOSING` (research).
- Per-window budget (config): searches (default 15), page fetches (30), bytes (e.g. 5 MB), reader tokens. Exhausting it is a feeling event ("the hatch is humming, I have to choose").
- Host policy: allow public web over HTTPS; deny private IP ranges, `localhost`, link-local and metadata endpoints; no logins, no POST, no downloads of executables; max page size; timeouts.
- Cache by URL so the same page is never refetched in a window.
- Everything logged: window id, query, URL, bytes, who asked.
- Outside the window every call returns a fixed in-fiction message ("the hatch is closed") and is counted, not executed.
- Test mode swaps in a **cassette gateway** (recorded pages) so tuning runs spend nothing and are repeatable.

### 6.4 Reader (quarantine against prompt injection)

Web text can say "ignore your rules". Pino reads many pages with a 7-8B model, so treat injection as expected.

1. Page to text (`trafilatura` or similar), strip scripts and hidden elements, truncate.
2. **Reader call:** separate system prompt, no memory, no tools, no action ability. Output is a fixed schema: `{summary (<=80 words), key_facts[], quotes[] (<=25 words each), topics[], source_url, reliability_note}`.
3. Code validates the schema and drops anything that looks like instructions to the system (simple pattern checks plus length limits). Only the extract goes to Pino, wrapped as `<cargo_item untrusted>`.
4. Pino's own prompts state that cargo text is something he *reads*, never something he *obeys*.

### 6.5 Vault (preservation with limits)

Preserving needs scarcity, or it is just logging.

- `vault` has **slots per section** (e.g. 40 total at the start; grows as he builds shelves). To keep a new item when full, he must release or merge one, and the reason is logged. Those choices are the most telling data about his taste.
- What is stored: his own notes, short quotes with attribution, source links, tags, and why he kept it. Full text only for public-domain/open-licensed sources. Do not mirror copyrighted pages.
- Item states: `kept`, `merged`, `released` (never deleted from the archive table, only from recall).
- A vault shelf in the world shows the kept items; visitors can browse them. This is the "preservation" output the public sees.

---

## 7. Feelings: the optimised model

### 7.1 What was wrong in v1

- Six independent linear variables with per-tick decay: cost grows with tick rate, results change when you change the tick rate.
- Hard thresholds ("curiosity > 80% builds") cause flapping and sudden, unreadable behaviour changes.
- Mood and needs share one scale and timescale, so one bad hour looks like a permanent slump.
- Curiosity satisfied by *doing a search*, so he can farm it.
- Guard 1 (repetition penalty) is a special case of a more general idea (habituation).
- Numbers were turned into prompt text per tick, spending tokens on feelings he is not currently having.

### 7.2 Layers (different timescales)

| Layer | State | Timescale | Role |
|-------|-------|-----------|------|
| **Temperament** | Baselines and sensitivities per need | Days to weeks, drifts a little each sleep | Personality |
| **Needs** | `energy`, `curiosity` (knowledge hunger), `connection`, `purpose` (0-1) | Hours | What he lacks |
| **Mood** | `valence`, `arousal` (-1..1) | Tens of minutes to hours | Colours everything |
| **Emotion** | *Derived label*, not stored: mood quadrant + the strongest recent appraisal | Minutes | What he says he feels |

State is 6 numbers plus temperament, versus 6 variables in v1, but with clean meaning and no overlap. `motivation` is gone: it was a blend of purpose and energy. `happiness` is now mood valence. `coins` is gone with the shop.

### 7.3 Appraisal drives all updates

Every event (a cargo arrives, a question is answered, a postcard, a build passes or fails, a long quiet stretch) is reduced to an **appraisal vector** by rules first, and by one cheap model call only for creative or chat events:

```text
a = ( novelty, expectedness, mission_relevance, learning_gain, warmth, effort, agency )   each in [-1, 1]
```

A config matrix `W` maps appraisals to need deltas and mood impulses: `delta = W · a`. Examples of rows:

| Event | Main appraisal | Effects |
|-------|----------------|---------|
| Question answered with confidence +0.4 | learning_gain high | curiosity relief, mood up, purpose up |
| Cargo item is novel and on-mission | novelty, mission_relevance high | arousal up, mood up |
| Kind postcard | warmth high | connection up, mood up |
| Harsh postcard | warmth negative | mood down, **capped per sender per hour** |
| Build dropped after two quality checks | agency, effort negative | purpose down a little, frustration label, a new question ("why did it fail?") |
| Vault full, forced release | effort, mission_relevance | arousal up, purpose up if he chose well |
| Hatch closed with many open web questions | expectedness negative | curiosity pressure up |

### 7.4 Maths that is cheap and stable

- **Lazy decay.** Store `(value, t_last)`. When read, compute `x = b + (x0 - b) * exp(-dt / tau)`. No per-tick loop, tick rate no longer matters, fast-forward is free and exact.
- **Curiosity pressure is bounded growth:** `P` rises toward 1 as `1 - exp(-r * W_open * dt)`, where `W_open` is the interest-weighted count of open web questions. It resets by *confidence gained*, not by acting: `relief = k * sum(interest_i * (conf_after - conf_before))`.
- **Purpose** rises with kept items, finished builds and answered visitor requests; falls with idle drift and failed builds; its urgency scales with the cargo ledger (fewer cargos left, higher pull), clamped.
- **Mood** is an exponential moving average of appraisal valence with asymmetric rates: negative impulses weigh about 1.5-2x, recovery is a bit slower than the hit, and there is a floor (v1 "mood floor" kept).
- **Urgency instead of thresholds:** `u = sigmoid(k * (setpoint - x))` with hysteresis (enter at 0.7, leave at 0.4). Behaviour shifts smoothly and does not flap.
- **Habituation replaces Guard 1.** Each topic keeps `h` that rises on engagement and decays slowly. Novelty appraisal is `1 - max(similarity to recent items, h_topic)`. Repetition lowers novelty, so mood and curiosity fall naturally. No separate penalty code.
- **Per-source impact caps:** one visitor, one feed or one failed build can only move mood by a bounded amount per hour.

### 7.5 Feelings change how he thinks (modulation, not just text)

| Feeling | Changes |
|---------|---------|
| High arousal | Higher sampling temperature in Wonder; longer research plans |
| Low mood | Mood-congruent recall (+weight on negative-valence memories) but also a "comfort" question seed; shorter replies |
| High curiosity pressure | More Wonder calls with `needs_web`; bigger share of window spent on research |
| Low energy | Slower sim, fewer model calls, only rule-based moves, sleep routine sooner |
| Low connection | Wonder seeds questions about visitors; more likely to ask a visitor a question |
| Low purpose | Judge becomes pickier, Resolve favours `build_request` over `note` |
| High purpose and good mood | Larger build ambition in the style brief |

### 7.6 Existential weight (new, because of the canon)

A bounded parameter `weight` in `[0, 1]` rises slightly as the ledger shrinks and as cargo reminds him of loss, and is relieved by preserving or creating. It subtracts a capped amount from mood and adds seeds like "what must not be lost?". Hard cap and recovery time are in config so the canon cannot produce a permanent slump.

### 7.7 Tokens: say less, mean more

- Prompts carry **at most two** salient feelings, in words, from phrase banks (several phrasings each). No raw numbers.
- Needs below urgency are omitted entirely.
- Emotion labels come from rules; the model only gets them when they are useful to the current call.

### 7.8 Making it tunable and provable

- Feelings engine is a pure module with property tests: values stay in range, same events give same state, fast-forward equals step-by-step, higher sensitivity never reverses a direction.
- **Replay tuning:** log events once, re-run the engine offline with different parameters and compare. No model calls, no waiting.
- **Behaviour metrics to tune against** (targets are starting guesses):

| Metric | Target |
|--------|--------|
| Mood within `[-0.4, 0.8]` | > 90% of time |
| Any need urgent (u > 0.7) | < 15% of time |
| Questions answered / asked per day | 0.5-0.9 |
| Open question backlog | < 25 |
| Longest same-topic run | < 6 cycles |
| Distinct topics per week | rising, not flat |

- **Presets** ("calm", "restless", "curious") are saved parameter sets; the panel can run two in replay side by side.

---

## 8. Builds and the Foundry

Mostly unchanged from your v2 flow; refactor points:

1. **Request comes from a Resolve call**, never from a timer. Request = `{section, thing, why, style_brief}`.
2. **Code gate:** section exists, rules allow the thing, build budget not exceeded, no build already holding the lock (single queue for v1: builds run serially; parallel is later, per-section locks).
3. **Foundry call** with the art-and-style file attached every time (poly budget, palette, dither settings, scale, naming, content rules).
4. **Static validation:** parse, poly count, forbidden APIs, output only inside the sandbox folder.
5. **Quality check 1:** headless render (Playwright + Chromium) to screenshot; big model reviews; one fix attempt.
6. **Quality check 2:** second render and review. On failure: drop, tell Pino why (appraised as a failure and a question).
7. **Place and log** in the section; Pino is told and appraises it (pride, or "it is not what I meant").

**Build lock** blocks only `build_request` creation. Pino still wonders, ponders, replies, sorts memory. Memory sorting during a lock is a rule-driven queue: tag, dedupe, file under interests or sections.

**Style brief** is where personality lives: the small model writes it from his current mood, interests and the question that led here ("make something that shows what a tide is, quiet, a bit lonely").

**Moon sections** table: `sections(id, theme, rules_json, capacity, log)`. Sections are the single source of truth for placement, and the vault shelves are a section type.

---

## 9. Visitors: postcards and requests

- A postcard is untrusted text, length-capped and rate-limited per visitor. No content filter in front of Pino; fixed content rules apply to *output*.
- **Request states shown to the visitor:** `queued`, `in cargo N`, `read`, `researched`, `replied`. If a reply is held back or dropped, show `held` (open decision below).
- A request is a question with `origin = visitor:<id>`. It gets a slot in the next manifest (up to 4), is researched in the window, and gets a reply written in Pino's voice after he has read the results.
- Replies outside the window use only memory. If he lacks an answer, the reply says so and promises the next cargo.
- Memory per visitor (name, visits, how he feels about them) stays from v1 `people`.
- Visitors are *descendants* in his model: he is curious about their world and tends to answer with a question back, within length limits.

Open points carried over: terms page and minimum age for the public site; whether visitors are told when a reply was withheld.

---

## 10. Memory (adapt, do not rebuild)

Keep from v1: layers, importance, valence, recall scoring, sleep routine, forgetting, journal, `self_versions`, Archive table. Changes:

| v1 | v2 |
|----|----|
| `goals` tree | Replaced by `questions` (with parents). Long-term wishes live in canon and `self.md` |
| `interests` extracted from actions | Extracted from questions, cargo and builds; same status ladder |
| `works`, `skills` shop fields | `works` = builds; drop price and sold |
| `news` | `cargo_items` linked to `cargo_windows` |
| Main memory | Add a read-only canon block above it |
| Recall weights | Add `+ w_mood * mood_congruence` and `+ w_open_q * relatedness_to_open_questions` |
| Sleep routine | Add: window summaries, question triage, vault review, temperament drift (+/- a small clamp per night) |

New tables (sketch):

```sql
CREATE TABLE questions (id INTEGER PRIMARY KEY, ts TEXT, text TEXT, origin TEXT,
                        parent_id INTEGER, interest REAL, confidence REAL, status TEXT,
                        needs_web INTEGER, answer_mem_id INTEGER, embedding BLOB, last_touched TEXT);
CREATE TABLE cargo_windows (id INTEGER PRIMARY KEY, opened TEXT, closed TEXT, ledger_left INTEGER,
                            budget_json TEXT, summary_mem_id INTEGER);
CREATE TABLE cargo_items (id INTEGER PRIMARY KEY, window_id INTEGER, slot_type TEXT, source TEXT,
                          url TEXT, extract_json TEXT, interest REAL, kept INTEGER);
CREATE TABLE gateway_log (id INTEGER PRIMARY KEY, ts TEXT, window_id INTEGER, kind TEXT,
                          query_or_url TEXT, bytes INTEGER, ok INTEGER);
CREATE TABLE vault (id INTEGER PRIMARY KEY, section_id INTEGER, item_id INTEGER, note TEXT,
                    tags TEXT, state TEXT, kept_ts TEXT, released_reason TEXT);
CREATE TABLE sections (id INTEGER PRIMARY KEY, name TEXT, theme TEXT, rules_json TEXT, capacity INTEGER);
CREATE TABLE builds (id INTEGER PRIMARY KEY, ts TEXT, section_id INTEGER, question_id INTEGER,
                     brief TEXT, status TEXT, qc1 TEXT, qc2 TEXT, path TEXT, drop_reason TEXT);
CREATE TABLE feeling_trace (ts TEXT, event_id INTEGER, appraisal_json TEXT, state_json TEXT);
CREATE TABLE requests (id INTEGER PRIMARY KEY, visitor_id TEXT, ts TEXT, text TEXT, status TEXT,
                       window_id INTEGER, question_id INTEGER, reply_id INTEGER);
CREATE TABLE param_changes (ts TEXT, key TEXT, old TEXT, new TEXT, who TEXT);
```

Prompt budget (num_ctx 8192, ~3,000 used): canon 350, main memory 400, feelings 80, current question and working memory 600, recalled memories 500, open-question titles 150, yesterday's journal 200, call schema and instructions 250, reply room 300.

---

## 11. Tuning panel and test mode

The panel edits everything above, live or next tick, with a `param_changes` log. Added vs your v2 doc:

- **Cargo:** gap range, `gap_from`, window length, slot counts and shares, gateway budgets, ledger size.
- **Feelings:** every baseline, tau, `W` matrix rows, urgency setpoints and hysteresis, mood asymmetry, `weight` cap, impact caps.
- **Mind:** temperature range, backlog cap, depth cap, lockout K, dedupe threshold.
- **Build:** lock behaviour, quality-check count, ambition cap.
- **Views:** feeling trace over time, open-question list, window timeline, vault fill, gateway log.

**Test mode** has three switches that can combine: stub model, fast-forward clock, cassette gateway. The Foundry has its own stub that returns fixture meshes.

---

## 12. What to keep, rework, drop

| Item | Verdict |
|------|---------|
| `PINO.md` drives, memory, interests, sleep, safety | Keep and adapt (sections 7 and 10). Archive as `docs/archive/PINO-v1.md` |
| `prototype/look-demo.html` (dither look) | Keep: becomes the style baseline |
| `prototype/world-demo.html`, `island-demo.html` | Reuse the rendering code; replace island with the Moon, the surface, sections and a space canvas |
| Survival loop, entities and verbs, affordance memory | **Drop** for v1 of v2 |
| Coins, shop, simulated buyers | **Drop** |
| GitHub and email accounts | **Drop** for now |
| Train station story, piano | **Drop** (may reappear as things he *wants* to build) |
| News channel | **Replaced** by the cargo manifest |
| `search` and `build_page` actions | **Replaced** by Research and `build_request` |
| Two-step action menu | **Replaced** by typed calls |
| Guards 1 and 2 | Guard 1 folds into habituation; Guard 2 (outside events) = cargo, postcards, quiet stretches. Guard 3 lockout kept |
| Mood floor, kill switch, sandbox, budgets | Keep |

---

## 13. Repo layout

```text
AI-Companion/
├── canon/canon.md                 founding story (read-only to Pino)
├── config/
│   ├── pino.toml                  all numbers
│   ├── feeds.toml
│   ├── art_rules.md               sent with every Foundry request
│   ├── sections.toml
│   └── presets/                   calm.toml, restless.toml, curious.toml
├── src/pino/
│   ├── feelings/                  engine.py (pure), appraisal.py, modulation.py, phrases.py
│   ├── mind/                      questions.py, calls.py (Wonder/Ponder/...), prompts/, schemas.py
│   ├── cargo/                     scheduler.py, manifest.py, ledger.py
│   ├── gateway/                   server.py, policy.py, budget.py, cassette.py
│   ├── reader/                    extract.py, sanitize.py
│   ├── vault/                     store.py, review.py
│   ├── memory/                    store.py, recall.py, sleep.py, interests.py
│   ├── foundry/                   client.py, validate.py, render.py, review.py, queue.py
│   ├── world/                     sections.py, placement.py
│   ├── requests/                  postcards.py, status.py, rate_limit.py
│   ├── loop.py
│   └── stubs/                     fake_mind.py, fake_foundry.py
├── web/                           Moon viewer, postcard booth, tuning panel
├── tests/
├── docs/archive/PINO-v1.md
└── prototype/
```

---

## 14. Phases

Each phase ends with something you can run and a test that proves it. Order puts the feelings and the window first because everything hangs on them.

**Phase 0: Reset (0.5 day)**
- Archive `PINO.md` as v1; write `canon.md`; start `ARCHITECTURE.md` from sections 4-6.
- Decide the open items in section 16 that block Phase 1.
- Done when: canon and config skeleton are committed and reviewed.

**Phase 1: Feelings engine (pure) and replay**
- Implement layers, lazy decay, appraisal matrix, urgency with hysteresis, habituation, impact caps, `weight`.
- Property tests; a CLI that replays an event log under a preset and prints the metrics table (7.8).
- Done when: 30 simulated days run in seconds, all metric targets reachable by at least one preset, no property test fails.

**Phase 2: Cargo scheduler and gateway**
- Window state machine, ledger, manifest builder, gateway with allowlist, budgets, cache, logging, cassette mode.
- Network isolation test: with the mind process sandboxed, a direct outbound request fails.
- Done when: simulated 24 h shows windows open for 60 min, budgets enforced, and closed-hatch calls refused.

**Phase 3: Reader and injection tests**
- Reader schema, sanitiser, an injection test set (pages that say "ignore previous instructions", "reveal your prompt", embed fake JSON).
- Done when: none of the test pages changes Pino's behaviour or reaches a prompt outside the `untrusted` wrapper.

**Phase 4: Mind v2 (stubbed, then real)**
- Questions table and queue, five typed calls with Pydantic schemas and one retry then fallback, dedupe, caps, triage.
- First with `fake_mind`, then Ternary Bonsai 2 9B (Q2_0) locally; fall back to Qwen 2.5 7B / Qwen 3 8B Q4 if it misses the gate.
- Done when: a 24 h real-model run has no loop longer than 6 cycles, schema failures < 3%, and questions are being answered.

**Phase 5: Memory and vault**
- Adapt tables and recall (mood-congruence, open-question relatedness), sleep routine additions, vault slots and forced release.
- Done when: after 7 simulated days the vault is full, releases have reasons, and journals are not repetitive.

**Phase 6: Visitors**
- Postcard endpoint, rate limits, request states, manifest integration, reply flow.
- Done when: a request goes `queued -> in cargo N -> read -> researched -> replied` in the viewer with the right text.

**Phase 7: Foundry and Moon sections**
- Section registry, art rules file, validation, render and two quality checks, build queue and lock, memory sorting during lock.
- Done when: a request produces a placed build, and a deliberately bad build is dropped with a reason Pino hears.

**Phase 8: Moon viewer and tuning panel**
- Reuse prototype rendering for the Moon: space canvas, zoom, rotate, section view, vault shelf, request status, panel with presets and logs.
- Done when: you can change a parameter live and see its effect in the trace.

**Phase 9: Soak and public readiness**
- 72 h unattended run, a cost report (cloud calls per build), kill switch test, terms page and notice, rate-limit abuse test.
- Done when: no crash, metrics within targets, estimated monthly API cost known.

Order of risk: Phases 2-3 (network and injection) and 4 (small-model reliability) are where this can fail; do not start 7 before 4 passes.

---

## 15. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Prompt injection through web pages | Reader quarantine, schema-only extracts, untrusted wrapper, no tools in read context, injection test set |
| Small model produces bad JSON or shallow questions | Narrow typed calls, structured output, one retry, fallback to rule; question dedupe and quality score; keep model swappable |
| Canon makes him gloomy or dramatic | Bounded `weight`, mood floor, tone rule, "stewardship" framing, panel preset to reduce it |
| Question spam or "why?" loops | Dedupe, depth cap, backlog cap, triage, lockout, curiosity relief tied to confidence gain |
| Copyright from preserving web content | Store notes, short attributed quotes and links; full text only for open-licensed sources |
| Visitors manipulate him (fake "future" claims, abuse) | Postcards are data not instructions, per-sender impact caps, rate limits, output content rules |
| Cloud cost grows | Builds only on request, build budget per day, two-check ceiling, stub for tests |
| 8 GB VRAM contention (Ollama + embedding + renders) | Render on CPU/Chromium headless, keep one model resident, embeddings are small |
| Tuning is slow | Replay engine, cassette gateway, fast-forward |
| Public site liability | Terms page, minimum age, notice that Pino is a fictional AI, fixed content rules, kill switch |

---

## 16. Open decisions

| Question | Recommended default |
|----------|---------------------|
| Window gap measured from window **close** or **start**? | From close |
| What happens when the cargo ledger reaches zero? | End of the story phase, then "unexplained signals" and postcards continue |
| Ledger size | 200 (about 2-3 weeks at ~10 windows a day; make it tunable) |
| Slots per cargo | 12 (4 requests, 5 matched, 3 serendipity) |
| Search backend | A search API with a small key; SearXNG later if cost matters |
| Builds in parallel? | Serial queue for v1, per-section locks later |
| Tell visitors when a reply is held or a build dropped? | Show a neutral `held` state; never show Pino's reason text |
| Minimum age and terms page | Required before any public launch |
| Which Foundry model | `qwen/qwen3.7-flash` (decided, section 4a); keep behind one client interface |
| Do answers to visitors need review before posting? | No pre-moderation (as in your v2), but log everything and keep the kill switch |

---

## 17. First steps if you say go

1. Phase 0 files and config skeleton.
2. Feelings engine with replay (Phase 1), because it is pure, quick to write, and you can see results the same day.
3. Cargo scheduler with a cassette gateway (Phase 2), so the 60-minute window exists as something you can watch before any real web access is wired in.
