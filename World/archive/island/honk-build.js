// How Honk's builds are made: turns the JSON recipe a model writes into clean parts, and checks them.
// Pure logic (no three.js), tested in tests/. The model never has to do coordinate maths for most of it:
//  - a part may say where it goes relative to an earlier part (named by its "id"):  "on": "seat", "side": "top", "off": [dx, dz]
//  - a part may repeat itself:  "mirror": "x" | "z" | "xz"  (across the middle of the build),  "ring": 2..12 (around the up axis)
// Parts that do not name an earlier part use "pos" as before, so old saved recipes still work.

export const SHAPES = ['box', 'rbox', 'sphere', 'dome', 'cylinder', 'taper', 'cone', 'pyramid', 'wedge', 'torus'];
export const SIDES = ['top', 'bottom', 'left', 'right', 'front', 'back'];   // right = +x, front = +z, back = -z
export const MIRRORS = ['x', 'z', 'xz'];
// how far each unit shape reaches from its centre (full size, before scaling)
const EXTENT = { torus: [1, 1, 0.3] };
const ext = shape => EXTENT[shape] || [1, 1, 1];

const D2R = Math.PI / 180, R2D = 180 / Math.PI;
const clampN = (x, lo, hi, d) => { x = Number(x); return Number.isFinite(x) ? Math.min(hi, Math.max(lo, x)) : d; };
const v3 = (a, lo, hi, d) => [0, 1, 2].map(i => clampN(a?.[i], lo, hi, d));

// rotation matrices, three.js conventions (Euler XYZ, column vectors)
const mul = (a, b) => a.map((r, i) => [0, 1, 2].map(j => r[0] * b[0][j] + r[1] * b[1][j] + r[2] * b[2][j]));
const Rx = t => { const c = Math.cos(t), s = Math.sin(t); return [[1, 0, 0], [0, c, -s], [0, s, c]]; };
const Ry = t => { const c = Math.cos(t), s = Math.sin(t); return [[c, 0, s], [0, 1, 0], [-s, 0, c]]; };
const Rz = t => { const c = Math.cos(t), s = Math.sin(t); return [[c, -s, 0], [s, c, 0], [0, 0, 1]]; };
const eulerMat = rot => mul(mul(Rx(rot[0] * D2R), Ry(rot[1] * D2R)), Rz(rot[2] * D2R));
const matEuler = m => {
  const y = Math.asin(Math.min(1, Math.max(-1, m[0][2])));
  return Math.abs(m[0][2]) < 0.9999999 ? [Math.atan2(-m[1][2], m[2][2]) * R2D, y * R2D, Math.atan2(-m[0][1], m[0][0]) * R2D] : [Math.atan2(m[2][1], m[1][1]) * R2D, y * R2D, 0];
};

// the box a part fills in the world: [min, max] on each axis, with its rotation taken into account
export function partBox(p) {
  const m = eulerMat((p.rot || [0, 0, 0])), e = ext(p.shape), half = [0, 1, 2].map(i => {
    let h = 0; for (let j = 0; j < 3; j++) h += Math.abs(m[i][j]) * e[j] * p.scale[j] / 2; return h; });
  const c = p.pos || [0, 0, 0];
  return { min: c.map((v, i) => v - half[i]), max: c.map((v, i) => v + half[i]), half };
}

const AXIS_OF = { top: [1, 1], bottom: [1, -1], right: [0, 1], left: [0, -1], front: [2, 1], back: [2, -1] };
// where a part goes when it is put on a side of an earlier part. "off" slides it along the other two axes (x, y, z order).
function attach(parent, p, side, off) {
  const [ax, dir] = AXIS_OF[side], o = partBox({ ...p, pos: [0, 0, 0] }), pb = partBox(parent), pos = parent.pos.slice();
  const others = [0, 1, 2].filter(i => i !== ax);
  others.forEach((i, k) => { pos[i] += clampN(off?.[k], -4, 4, 0); });
  pos[ax] = dir > 0 ? pb.max[ax] + o.half[ax] - 0.02 : pb.min[ax] - o.half[ax] + 0.02;   // a hair of overlap so the two touch
  return pos;
}

// reflect or rotate a copy of a part. Rotations are exact; a mirror flips the angles it should.
const spin = (p, deg) => {
  const t = deg * D2R, c = Math.cos(t), s = Math.sin(t);
  return { ...p, pos: [p.pos[0] * c + p.pos[2] * s, p.pos[1], -p.pos[0] * s + p.pos[2] * c], rot: matEuler(mul(Ry(t), eulerMat(p.rot))) };
};
const mirrorX = p => ({ ...p, pos: [-p.pos[0], p.pos[1], p.pos[2]], rot: [p.rot[0], -p.rot[1], -p.rot[2]] });
const mirrorZ = p => ({ ...p, pos: [p.pos[0], p.pos[1], -p.pos[2]], rot: [-p.rot[0], -p.rot[1], p.rot[2]] });
const onAxis = (p, i) => Math.abs(p.pos[i]) < 0.03;
function copies(p) {
  let out = [p];
  const m = p.mirror, add = f => { for (const q of out.slice()) out.push(f(q)); };
  if (m === 'x' || m === 'xz') { if (!onAxis(p, 0)) add(mirrorX); }
  if (m === 'z' || m === 'xz') { if (!onAxis(p, 2)) add(mirrorZ); }
  const n = Math.round(Number(p.ring));
  if (n >= 2 && n <= 12 && Math.hypot(p.pos[0], p.pos[2]) >= 0.03) { const base = out.slice(); for (const q of base) for (let k = 1; k < n; k++) out.push(spin(q, 360 * k / n)); }
  return out;
}

// raw JSON from the model -> clean parts (centred, standing on the ground) or null.
// env: { PAL, MATERIALS, USES, useOfName(name), matOfColor(color), maxParts }
export function cleanRecipe(j, name, env) {
  j = withKit(j);
  const base = j?.base && typeof j.base === 'object' ? [{ ...j.base, pos: [0, clampN(j.base.scale?.[1], 0.04, 4, 0.5) / 2, 0] }] : [];   // the base stands at the middle
  const raw = [...base, ...(Array.isArray(j?.parts) ? j.parts : [])].slice(0, env.maxParts), made = [], src = [], warn = [], ids = {};
  const label = i => raw[i]?.id ? `"${raw[i].id}"` : String(i);
  raw.forEach((p, i) => {
    if (typeof p?.id === 'string' && !(String(p.id).toLowerCase() in ids)) ids[p.id.toLowerCase()] = i;
    if (!SHAPES.includes(p?.shape)) { made.push(null); return; }
    const q = { shape: p.shape, scale: v3(p.scale, 0.04, 4, 0.5), rot: v3(p.rot, -180, 180, 0), color: env.PAL[p.color] ? p.color : 'violet', glow: !!p.glow,
      material: env.MATERIALS[p.material] ? p.material : env.matOfColor(p.color), mirror: MIRRORS.includes(p.mirror) ? p.mirror : undefined, ring: p.ring };
    if (typeof p.text === 'string' && p.text.trim() && ['box', 'rbox'].includes(p.shape)) q.text = p.text.trim().slice(0, 48);
    const ref = typeof p.on === 'string' ? ids[p.on.toLowerCase()] : Number.isInteger(p.on) ? p.on : undefined;
    const par = ref >= 0 && ref < i ? made[ref] : null;
    if (p.on !== undefined && p.on !== null && !par) warn.push(`part ${label(i)} is attached to ${JSON.stringify(p.on)}, which is not the id of an EARLIER part`);
    else if (par && ['wedge', 'cone', 'pyramid', 'dome'].includes(p.shape) && p.side === 'bottom') warn.push(`part ${label(i)} is a ${p.shape} on the BOTTOM of another part; roofs, tips and tops go on "top"`);
    else if (par && !AXIS_OF[p.side]) warn.push(`part ${label(i)} says "on" but has no "side" (top, bottom, left, right, front or back)`);
    if (Number(p.ring) >= 2 && !par && Math.hypot(...[0, 2].map(k => Number(p.pos?.[k]) || 0)) < 0.03) warn.push(`part ${label(i)} has "ring" but sits on the middle line, so its copies would pile up; move it out from the middle with "on" and "side", or "pos"`);
    q.pos = par && AXIS_OF[p.side] ? attach(par, q, p.side, p.off) : v3(p.pos, -3, 6, 0);
    q.pos = q.pos.map(v => Math.min(6, Math.max(-6, v)));
    made.push(q);
  });
  let parts = [];
  made.forEach((q, i) => { if (q) for (const c of copies(q)) { parts.push(c); src.push(i); } });
  if (parts.length > env.maxParts) { parts = parts.slice(0, env.maxParts); src.length = env.maxParts; }
  if (!parts.length) return null;
  // keep the shapes' own clamps after symmetry, then centre the whole thing and stand it on the ground
  parts.forEach(p => { p.pos = p.pos.map(v => Math.min(6, Math.max(-6, v))); p.rot = p.rot.map(v => Math.round(v * 10) / 10); delete p.mirror; delete p.ring; });
  const minY = Math.min(...parts.map(p => partBox(p).min[1]));
  const cx = parts.reduce((s, p) => s + p.pos[0], 0) / parts.length, cz = parts.reduce((s, p) => s + p.pos[2], 0) / parts.length;
  parts.forEach(p => { p.pos[0] -= cx; p.pos[1] -= minY; p.pos[2] -= cz; });
  return { use: env.USES.includes(j?.use) ? j.use : env.useOfName(name), parts, src, labels: raw.map((_, i) => label(i)), warn, ...(j?.kit?.type ? { kit: j.kit.type } : {}) };
}

// how far the finished thing reaches out from its middle on the ground (for finding room for it)
export function footprint(recipe) {
  let r = 0.3;
  for (const p of recipe.parts) { const b = partBox(p); r = Math.max(r, Math.hypot(Math.max(Math.abs(b.min[0]), Math.abs(b.max[0])), Math.max(Math.abs(b.min[2]), Math.abs(b.max[2])))); }
  return r;
}

// which parts touch the biggest connected group; the rest are floating on their own
export function connectivity(parts, gap = 0.04) {
  const boxes = parts.map(partBox), root = parts.map((_, i) => i), find = i => root[i] === i ? i : (root[i] = find(root[i]));
  for (let i = 0; i < parts.length; i++) for (let k = i + 1; k < parts.length; k++) {
    const a = boxes[i], b = boxes[k];
    if ([0, 1, 2].every(x => a.min[x] <= b.max[x] + gap && b.min[x] <= a.max[x] + gap)) root[find(i)] = find(k);
  }
  const groups = {}; parts.forEach((_, i) => (groups[find(i)] ||= []).push(i));
  const list = Object.values(groups).sort((a, b) => b.length - a.length);
  return { main: list[0] || [], strays: list.slice(1).flat() };
}

// does the thing do what its "use" says? Returns plain-language problems the model can fix.
function useProblems(recipe) {
  const P = recipe.parts, out = [], top = p => p.pos[1] + p.scale[1] / 2;
  const centred = p => Math.abs(p.pos[0]) < p.scale[0] / 2 + 0.3 && Math.abs(p.pos[2]) < p.scale[2] / 2 + 0.3;
  if (recipe.use === 'lamp' && !P.some(p => p.glow)) out.push('a lamp needs at least one part with "glow": true');
  if (recipe.use === 'shelter' && !P.some(p => p.pos[1] - p.scale[1] / 2 > 1.5 && p.scale[0] > 1.2 && p.scale[2] > 1.2)) out.push('a shelter needs a roof that starts above 1.6 units high and is wider than 1.2 units');
  if ((recipe.use === 'seat' || recipe.use === 'bed') && !P.some(p => top(p) >= 0.2 && top(p) <= 1.05 && centred(p))) out.push(`a ${recipe.use} needs a flat part to ${recipe.use === 'seat' ? 'sit' : 'lie'} on with its top between 0.2 and 1 unit high`);
  return out;
}

// problems found with a cleaned recipe. hard: it is not a usable object yet. soft: it works but could be better.
export function checkRecipe(recipe) {
  const hard = [], soft = [...(recipe.warn || [])], P = recipe.parts, srcOf = i => (recipe.src?.[i] ?? i), lab = i => recipe.labels?.[i] ?? i;
  if (P.length < 3) hard.push('it has fewer than 3 parts; add the details that make it look like what it is');
  const { strays } = connectivity(P);
  if (strays.length) {
    const ids = [...new Set(strays.map(srcOf))].slice(0, 6).map(lab);
    hard.push(`part${ids.length > 1 ? 's' : ''} ${ids.join(', ')} float${ids.length > 1 ? '' : 's'} away from the rest; attach ${ids.length > 1 ? 'them' : 'it'} to another part with "on" and "side"`);
  }
  for (let i = 0; i < P.length; i++) for (let k = i + 1; k < P.length; k++) {
    const a = P[i], b = P[k];
    if (a.shape === b.shape && [0, 1, 2].every(x => Math.abs(a.pos[x] - b.pos[x]) < 0.05 && Math.abs(a.scale[x] - b.scale[x]) < 0.05)) {
      soft.push(`parts ${lab(srcOf(i))} and ${lab(srcOf(k))} are in exactly the same place; give each part its own place`); i = P.length; break; }
  }
  const use = useProblems(recipe);
  if (use.length) soft.push(...use);
  if (P.length > 4 && new Set(P.map(p => p.color)).size < 2) soft.push('every part is the same colour; use two or three colours so the details show');
  if (P.length > 5 && new Set(P.map(p => p.shape)).size < 2) soft.push('every part is the same shape; mix shapes so it does not look like a block');
  return { hard, soft };
}

// last resort: drop the floating parts. Returns false if too little is left.
export function dropStrays(recipe) {
  const { main } = connectivity(recipe.parts), keep = new Set(main);
  recipe.src = recipe.src?.filter((_, i) => keep.has(i));
  recipe.parts = recipe.parts.filter((_, i) => keep.has(i));
  return recipe.parts.length >= 3;
}

// a lamp that cannot light, a seat with no seat: say what it really is
export function settleUse(recipe) { if (useProblems(recipe).length) recipe.use = 'art'; }

// ---- what the model is shown
// The recipe is a "base" part (it stands at the middle of the build, the code places it) plus parts that each go ON an earlier
// part. The model is never asked for coordinates: a small model gets them wrong, and parts end up floating or piled together.
export const BUILD_EXAMPLES = `Example 1, a small chair. Start from the "base" (the seat). Every other part has an "id" and goes "on" a part before it. The four legs are one part with "mirror": "xz".
{"plan":"A seat, four legs, a backrest and a soft cushion.","note":"A little chair with a soft pink cushion.","use":"seat",
"base":{"id":"seat","shape":"box","scale":[0.8,0.1,0.8],"color":"wood","material":"wood"},
"parts":[
{"id":"legs","shape":"cylinder","on":"seat","side":"bottom","off":[0.3,0.3],"scale":[0.08,0.5,0.08],"color":"bark","material":"wood","mirror":"xz"},
{"id":"back","shape":"box","on":"seat","side":"top","off":[0,-0.35],"scale":[0.8,0.7,0.1],"color":"wood","material":"wood"},
{"id":"cushion","shape":"rbox","on":"seat","side":"top","off":[0,0.05],"scale":[0.7,0.14,0.6],"color":"pink","material":"cushion"}]}

Example 2, a flower. The base is the stem. The petal sits to the RIGHT of the yellow middle, and "ring": 6 turns it into six petals all the way around.
{"plan":"A stem, two leaves, a round yellow middle and six petals around it.","note":"A tall flower with pink petals.","use":"art",
"base":{"id":"stem","shape":"taper","scale":[0.1,1.2,0.1],"color":"green","material":"moss"},
"parts":[
{"id":"leaf","shape":"sphere","on":"stem","side":"right","off":[-0.25,0],"scale":[0.5,0.08,0.22],"rot":[0,0,20],"color":"lime","material":"moss","mirror":"x"},
{"id":"middle","shape":"sphere","on":"stem","side":"top","scale":[0.3,0.3,0.3],"color":"yellow","material":"fabric"},
{"id":"petals","shape":"sphere","on":"middle","side":"right","scale":[0.34,0.1,0.2],"color":"pink","material":"fabric","ring":6}]}

Example 3, a small house. The roof is a wedge on the TOP of the walls, wider than them; the door and the windows go on the FRONT side. A part with "mirror": "x" and "off" 0.55 gets a twin at -0.55.
{"plan":"Walls, a red gabled roof, a door and two glowing windows.","note":"A cosy little house.","use":"shelter",
"base":{"id":"walls","shape":"box","scale":[1.8,1.8,1.6],"color":"cream","material":"wood"},
"parts":[
{"id":"roof","shape":"wedge","on":"walls","side":"top","scale":[2.2,0.9,1.9],"color":"red","material":"wood"},
{"id":"door","shape":"box","on":"walls","side":"front","off":[0,-0.3],"scale":[0.5,1,0.1],"color":"bark","material":"wood"},
{"id":"window","shape":"box","on":"walls","side":"front","off":[0.55,0.2],"scale":[0.4,0.4,0.1],"color":"yellow","material":"glass","glow":true,"mirror":"x"}]}

Example 4, a lamp post. The glowing part has "glow": true.
{"plan":"A foot, a pole, a glowing ball and a little hat over it.","note":"A tall lamp that glows at night.","use":"lamp",
"base":{"id":"foot","shape":"cylinder","scale":[0.5,0.08,0.5],"color":"navy","material":"metal"},
"parts":[
{"id":"pole","shape":"cylinder","on":"foot","side":"top","scale":[0.1,1.7,0.1],"color":"navy","material":"metal"},
{"id":"light","shape":"sphere","on":"pole","side":"top","scale":[0.4,0.4,0.4],"color":"yellow","material":"glass","glow":true},
{"id":"hat","shape":"cone","on":"light","side":"top","scale":[0.5,0.3,0.5],"color":"navy","material":"metal"}]}`;

// the JSON schema that forces the reply into the recipe shape: no coordinates, only "on" + "side"
export function buildSchema(colors, materials, uses) {
  const part = { shape: { type: 'string', enum: SHAPES }, material: { type: 'string', enum: materials }, color: { type: 'string', enum: colors },
    id: { type: 'string' }, scale: { type: 'array', items: { type: 'number' } }, rot: { type: 'array', items: { type: 'number' } }, glow: { type: 'boolean' }, text: { type: 'string' } };
  return { type: 'object', required: ['plan', 'use', 'parts'], properties: {
    plan: { type: 'string' }, note: { type: 'string' }, use: { type: 'string', enum: uses },
    kit: { type: 'object', required: ['type'], properties: { type: { type: 'string', enum: Object.keys(KITS) }, color: { type: 'string', enum: colors },
      accent: { type: 'string', enum: colors }, size: { type: 'number' }, count: { type: 'integer' }, text: { type: 'string' } } },
    base: { type: 'object', required: ['id', 'shape', 'scale', 'color', 'material'], properties: part },
    parts: { type: 'array', items: { type: 'object', required: ['id', 'shape', 'scale', 'color', 'material', 'on', 'side'], properties: {
      ...part, on: { type: 'string' }, side: { type: 'string', enum: SIDES }, off: { type: 'array', items: { type: 'number' } },
      mirror: { type: 'string', enum: MIRRORS }, ring: { type: 'integer' } } } } } };
}

// ---- kits: ready-made things that always come out looking right. The model picks one and a few settings, then may add
// its own parts "on" the kit's parts (by their ids). This is the biggest help for a small model: a flower, a sign or a
// tower made from a kit is well proportioned every time, and his own parts make it his.
const K = (id, shape, scale, color, material, more = {}) => ({ id, shape, scale, color, material, ...more });
const on = (part, id, side, off) => ({ ...part, on: id, side, ...(off ? { off } : {}) });
export const KITS = {
  flower: { ids: 'stem, leaf, middle, petals', use: 'art', make: ({ S, color = 'pink', accent = 'yellow', count = 8 }) => ({ base: K('stem', 'taper', [0.12 * S, 1.3 * S, 0.12 * S], 'green', 'moss'), parts: [
    on(K('leaf', 'sphere', [0.55 * S, 0.08 * S, 0.24 * S], 'lime', 'moss', { rot: [0, 0, 25], mirror: 'x' }), 'stem', 'right', [-0.35 * S, 0]),
    on(K('middle', 'sphere', [0.34 * S, 0.3 * S, 0.34 * S], accent, 'fabric'), 'stem', 'top'),
    on(K('petals', 'sphere', [0.4 * S, 0.09 * S, 0.2 * S], color, 'fabric', { rot: [0, 0, 12], ring: clampN(count, 4, 12, 8) }), 'middle', 'right')] }) },
  tree: { ids: 'trunk, crown, puff', use: 'art', make: ({ S, color = 'green', accent = 'bark' }) => ({ base: K('trunk', 'taper', [0.35 * S, 1.6 * S, 0.35 * S], accent, 'bark'), parts: [
    on(K('crown', 'sphere', [1.6 * S, 1.3 * S, 1.6 * S], color, 'moss'), 'trunk', 'top'),
    on(K('puff', 'sphere', [1.0 * S, 0.8 * S, 1.0 * S], color, 'moss'), 'crown', 'top')] }) },
  chair: { ids: 'seat, legs, back, cushion', use: 'seat', maxS: 1.3, make: ({ S, color = 'wood', accent = 'pink' }) => ({ base: K('seat', 'box', [0.8 * S, 0.1 * S, 0.8 * S], color, 'wood'), parts: [
    on(K('legs', 'cylinder', [0.08 * S, 0.5 * S, 0.08 * S], 'bark', 'wood', { mirror: 'xz' }), 'seat', 'bottom', [0.3 * S, 0.3 * S]),
    on(K('back', 'box', [0.8 * S, 0.7 * S, 0.1 * S], color, 'wood'), 'seat', 'top', [0, -0.35 * S]),
    on(K('cushion', 'rbox', [0.7 * S, 0.14 * S, 0.6 * S], accent, 'cushion'), 'seat', 'top', [0, 0.05 * S])] }) },
  bench: { ids: 'seat, legs, back', use: 'seat', make: ({ S, color = 'wood', accent = 'bark' }) => ({ base: K('seat', 'box', [1.6 * S, 0.1 * S, 0.5 * S], color, 'wood'), parts: [
    on(K('legs', 'box', [0.1 * S, 0.42 * S, 0.45 * S], accent, 'wood', { mirror: 'x' }), 'seat', 'bottom', [0.65 * S, 0]),
    on(K('back', 'box', [1.6 * S, 0.5 * S, 0.08 * S], color, 'wood'), 'seat', 'top', [0, -0.2 * S])] }) },
  table: { ids: 'top, legs', use: 'table', make: ({ S, color = 'wood', accent = 'bark' }) => ({ base: K('top', 'rbox', [1.4 * S, 0.12 * S, 0.9 * S], color, 'wood'), parts: [
    on(K('legs', 'cylinder', [0.09 * S, 0.7 * S, 0.09 * S], accent, 'wood', { mirror: 'xz' }), 'top', 'bottom', [0.55 * S, 0.33 * S])] }) },
  house: { ids: 'walls, roof, door, window, chimney', use: 'shelter', minS: 1.05, make: ({ S, color = 'cream', accent = 'red' }) => ({ base: K('walls', 'box', [1.8 * S, 1.6 * S, 1.6 * S], color, 'wood'), parts: [
    on(K('roof', 'wedge', [2.2 * S, 0.9 * S, 1.9 * S], accent, 'wood'), 'walls', 'top'),
    on(K('door', 'box', [0.5 * S, 1.0 * S, 0.1 * S], 'bark', 'wood'), 'walls', 'front', [0, -0.3 * S]),
    on(K('window', 'box', [0.4 * S, 0.4 * S, 0.1 * S], 'yellow', 'glass', { glow: true, mirror: 'x' }), 'walls', 'front', [0.55 * S, 0.2 * S]),
    on(K('chimney', 'box', [0.25 * S, 1.0 * S, 0.25 * S], 'stone', 'stone'), 'walls', 'top', [0.55 * S, -0.35 * S])] }) },
  lamp: { ids: 'foot, pole, light, hat', use: 'lamp', make: ({ S, color = 'navy', accent = 'yellow' }) => ({ base: K('foot', 'cylinder', [0.5 * S, 0.08 * S, 0.5 * S], color, 'metal'), parts: [
    on(K('pole', 'cylinder', [0.1 * S, 1.7 * S, 0.1 * S], color, 'metal'), 'foot', 'top'),
    on(K('light', 'sphere', [0.4 * S, 0.4 * S, 0.4 * S], accent, 'glass', { glow: true }), 'pole', 'top'),
    on(K('hat', 'cone', [0.5 * S, 0.3 * S, 0.5 * S], color, 'metal'), 'light', 'top')] }) },
  sign: { ids: 'board, posts, trim', use: 'art', make: ({ S, color = 'cream', accent = 'wood', text = '' }) => ({ base: K('board', 'box', [1.4 * S, 0.7 * S, 0.1 * S], color, 'wood', { text }), parts: [
    on(K('posts', 'cylinder', [0.1 * S, 1.0 * S, 0.1 * S], 'bark', 'wood', { mirror: 'x' }), 'board', 'bottom', [0.5 * S, 0]),
    on(K('trim', 'box', [1.5 * S, 0.08 * S, 0.14 * S], accent, 'wood'), 'board', 'top')] }) },
  billboard: { ids: 'board, posts, frame, lights', use: 'art', maxS: 1.15, make: ({ S, color = 'white', accent = 'magenta', text = '' }) => ({ base: K('board', 'box', [3.2 * S, 1.6 * S, 0.14 * S], color, 'wood', { text }), parts: [
    on(K('posts', 'box', [0.18 * S, 1.6 * S, 0.18 * S], 'stone', 'metal', { mirror: 'x' }), 'board', 'bottom', [1.2 * S, 0]),
    on(K('frame', 'box', [3.4 * S, 0.14 * S, 0.22 * S], accent, 'metal'), 'board', 'top'),
    on(K('lights', 'sphere', [0.2 * S, 0.2 * S, 0.2 * S], 'yellow', 'glass', { glow: true, mirror: 'x' }), 'frame', 'top', [1.3 * S, 0])] }) },
  tower: { ids: 'floor1 .. floorN, roof, window', use: 'art', make: ({ S, color = 'stone', accent = 'red', count = 3 }) => {
    const n = clampN(count, 2, 5, 3), parts = [];
    for (let i = 1; i < n; i++) parts.push(on(K('floor' + (i + 1), 'cylinder', [(1.4 - i * 0.15) * S, 1.0 * S, (1.4 - i * 0.15) * S], color, 'stone'), 'floor' + i, 'top'));
    parts.push(on(K('roof', 'cone', [(1.8 - n * 0.15) * S, 1.1 * S, (1.8 - n * 0.15) * S], accent, 'wood'), 'floor' + n, 'top'),
      on(K('window', 'box', [0.3 * S, 0.4 * S, 0.1 * S], 'yellow', 'glass', { glow: true }), 'floor' + n, 'front'));
    return { base: K('floor1', 'cylinder', [1.4 * S, 1.0 * S, 1.4 * S], color, 'stone'), parts }; } },
  statue: { ids: 'pedestal, plaque, body, wings, neck, head, beak', use: 'art', make: ({ S, color = 'white', accent = 'orange', text = '' }) => ({ base: K('pedestal', 'box', [1.0 * S, 0.8 * S, 1.0 * S], 'stone', 'stone'), parts: [
    on(K('plaque', 'box', [0.7 * S, 0.3 * S, 0.04 * S], 'yellow', 'metal', text ? { text } : {}), 'pedestal', 'front'),
    on(K('body', 'sphere', [0.9 * S, 0.7 * S, 1.1 * S], color, 'stone'), 'pedestal', 'top'),
    on(K('wings', 'sphere', [0.14 * S, 0.45 * S, 0.7 * S], color, 'stone', { mirror: 'x' }), 'body', 'right'),
    on(K('neck', 'cylinder', [0.18 * S, 0.8 * S, 0.18 * S], color, 'stone'), 'body', 'top', [0, 0.25 * S]),
    on(K('head', 'sphere', [0.35 * S, 0.32 * S, 0.4 * S], color, 'stone'), 'neck', 'top'),
    on(K('beak', 'cone', [0.15 * S, 0.3 * S, 0.15 * S], accent, 'stone', { rot: [90, 0, 0] }), 'head', 'front')] }) },
  arch: { ids: 'lintel, pillars, cap', use: 'art', make: ({ S, color = 'stone', accent = 'violet', text = '' }) => ({ base: K('lintel', 'box', [2.2 * S, 0.35 * S, 0.45 * S], color, 'stone', text ? { text } : {}), parts: [
    on(K('pillars', 'box', [0.35 * S, 2.2 * S, 0.35 * S], color, 'stone', { mirror: 'x' }), 'lintel', 'bottom', [0.9 * S, 0]),
    on(K('cap', 'box', [0.5 * S, 0.25 * S, 0.5 * S], accent, 'stone'), 'lintel', 'top')] }) },
  fountain: { ids: 'basin, water, column, bowl, spout', use: 'art', make: ({ S, color = 'stone', accent = 'teal' }) => ({ base: K('basin', 'cylinder', [2.0 * S, 0.4 * S, 2.0 * S], color, 'stone'), parts: [
    on(K('water', 'cylinder', [1.7 * S, 0.06 * S, 1.7 * S], accent, 'glass', { glow: true }), 'basin', 'top'),
    on(K('column', 'cylinder', [0.25 * S, 0.9 * S, 0.25 * S], color, 'stone'), 'water', 'top'),
    on(K('bowl', 'cylinder', [0.8 * S, 0.15 * S, 0.8 * S], color, 'stone'), 'column', 'top'),
    on(K('spout', 'sphere', [0.3 * S, 0.4 * S, 0.3 * S], accent, 'glass', { glow: true }), 'bowl', 'top')] }) },
  mushroom: { ids: 'stem, cap, spots', use: 'art', make: ({ S, color = 'red', accent = 'white' }) => ({ base: K('stem', 'cylinder', [0.4 * S, 1.0 * S, 0.4 * S], 'cream', 'moss'), parts: [
    on(K('cap', 'dome', [1.6 * S, 0.8 * S, 1.6 * S], color, 'moss'), 'stem', 'top'),
    on(K('spots', 'sphere', [0.22 * S, 0.1 * S, 0.22 * S], accent, 'moss', { ring: 5 }), 'cap', 'top', [0.32 * S, 0])] }) },
  campfire: { ids: 'ash, stones, logs, flame, core', use: 'lamp', make: ({ S, color = 'orange', accent = 'yellow' }) => ({ base: K('ash', 'cylinder', [1.0 * S, 0.06 * S, 1.0 * S], 'stone', 'stone'), parts: [
    on(K('stones', 'sphere', [0.25 * S, 0.2 * S, 0.25 * S], 'stone', 'stone', { ring: 8 }), 'ash', 'right'),
    on(K('logs', 'cylinder', [0.12 * S, 0.7 * S, 0.12 * S], 'bark', 'wood', { rot: [0, 0, 25], ring: 4 }), 'ash', 'top', [0.15 * S, 0]),
    on(K('flame', 'cone', [0.4 * S, 0.65 * S, 0.4 * S], color, 'fabric', { glow: true }), 'ash', 'top'),
    on(K('core', 'cone', [0.22 * S, 0.4 * S, 0.22 * S], accent, 'fabric', { glow: true }), 'ash', 'top')] }) },
  rocket: { ids: 'body, nose, window, fins, flame', use: 'toy', make: ({ S, color = 'white', accent = 'red' }) => ({ base: K('body', 'cylinder', [0.7 * S, 2.0 * S, 0.7 * S], color, 'metal'), parts: [
    on(K('nose', 'cone', [0.7 * S, 0.8 * S, 0.7 * S], accent, 'metal'), 'body', 'top'),
    on(K('window', 'cylinder', [0.3 * S, 0.08 * S, 0.3 * S], 'periwinkle', 'glass', { rot: [90, 0, 0], glow: true }), 'body', 'front', [0, 0.4 * S]),
    on(K('fins', 'wedge', [0.5 * S, 0.6 * S, 0.08 * S], accent, 'metal', { ring: 3 }), 'body', 'right', [-0.7 * S, 0]),
    on(K('flame', 'sphere', [0.45 * S, 0.4 * S, 0.45 * S], 'orange', 'fabric', { glow: true }), 'body', 'bottom')] }) },
  portal: { ids: 'ring, film, feet, plaque', use: 'art', make: ({ S, color = 'violet', accent = 'periwinkle', text = '' }) => ({ base: K('ring', 'torus', [2.4 * S, 2.4 * S, 1.2 * S], color, 'stone', { glow: true }), parts: [
    { ...K('film', 'cylinder', [1.7 * S, 0.04 * S, 1.7 * S], accent, 'glass', { rot: [90, 0, 0], glow: true }), pos: [0, 1.2 * S, 0] },
    on(K('feet', 'box', [1.4 * S, 0.3 * S, 0.8 * S], 'stone', 'stone'), 'ring', 'bottom'),
    on(K('plaque', 'box', [1.2 * S, 0.26 * S, 0.05 * S], 'cream', 'wood', text ? { text } : {}), 'feet', 'front')] }) },
  screen: { ids: 'foot, pole, screen, frame', use: 'art', make: ({ S, color = 'navy', accent = 'mint', text = '' }) => ({ base: K('foot', 'rbox', [1.0 * S, 0.12 * S, 0.6 * S], color, 'metal'), parts: [
    on(K('pole', 'cylinder', [0.12 * S, 1.0 * S, 0.12 * S], color, 'metal'), 'foot', 'top'),
    on(K('frame', 'box', [2.0 * S, 1.25 * S, 0.12 * S], color, 'metal'), 'pole', 'top'),
    on(K('screen', 'box', [1.8 * S, 1.05 * S, 0.04 * S], 'indigo', 'glass', { glow: true, text }), 'frame', 'front')] }) },
};
export const KIT_NAMES = Object.keys(KITS);
// the kit's parts (as a recipe), followed by the model's own extra parts; the model's "base" is not used with a kit
function withKit(j) {
  const k = j?.kit && KITS[j.kit.type];
  if (!k) return j;
  const S = clampN(j.kit.size, k.minS || 0.4, k.maxS || 2.5, Math.max(1, k.minS || 0)), text = typeof j.kit.text === 'string' ? j.kit.text.trim().slice(0, 48) : '';
  const opt = { S, text, count: j.kit.count, ...(j.kit.color ? { color: j.kit.color } : {}), ...(j.kit.accent ? { accent: j.kit.accent } : {}) };
  const r = k.make(opt), kitIds = new Set([r.base, ...r.parts].map(p => p.id));
  const extra = (Array.isArray(j.parts) ? j.parts : []).filter(p => !kitIds.has(p?.id));   // a part that repeats a kit part by id is dropped
  return { ...j, use: j.use || k.use, base: r.base, parts: [...r.parts, ...extra] };
}
