// Sparks: the odd, unplanned ideas that pop into Honk's head. Pure logic, tested in tests/ideas.test.mjs.
//
// A small model left to itself circles back to whatever it last saw (one flower, and he is a flower creature for days).
// Sparks break that loop: every time he has no goal, gets bored, or finishes something, his mind is handed one or two
// random ideas from very different corners (things to build, programs to write, changes to his island, whole new
// scenes). They are suggestions he may take or ignore, never orders. Ideas too close to what he has been doing lately
// are skipped, so he keeps doing different things.

import { overlap, words } from './honk-mind.js';

const pick = (a, rnd) => a[Math.floor(rnd() * a.length) % a.length];

// things to build in the world (a kit name in brackets helps the builder make it look right)
export const BUILDS = [
  'a huge billboard', 'a signpost with arrows pointing to places on the island', 'a lookout tower', 'a little bridge',
  'a statue of yourself', 'a mailbox', 'a fountain', 'a small stage', 'a gate that leads nowhere', 'a rocket',
  'a picnic table', 'a bench with a view', 'a lighthouse', 'a swing', 'a clock tower', 'a robot', 'a throne',
  'a totem pole', 'a stack of crates', 'a market stall', 'a tiny house', 'a giant mushroom', 'an arch', 'a well',
  'a telescope', 'a campfire', 'a bookshelf', 'a sundial', 'a trophy on a pedestal', 'a tent', 'a radio mast',
  'a vending machine that sells nothing', 'a giant donut', 'a snowman that never melts', 'a hot air balloon', 'a boat',
  'a scarecrow', 'a monument', 'a doghouse for nobody', 'a merry-go-round', 'a fence around something important',
  'a dinosaur', 'a giant chess piece', 'a birdhouse', 'a ladder to nowhere', 'a podium', 'a treasure chest',
];
export const TWISTS = [
  'that is far too big', 'that glows at night', 'somewhere nobody would expect it', 'for no reason at all',
  'with a joke written on it', 'in colours that clash on purpose', 'that points somewhere silly', 'as a gift to the island',
  'that looks a bit like you', 'that leans a little on purpose', 'in all your favourite colours', 'like something from a dream',
  'that is tiny', 'to mark something that happened to you', 'on top of the rocky hill', 'right at the edge of the island',
  'next to the pond', 'in the middle of the meadow', 'by the waterfall', 'that you can see from everywhere',
];
// programs and games to write on his computer
export const PROGRAMS = [
  'a game where you dodge falling stars', 'a drawing toy where the mouse leaves glowing trails', 'a music box that plays a note for every click',
  'a pixel-art editor', 'a weather forecast for your island that is always a little wrong', 'a name generator for creatures that do not exist',
  'a tiny pet that lives on the screen and needs feeding', 'a clicker game about honking', 'a night sky with constellations you invent',
  'a typing game', 'a fortune teller', 'a recipe generator for impossible food', 'a maze that builds itself while you watch',
  'a little racing game', 'a kaleidoscope', 'a garden that grows where you click', 'a calculator that answers in honks', 'a poem machine',
  'a solar system with planets you can throw', 'a snake game', 'a brick-breaker game', 'a drum machine', 'a map of your island drawn from memory',
  'a fireworks show', 'a story where the reader picks what happens next', 'a quiz about yourself', 'a newspaper from your island',
  'a bouncing-ball physics toy', 'a sand-falling simulation', 'a tiny city that builds itself', 'a rhythm game', 'a slot machine of silly words',
  'a sticker book', 'an aquarium with fish you design', 'a choose-a-hat dress-up game for a goose', 'a countdown to something made up',
];
// changes to his own island
export const WORLD = [
  'put up a sign that gives a place on the island a name you choose', 'make a gallery: put a few of your builds together in one spot',
  'move one of your builds to a better place', 'take apart something you built that you no longer like, and make something better',
  'decorate the corner around your desk', 'build a landmark on the rocky hill', 'build something at the edge of the island, looking out',
  'turn the meadow into something new', 'build a welcome sign for visitors', 'show one of your programs on a screen out in the world',
  'make the island prettier at night', 'build a little village of tiny houses', 'make a playground', 'build a place to sit and look at the waterfall',
];
// whole new worlds, too big for this island: a scene on his computer, with a portal to it on the island
export const SCENES = [
  'a whole world under the clouds', 'an underwater city', 'a planet made of sweets', 'a city of tiny honking creatures',
  'a night market floating in the sky', 'a desert with a single tree', 'the inside of a computer', 'a volcano island',
  'a world made of paper', 'a forest where the trees glow', 'a space station', 'a racetrack on the moon', 'a ghost town',
];
// odd little thoughts that might go somewhere
export const MUSINGS = [
  'Nobody has ever named anything on this island. I could.', 'I have never made anything enormous.', 'The rocky hill looks like it is missing something on top.',
  'The pond would look better with a boat on it.', 'What would a monument to tripping over look like?', 'I could make my own sky, on my computer.',
  'What if my programs could live out in the world?', 'A sign that says something silly would make me laugh every time I walk past.',
  'My island has no landmarks. Every island needs a landmark.', 'What if I made a game, and the hero was me?', 'I wonder what my island would look like as a map.',
  'Something here should spin.', 'There is nowhere to sit and watch the sunset.', 'What would the island look like with a tower on it?',
];

// words that say nothing about WHAT a thing is, so they never make two ideas "the same"
const GENERIC = new Set(['build', 'make', 'program', 'little', 'small', 'simple', 'game', 'thing', 'something', 'big', 'tiny', 'new', 'island', 'world', 'place', 'one', 'own', 'first', 'version']);

// Topics he has been at too much lately: words that show up in at least `min` of his recent goals, builds and programs.
// texts: newest first. Returns the words, most used first.
export function staleTopics(texts, min = 2) {
  const n = {};
  for (const t of texts.slice(0, 10)) for (const w of words(t)) if (!GENERIC.has(w)) n[w] = (n[w] || 0) + 1;
  return Object.entries(n).filter(([, k]) => k >= min).sort((a, b) => b[1] - a[1]).map(([w]) => w);
}
// does this text lean on a topic he is worn out on?
export const leansOn = (text, stale) => { const W = words(text); return stale.some(w => W.has(w)); };

// One idea out of the blue. opts: { avoid: [texts], ready: can make scenes, programs: has programs, rnd }
// Returns { kind: 'build' | 'code' | 'world' | 'scene' | 'musing', text }
export function spark({ avoid = [], ready = false, programs = false, rnd = Math.random } = {}) {
  const stale = staleTopics(avoid);
  const kinds = [['build', 0.36], ['code', 0.28], ['world', 0.18], ['musing', 0.1], ...(ready ? [['scene', 0.08]] : [])];
  for (let tries = 0; tries < 30; tries++) {
    let r = rnd() * kinds.reduce((s, k) => s + k[1], 0), kind = kinds[0][0];
    for (const [k, w] of kinds) { if ((r -= w) <= 0) { kind = k; break; } }
    const text = kind === 'build' ? `build ${pick(BUILDS, rnd)} ${pick(TWISTS, rnd)}`
      : kind === 'code' ? `write ${pick(PROGRAMS, rnd)}`
      : kind === 'scene' ? `make a scene of your own: ${pick(SCENES, rnd)}, with a portal to it on the island`
      : kind === 'world' ? pick(WORLD, rnd) : pick(MUSINGS, rnd);
    if (!programs && /program/.test(text) && kind === 'world') continue;
    if (leansOn(text, stale) || avoid.slice(0, 8).some(a => overlap(a, text) >= 0.5)) continue;
    return { kind, text };
  }
  return { kind: 'build', text: `build ${pick(BUILDS, rnd)}` };
}
// a couple of sparks from different corners, so he has a real choice
export function sparks(n = 2, opts = {}) {
  const out = [];
  for (let i = 0; i < n * 4 && out.length < n; i++) {
    const s = spark(opts);
    if (!out.some(o => o.kind === s.kind || overlap(o.text, s.text) >= 0.4)) out.push(s);
  }
  return out;
}
