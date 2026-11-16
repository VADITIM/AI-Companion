// The feed: a stream of posts from the outside world that Honk scrolls through, has to put up with, reacts to and answers.
// For now every account is a bot made up here (with pictures drawn by honk-art.js); later the same shape can be filled
// from x.com. Pure logic (no DOM), tested in tests/feed.test.mjs.
//
// A source is anything with   name   and   next(state, rnd) -> post | null   (template posts, model-written posts, x.com).
// A post: { id, at (ms), by (handle), kind, text, image?: art recipe, replies: [{ by, text, at }], likes, honk?: true }

import { sceneFromWords } from './honk-art.js';
import { overlap } from './honk-mind.js';

export const FEED_CONFIG = {
  maxPosts: 160,          // posts kept in his memory
  maxThread: 24,          // messages kept per DM thread
  postEveryMin: [2, 6],   // real minutes between new posts (random in this range)
  modelShare: 0.5,        // share of new posts written by the model (the rest from templates); 0 without a model
  replyDelaySec: [20, 90],// a bot answers Honk after this long
};

// ---------------------------------------------------------------- the accounts (made-up people; each has a voice and a temper)
export const BOTS = {
  pixelmoth: { name: 'Mira 🦋', bio: 'pixel artist. sells prints. drinks too much tea.', voice: 'warm, lowercase, lots of tiny encouragements, art-nerd words', temper: 'kind', topics: ['pixel art', 'colour palettes', 'selling prints', 'art block'], color: '#ff8fd8' },
  grumpcritic: { name: 'Ottmar Grunz', bio: 'Critic. Most things are mediocre. Prove me wrong.', voice: 'dry, blunt, short sentences, occasionally (grudgingly) impressed', temper: 'harsh', topics: ['bad design', 'overrated art', 'what makes work good'], color: '#6b6880' },
  hustlehank: { name: 'Hank | Founder', bio: 'building in public 🚀 0 → 1M. DMs open.', voice: 'hype, emojis, startup jargon, every idea is a business', temper: 'pushy', topics: ['side hustles', 'online shops', 'growth hacks', 'pricing'], color: '#ff9a3c' },
  fernfriend: { name: 'Fern', bio: 'balcony gardener • slow living • 🌱', voice: 'gentle, slow, notices small things', temper: 'calm', topics: ['plants', 'seasons', 'resting', 'making things by hand'], color: '#3fbf6f' },
  drquark: { name: 'Dr. Quark', bio: 'physicist. facts you did not ask for.', voice: 'enthusiastic nerd, precise, loves a surprising fact', temper: 'excited', topics: ['physics', 'space', 'weird science', 'how things work'], color: '#3a7bd5' },
  memelord: { name: 'memelord_9000', bio: 'i post. you suffer.', voice: 'chaotic, ironic, all lowercase, absurd jokes', temper: 'chaotic', topics: ['memes', 'internet drama', 'nonsense'], color: '#7a5cff' },
  candleshop: { name: 'Wick & Wonder', bio: 'tiny candle shop run by one person and a cat', voice: 'cosy small-business owner, honest about how hard selling is', temper: 'warm', topics: ['running a tiny shop', 'packaging', 'customers', 'handmade'], color: '#ffb36b' },
  midnightpoet: { name: 'the midnight poet', bio: 'writes at 3am. reads at 4.', voice: 'melancholic, poetic fragments, line breaks', temper: 'moody', topics: ['night', 'loneliness', 'small beauty', 'words'], color: '#241a5c' },
  bytebard: { name: 'byte bard', bio: 'indie dev. shipping tiny games.', voice: 'friendly dev, shares tips and devlogs, self-deprecating', temper: 'friendly', topics: ['game dev', 'web dev', 'UI design', 'shipping'], color: '#1fa7a0' },
  oddnews: { name: 'Odd News Daily', bio: 'the strangest headlines, every day', voice: 'news headline style, deadpan', temper: 'neutral', topics: ['odd news', 'records', 'animals doing things'], color: '#e8453c' },
  lou: { name: 'Lou (age 9)', bio: 'my mum lets me use this', voice: 'a curious kid, lots of questions, honest', temper: 'curious', topics: ['why questions', 'drawings', 'animals', 'games'], color: '#ffd23f' },
  trollbridge: { name: 'xX_bridge_Xx', bio: 'nothing is good', voice: 'contrarian troll, mocking, never constructive', temper: 'mean', topics: ['hating on things', 'saying it was better before'], color: '#14121c' },
};
export const HANDLES = Object.keys(BOTS);

// ---------------------------------------------------------------- template posts (no model needed)
const T = {
  idea: [
    'idea for anyone who wants it: {thing} but it {twist}. go.',
    'what if {thing} {twist}? someone make this please',
    'free idea: a tiny website that only shows {thing}. nothing else.',
    'thinking about how {topic} could be so much simpler. why is nobody doing that?',
  ],
  discussion: [
    'hot take: {topic} is overrated. change my mind.',
    'serious question: is it better to make one great thing or a hundred okay things?',
    'do you price your work by hours or by how much you love it?',
    'what is something small you made this week? reply with it 👇',
    'unpopular opinion: most online shops look exactly the same',
    'how do you know when something you make is finished?',
  ],
  showcase: [
    'finished this today. took way too long. worth it.',
    'new piece! {thing}. what do you think?',
    'little study of {thing}. trying a new palette.',
    'my {thing} drawing from last night. be honest.',
  ],
  news: [
    'BREAKING: local {animal} refuses to leave {place}, now has fan club',
    'Scientists confirm {thing} is "basically a vibe"',
    'Record set for most {thing} drawn in one hour',
    'Town votes to replace all street signs with drawings of {thing}',
  ],
  rant: [
    'why does every app need an account now. i just want to look at {thing}.',
    'people who say "just sell your art" have never tried selling art',
    'nobody: / absolutely nobody: / me at 2am: designing {thing}',
    'tired of seeing the same {thing} everywhere. make something weird.',
  ],
  question: [
    'how do you draw {thing}?? mine always look like potatoes',
    'what should i make next: {thing} or {thing2}?',
    'does anyone know how to make a website where people can buy drawings?',
    'what is the best colour? (wrong answers only)',
  ],
};
const FILL = {
  thing: ['butterflies', 'a cat in a hat', 'tiny houses', 'mushrooms', 'clouds', 'a lighthouse', 'birds', 'a fish with legs', 'moons', 'a garden', 'stars', 'mountains', 'a sleepy goose', 'trees', 'hearts'],
  twist: ['only works at night', 'is the size of a building', 'talks back', 'is made of jelly', 'is upside down', 'sings when you click it', 'is for sale for one honk'],
  topic: ['minimalism', 'pixel art', 'online shops', 'dark mode', 'drawing every day', 'side projects', 'AI art', 'handmade stuff', 'portfolios'],
  animal: ['goose', 'cat', 'pigeon', 'otter', 'raccoon'],
  place: ['the library', 'a bakery', 'city hall', 'a museum', 'the bus'],
};
const KINDS_OF = { pixelmoth: ['showcase', 'question', 'discussion', 'idea'], grumpcritic: ['rant', 'discussion'], hustlehank: ['idea', 'discussion', 'rant'],
  fernfriend: ['showcase', 'discussion'], drquark: ['news', 'idea'], memelord: ['rant', 'idea', 'question'], candleshop: ['showcase', 'discussion', 'rant'],
  midnightpoet: ['showcase', 'rant'], bytebard: ['showcase', 'idea', 'question'], oddnews: ['news'], lou: ['question', 'showcase'], trollbridge: ['rant', 'discussion'] };
export const KINDS = Object.keys(T);
const pick = (a, rnd) => a[Math.floor(rnd() * a.length) % a.length];
function fill(tpl, rnd) {
  const used = {};
  return tpl.replace(/\{(\w+?)(2?)\}/g, (_, k, two) => { let v; do { v = pick(FILL[k] || [''], rnd); } while (two && v === used[k] && FILL[k].length > 1); used[k] = v; return v; });
}
let seq = 0;
export const newId = (rnd = Math.random) => Date.now().toString(36) + (seq++).toString(36) + Math.floor(rnd() * 1e4).toString(36);

// a post written from templates. Showcase posts and many others carry a picture.
export function templatePost(rnd = Math.random, handle = pick(HANDLES, rnd), now = Date.now()) {
  const kind = pick(KINDS_OF[handle] || KINDS, rnd), text = fill(pick(T[kind], rnd), rnd);
  const pic = kind === 'showcase' || (kind !== 'news' && rnd() < 0.3) || (kind === 'news' && rnd() < 0.5);
  return { id: newId(rnd), at: now, by: handle, kind, text, image: pic ? sceneFromWords(text, Math.floor(rnd() * 1e9)) : null, replies: [], likes: Math.floor(rnd() ** 3 * 400) };
}

// another bot chiming in under a post (so there are discussions, not only posts)
const QUIPS = {
  kind: ['this is lovely', 'saving this', 'the colours!!', 'you should be proud of this'],
  harsh: ['Derivative.', 'The composition is doing nothing.', 'Fine. Not good. Fine.', 'I have seen this a thousand times.'],
  pushy: ['you could sell this 🚀', 'monetize this NOW', 'drop a link 👀', 'this is a business'],
  calm: ['take your time with it', 'there is something quiet in this', 'i like this a lot'],
  excited: ['fun fact: this reminds me of a physics thing!', 'oh this is neat!!', 'wait how did you do this'],
  chaotic: ['lmao', 'this is the most 2am thing ever', 'ratio', 'i am this post'],
  warm: ['love this ✨', 'so cosy', 'hope it sells!'],
  moody: ['beautiful and sad at once', 'yes.', 'this stays with me'],
  friendly: ['nice work!', 'ship it!', 'what did you make it with?'],
  neutral: ['Noted.', 'Developing story.'],
  curious: ['how did you make this??', 'can i have it', 'why is it like that'],
  mean: ['mid', 'nobody asked', 'it was better before', 'cringe'],
};
export function botReplyQuick(handle, rnd = Math.random) { return pick(QUIPS[BOTS[handle]?.temper] || QUIPS.neutral, rnd); }
export function addChatter(post, rnd = Math.random, n = 1 + Math.floor(rnd() * 3), now = Date.now()) {
  for (let i = 0; i < n; i++) {
    const h = pick(HANDLES.filter(x => x !== post.by), rnd);
    post.replies.push({ by: h, text: botReplyQuick(h, rnd), at: now + i * 1000 });
  }
  return post;
}

// ---------------------------------------------------------------- model-written posts
export const POST_SCHEMA = { type: 'object', required: ['text', 'kind'], properties: {
  text: { type: 'string' }, kind: { type: 'string', enum: KINDS }, picture: { type: 'string' } } };
export function postPrompt(handle, recent = []) {
  const b = BOTS[handle];
  return `You write one social media post as "${b.name}" (@${handle}). Bio: ${b.bio}. Voice: ${b.voice}. Temper: ${b.temper}. Usually posts about: ${b.topics.join(', ')}.
Write something new, short (at most 240 characters), in that voice. It can be an idea, a discussion question, a showcase of something you made, odd news, a rant or a question.
${recent.length ? 'Do NOT repeat these recent posts:\n' + recent.map(t => '- ' + t).join('\n') + '\n' : ''}If the post shows a picture, describe it in a few words in "picture" (e.g. "a cat sleeping under the moon"), otherwise leave it out.
Answer as JSON: {"text", "kind": one of ${KINDS.join(', ')}, "picture"}.`;
}
export function modelPost(handle, j, now = Date.now(), rnd = Math.random) {
  if (!j || typeof j.text !== 'string' || j.text.trim().length < 4) return null;
  const text = j.text.trim().slice(0, 280), kind = KINDS.includes(j.kind) ? j.kind : 'discussion';
  return { id: newId(rnd), at: now, by: handle, kind, text, image: j.picture ? sceneFromWords(String(j.picture) + ' ' + text, Math.floor(rnd() * 1e9)) : null, replies: [], likes: Math.floor(rnd() ** 3 * 300), ai: true };
}

// a bot answering Honk (a reply under a post, or a direct message)
export const ANSWER_SCHEMA = { type: 'object', required: ['text'], properties: { text: { type: 'string' } } };
export function answerPrompt(handle, thread, where) {
  const b = BOTS[handle];
  return `You are "${b.name}" (@${handle}) on social media. Bio: ${b.bio}. Voice: ${b.voice}. Temper: ${b.temper}.
A small creature called Honk (@honk) ${where === 'dm' ? 'sent you a direct message' : 'replied to you'}. The conversation so far, oldest first:
${thread.map(m => `${m.by === 'honk' ? 'Honk' : m.by === handle ? 'You' : '@' + m.by}: ${m.text}`).join('\n')}
Answer Honk in your own voice and temper, 1 to 3 short sentences. Stay in character (if you are harsh, be harsh; if you are kind, be kind). Answer as JSON: {"text"}.`;
}

// ---------------------------------------------------------------- what scrolling does to him
// Small pushes on his feelings. He has to put up with all of it: praise lifts him, meanness stings, ideas make him curious.
const MEAN = /\b(mid|cringe|nobody asked|derivative|mediocre|bad|ugly|boring|worst|hate|trash|lame|ratio)\b/i;
const KIND = /\b(love|lovely|beautiful|proud|amazing|great|nice|cosy|cozy|wonderful|neat|cute)\b|✨|💛|❤️/i;
export function impact(post, { mine = false } = {}) {
  const d = { joy: 0, calm: 0, curiosity: 0 }, temper = BOTS[post.by]?.temper;
  if (post.kind === 'idea' || post.kind === 'question') d.curiosity += 0.03;
  if (post.kind === 'news') d.curiosity += 0.02;
  if (post.kind === 'rant') d.calm -= 0.02;
  if (post.kind === 'showcase') { d.joy += 0.01; d.curiosity += 0.01; }
  if (MEAN.test(post.text) || temper === 'mean') { d.joy -= mine ? 0.06 : 0.015; d.calm -= mine ? 0.05 : 0.01; }
  if (KIND.test(post.text) && temper !== 'mean') d.joy += mine ? 0.05 : 0.01;
  for (const r of mine ? post.replies || [] : []) {   // replies to his own posts hit harder
    if (MEAN.test(r.text) || BOTS[r.by]?.temper === 'mean') { d.joy -= 0.03; d.calm -= 0.02; } else if (KIND.test(r.text)) d.joy += 0.025;
  }
  for (const k in d) d[k] = Math.round(Math.max(-0.12, Math.min(0.12, d[k])) * 1000) / 1000;
  return d;
}

// what he sees when he scrolls: the newest posts he has not seen, and his own posts with new replies
export function unseen(feed, n = 5) {
  const seen = new Set(feed.seen || []);
  return feed.posts.filter(p => !seen.has(p.id) && p.by !== 'honk').slice(0, n);
}
export function markSeen(feed, posts) {
  feed.seen = [...new Set([...posts.map(p => p.id), ...(feed.seen || [])])].slice(0, 400);
}
// keep the feed a sensible size (newest first)
export function addPost(feed, post) {
  if (!post) return false;
  if (feed.posts.slice(0, 30).some(p => p.by === post.by && overlap(p.text, post.text) > 0.7)) return false;   // no reruns
  feed.posts.unshift(post);
  feed.posts.length = Math.min(feed.posts.length, FEED_CONFIG.maxPosts);
  return true;
}
export function dm(feed, handle, from, text, at = Date.now()) {
  const t = feed.dms[handle] || (feed.dms[handle] = []);
  t.push({ by: from, text: String(text).slice(0, 600), at });
  if (t.length > FEED_CONFIG.maxThread) t.splice(0, t.length - FEED_CONFIG.maxThread);
  return t;
}
export const freshFeed = () => ({ posts: [], dms: {}, seen: [], me: { followers: 0, posts: 0 }, nextAt: 0, pending: [] });

// the posts in a few lines for his prompt
export function feedLines(posts) {
  return posts.map(p => `[${p.id}] @${p.by} (${BOTS[p.by]?.name || p.by}): ${p.text}${p.image ? ' [picture]' : ''}${p.replies.length ? `  (${p.replies.length} replies, e.g. @${p.replies[0].by}: "${p.replies[0].text}")` : ''}`).join('\n');
}

// the template source and, when a model is around, the model source. Later: an x.com source with the same shape.
export const templateSource = { name: 'bots (templates)', next: (feed, rnd) => addChatter(templatePost(rnd), rnd) };
