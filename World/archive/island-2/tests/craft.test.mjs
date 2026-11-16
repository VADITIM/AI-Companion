// Tests for Honk's drawing (honk-art.js), design sense (honk-design.js), feed (honk-feed.js) and purpose/voice (honk-mind.js).
// Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as Art from '../honk-art.js';
import * as D from '../honk-design.js';
import * as F from '../honk-feed.js';
import * as Mind from '../honk-mind.js';

const seeded = (s = 7) => () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);

test('a butterfly recipe becomes a proper SVG with two mirrored wings', () => {
  const art = Art.cleanArt({ title: 'Spring', palette: ['#ffd6e8', '#4b47d6', '#ffd23f'], background: { colors: ['p0', '#ffffff'] },
    layers: [{ motif: 'butterflies', x: 50, y: 45, size: 50, color: 'p1', accent: 'p2' }, { shape: 'circle', x: 20, y: 20, r: 4, color: 'yellow', mirror: 'x' }] });
  assert.equal(art.layers[0].motif, 'butterfly');
  const ex = Art.expand(art);
  assert.equal(ex.length, 3);                                     // the circle got a mirrored twin
  assert.deepEqual(ex.slice(1).map(l => l.x), [20, 80]);
  const svg = Art.toSVG(art);
  assert.match(svg, /^<svg[^>]+viewBox="0 0 100 100"/);
  assert.equal((svg.match(/<ellipse/g) || []).length >= 5, true); // four wings and a body
  assert.doesNotMatch(svg, /NaN|undefined/);
});

test('art recipes are cleaned: junk layers dropped, numbers clamped, nothing usable -> null', () => {
  assert.equal(Art.cleanArt({ layers: [{ shape: 'spaceship' }, { motif: 'dragon' }] }), null);
  const a = Art.cleanArt({ layers: [{ motif: 'cat', x: 9999, size: -5, color: 'not a colour' }, { shape: 'poly', points: [[1, 1]] }, { shape: 'text', text: '<b>hi</b>', x: 50, y: 90 }] });
  assert.equal(a.layers.length, 2);
  assert.equal(a.layers[0].x, 110); assert.equal(a.layers[0].size, 4);
  assert.match(Art.toSVG(a), /&lt;b&gt;hi/);                      // text is escaped
});

test('critique catches an empty, tiny or invisible picture and passes a good one', () => {
  const tiny = Art.cleanArt({ background: { colors: ['#ffffff'] }, layers: [{ motif: 'flower', x: 5, y: 5, size: 6, color: '#fffefe' }] });
  const c = Art.critiqueArt(tiny);
  assert.ok(c.some(x => /almost empty/.test(x)) && c.some(x => /tiny/.test(x)) && c.some(x => /disappears/.test(x)));
  const good = Art.sceneFromWords('a cat sleeping under the moon', 42);
  assert.equal(good.layers[0].motif, 'cat');
  assert.deepEqual(Art.critiqueArt(good).filter(x => /disappears|tiny|no clear subject/.test(x)), []);
});

test('design lint flags placeholder text, no viewport and messy pages, and passes a clean one', () => {
  const bad = '<html><body><div class="card"><button>Buy</button><p>Lorem ipsum dolor sit amet</p><p>Product 1</p><a href="#">a</a><a href="#">b</a><a href="#">c</a></div></body></html>';
  const issues = D.designLint(bad);
  for (const re of [/title/, /viewport/, /placeholder/, /<h1>/, /hover/, /go nowhere/]) assert.ok(issues.some(i => re.test(i)), re);
  const good = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Honk's Cats</title>
  <style>body{font-family:system-ui;color:#1d1b2e} .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))} button:hover{transform:translateY(-2px)}</style></head>
  <body><main><h1>Honk's cat prints</h1><p>Six sleepy cats I drew this week. Message me if you want one.</p><div class="grid"><button>Ask about Moon Cat</button></div></main></body></html>`;
  assert.deepEqual(D.designLint(good), []);
});

test('a theme Honk picks always stays readable', () => {
  const { theme, fixes } = D.checkTheme({ bg: '#ffff00', panel: '#ffffff', text: '#fafafa', accent: '#ffffee', radius: 99, font: 'comic' });
  assert.ok(D.contrast(theme.text, theme.panel) >= 7);
  assert.ok(D.contrast(theme.accent, theme.panel) >= 2.2);
  assert.equal(theme.radius, 28); assert.equal(theme.font, D.DEFAULT_THEME.font);
  assert.ok(fixes.length >= 2);
  const dark = D.checkTheme({ bg: '#101018', panel: '#1b1a2b', text: '#f0eeff', muted: '#a8a4c8', accent: '#8f88ff' });
  assert.deepEqual(dark.fixes, []);
  assert.match(D.themeCSS(dark.theme), /--panel:#1b1a2b/);
});

test('apps must point at a real program', () => {
  assert.ok(D.cleanApp({ program: 'nope' }, {}).error);
  const { app } = D.cleanApp({ program: 'cat-shop', name: 'A very long shop name that goes on', icon: '🛍️', place: 'nowhere' }, { 'cat-shop': { title: 'Cat shop' } });
  assert.equal(app.slug, 'cat-shop'); assert.equal(app.place, 'dock'); assert.equal(app.name.length, 22);
});

test('template posts come with pictures, chatter, and no exact reruns', () => {
  const rnd = seeded(3), feed = F.freshFeed();
  let added = 0;
  for (let i = 0; i < 40; i++) added += F.addPost(feed, F.templateSource.next(feed, rnd)) ? 1 : 0;
  assert.ok(added > 20);
  assert.ok(feed.posts.some(p => p.image && p.image.layers.length));
  assert.ok(feed.posts.every(p => p.replies.length >= 1 && p.replies.every(r => r.by !== p.by)));
  assert.ok(new Set(feed.posts.map(p => p.by)).size > 5);
  assert.equal(F.addPost(feed, { ...feed.posts[0], id: 'x' }), false);
});

test('mean replies to his own post sting more than kind ones lift him', () => {
  const mine = { by: 'honk', kind: 'showcase', text: 'my cat drawing', replies: [{ by: 'trollbridge', text: 'mid' }, { by: 'grumpcritic', text: 'Derivative.' }] };
  const d = F.impact(mine, { mine: true });
  assert.ok(d.joy < 0 && d.calm < 0);
  const kind = F.impact({ by: 'pixelmoth', kind: 'showcase', text: 'this is lovely', replies: [] });
  assert.ok(kind.joy > 0);
  assert.ok(F.impact({ by: 'drquark', kind: 'idea', text: 'what if', replies: [] }).curiosity > 0);
});

test('model posts are checked; DMs are kept short', () => {
  assert.equal(F.modelPost('lou', { text: '' }), null);
  const p = F.modelPost('lou', { text: 'how do you draw a cat??', kind: 'nonsense', picture: 'a wobbly cat' });
  assert.equal(p.kind, 'discussion'); assert.equal(p.image.layers[0].motif, 'cat');
  const feed = F.freshFeed();
  for (let i = 0; i < 30; i++) F.dm(feed, 'lou', i % 2 ? 'honk' : 'lou', 'hi ' + i);
  assert.equal(feed.dms.lou.length, F.FEED_CONFIG.maxThread);
  assert.match(F.answerPrompt('grumpcritic', feed.dms.lou.slice(-2), 'dm'), /Temper: harsh/);
});

test('openings: a collection becomes a gallery, then a shop, then an app', () => {
  const works = n => Array.from({ length: n }, (_, i) => ({ kind: 'art', collection: 'sleepy cats', title: 'cat ' + i }));
  assert.match(Mind.openings({ works: [] })[0], /not made a series/);
  assert.match(Mind.openings({ works: works(2) })[0], /2 pieces.*few more/);
  assert.match(Mind.openings({ works: works(5) })[0], /gallery page/);
  const gallery = { 'cat-gallery': { slug: 'cat-gallery', title: 'Cats', kind: 'site', shows: 'sleepy cats', check: 'runs without errors' } };
  const o = Mind.openings({ works: works(7), programs: gallery });
  assert.ok(o.some(x => /shop page/.test(x)) && o.some(x => /become an app/.test(x)));
  assert.ok(!Mind.openings({ works: works(7), programs: gallery, apps: [{ slug: 'cat-gallery' }] }).some(x => /become an app/.test(x)));
});

test('his voice is his own: cleaned, coloured by mood, nothing about the viewer', () => {
  const v = Mind.cleanVoice({ style: 'clipped, dry, lots of dashes', temper: 'sharp', quirks: ['signs off with "— H."', 'the human is watching me', ''] });
  assert.equal(v.style, 'clipped, dry, lots of dashes'); assert.deepEqual(v.quirks, ['signs off with "— H."']);
  assert.equal(Mind.cleanVoice(null).style, Mind.VOICE_DEFAULT.style);
  assert.match(Mind.temperNow({ joy: 0.2, calm: 0.2, energy: 0.8 }, v), /sharp; right now a bit grumpy.*prickly/);
});
