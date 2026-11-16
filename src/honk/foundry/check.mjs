// Checks a build recipe with the same code the world draws it with (World/honk-build.js).
// stdin: {"recipe": {...}, "name": "...", "maxParts": 40}   stdout: {"ok", "hard": [...], "soft": [...], "recipe": {parts: [...]}, "radius"}
import * as B from '../../../World/honk-build.js';

const COLORS = ['navy', 'indigo', 'violet', 'periwinkle', 'lavender', 'cream', 'white', 'pink', 'magenta', 'plum', 'teal', 'mint', 'yellow',
  'orange', 'red', 'lime', 'green', 'stone', 'dark', 'wood', 'bark'];
let text = '';
for await (const chunk of process.stdin) text += chunk;
const input = JSON.parse(text);
const env = { PAL: Object.fromEntries(COLORS.map(c => [c, 1])), MATERIALS: { plain: 1 }, USES: ['art'], useOfName: () => 'art', matOfColor: () => 'plain', maxParts: input.maxParts || 40 };
const raw = { ...input.recipe, kit: undefined, use: 'art' };
(raw.parts || []).forEach(p => { if (p && typeof p === 'object') delete p.text; });   // no writing on builds
const clean = B.cleanRecipe(raw, input.name || '', env);
if (!clean) console.log(JSON.stringify({ ok: false, hard: ['it has no usable parts'], soft: [] }));
else {
  const { hard, soft } = B.checkRecipe(clean);
  const parts = clean.parts.map(p => ({ shape: p.shape, pos: p.pos.map(v => Math.round(v * 1000) / 1000), scale: p.scale, rot: p.rot, color: p.color, glow: p.glow }));
  const height = Math.max(...clean.parts.map(p => B.partBox(p).max[1]));
  if (height > 8.5) hard.push('it is taller than 8; make it lower');
  console.log(JSON.stringify({ ok: !hard.length, hard, soft, recipe: { parts }, radius: B.footprint(clean), height }));
}
