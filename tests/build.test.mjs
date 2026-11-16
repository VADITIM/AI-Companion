// Tests for how Honk's builds are placed and checked (World/honk-build.js). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as B from '../World/honk-build.js';

const PAL = Object.fromEntries(['wood', 'bark', 'pink', 'green', 'lime', 'yellow', 'navy', 'violet'].map(c => [c, '#000']));
const MATERIALS = Object.fromEntries(['wood', 'cushion', 'moss', 'fabric', 'stone'].map(m => [m, {}]));
const env = { PAL, MATERIALS, USES: ['seat', 'bed', 'lamp', 'shelter', 'table', 'toy', 'art', 'other'], useOfName: () => 'art', matOfColor: () => 'wood', maxParts: 40 };
// the two examples shown to the model are parsed from the prompt itself, so they can never rot
const examples = [...B.BUILD_EXAMPLES.matchAll(/^\{"plan".*?\]\}$/gms)].map(m => JSON.parse(m[0]));
const [chairJ, flowerJ, houseJ, lampJ] = examples;
const near = (a, b, e = 0.05) => assert.ok(Math.abs(a - b) < e, `${a} is not near ${b}`);

test('all prompt examples are valid JSON recipes', () => assert.equal(examples.length, 4));

test('the house and lamp examples really are a shelter and a lamp, with nothing floating', () => {
  const e2 = { ...env, PAL: { ...PAL, cream: 1, red: 1 }, MATERIALS: { ...MATERIALS, glass: {}, metal: {} } };
  for (const [j, use, n] of [[houseJ, 'shelter', 5], [lampJ, 'lamp', 4]]) {
    const r = B.cleanRecipe(j, 'x', e2);
    assert.equal(r.parts.length, n); assert.deepEqual(B.checkRecipe(r), { hard: [], soft: [] }); B.settleUse(r); assert.equal(r.use, use);
  }
});

test('the chair example: four legs from one part, all touching, standing on the ground', () => {
  const r = B.cleanRecipe(chairJ, 'chair', env);
  assert.equal(r.parts.length, 7);                                   // seat + 4 legs + back + cushion
  assert.equal(r.parts.filter(p => p.shape === 'cylinder').length, 4);
  near(Math.min(...r.parts.map(p => B.partBox(p).min[1])), 0);
  assert.deepEqual(B.checkRecipe(r), { hard: [], soft: [] });
  assert.equal(r.use, 'seat');
});

test('the flower example: six petals around the stem, a leaf on each side', () => {
  const r = B.cleanRecipe(flowerJ, 'flower', env);
  assert.equal(r.parts.length, 1 + 2 + 1 + 6);
  const petals = r.parts.filter(p => p.color === 'pink');
  assert.equal(petals.length, 6);
  const mid = r.parts.find(p => p.color === 'yellow');
  for (const p of petals) near(Math.hypot(p.pos[0] - mid.pos[0], p.pos[2] - mid.pos[2]), Math.hypot(petals[0].pos[0] - mid.pos[0], petals[0].pos[2] - mid.pos[2]), 0.02);
  assert.equal(new Set(petals.map(p => p.pos.map(v => v.toFixed(2)).join())).size, 6);   // all in different places
  assert.deepEqual(B.checkRecipe(r), { hard: [], soft: [] });
});

test('"top" puts a part exactly on the parent, "right" beside it', () => {
  const r = B.cleanRecipe({ parts: [
    { shape: 'box', pos: [0, 0.5, 0], scale: [1, 1, 1], color: 'wood', material: 'wood' },
    { shape: 'sphere', on: 0, side: 'top', scale: [0.5, 0.5, 0.5], color: 'pink', material: 'wood' },
    { shape: 'box', on: 0, side: 'right', scale: [0.4, 0.4, 0.4], color: 'pink', material: 'wood' }] }, 'x', env);
  const [a, b, c] = r.parts, ba = B.partBox(a), bb = B.partBox(b), bc = B.partBox(c);
  near(bb.min[1], ba.max[1], 0.03); near(bc.min[0], ba.max[0], 0.03);
});

test('a part that floats away is reported, then dropped as a last resort', () => {
  const r = B.cleanRecipe({ parts: [
    { shape: 'box', pos: [0, 0.5, 0], scale: [1, 1, 1], color: 'wood', material: 'wood' },
    { shape: 'box', on: 0, side: 'top', scale: [0.5, 0.5, 0.5], color: 'pink', material: 'wood' },
    { shape: 'box', on: 0, side: 'left', scale: [0.4, 0.4, 0.4], color: 'violet', material: 'wood' },
    { shape: 'sphere', pos: [3, 3, 3], scale: [0.3, 0.3, 0.3], color: 'yellow', material: 'wood' }] }, 'x', env);
  const c = B.checkRecipe(r);
  assert.equal(c.hard.length, 1); assert.match(c.hard[0], /part 3/);
  assert.ok(B.dropStrays(r)); assert.equal(r.parts.length, 3); assert.deepEqual(B.checkRecipe(r).hard, []);
});

test('too few parts is a hard problem; one colour is only a soft one', () => {
  const few = B.cleanRecipe({ parts: [{ shape: 'box', pos: [0, 0, 0], scale: [1, 1, 1], color: 'wood', material: 'wood' }] }, 'x', env);
  assert.equal(B.checkRecipe(few).hard.length, 1);
  const mono = B.cleanRecipe({ parts: Array.from({ length: 5 }, (_, i) => ({ shape: 'box', on: i ? i - 1 : undefined, side: 'top', pos: [0, 0.5, 0], scale: [1, 1, 1], color: 'wood', material: 'wood' })) }, 'x', env);
  const c = B.checkRecipe(mono); assert.deepEqual(c.hard, []); assert.ok(c.soft.some(s => /same colour/.test(s)));
});

test('a lamp with no glowing part becomes art; a lit one stays a lamp', () => {
  const mk = glow => B.cleanRecipe({ use: 'lamp', parts: [
    { shape: 'cylinder', pos: [0, 0.5, 0], scale: [0.1, 1, 0.1], color: 'navy', material: 'wood' },
    { shape: 'sphere', on: 0, side: 'top', scale: [0.4, 0.4, 0.4], color: 'yellow', material: 'wood', glow },
    { shape: 'cone', on: 1, side: 'top', scale: [0.4, 0.3, 0.4], color: 'navy', material: 'wood' }] }, 'x', env);
  const dark = mk(false); B.settleUse(dark); assert.equal(dark.use, 'art');
  const lit = mk(true); B.settleUse(lit); assert.equal(lit.use, 'lamp');
});

test('old recipes (absolute positions only) and bad input still clean up', () => {
  const r = B.cleanRecipe({ parts: [{ shape: 'box', pos: [5, 5, 5], scale: [1, 1, 1], color: 'nonsense' }, { shape: 'teapot' }, { shape: 'sphere', on: 7, side: 'top', pos: [5, 6, 5], scale: [1, 1, 1] }] }, 'x', env);
  assert.equal(r.parts.length, 2); assert.equal(r.parts[0].color, 'violet');
  assert.equal(B.cleanRecipe({ parts: [] }, 'x', env), null); assert.equal(B.cleanRecipe(null, 'x', env), null);
});

test('symmetry does not stack copies on the middle line, and the part cap holds', () => {
  const r = B.cleanRecipe({ parts: [{ shape: 'box', pos: [0, 0.5, 0], scale: [1, 1, 1], color: 'wood', material: 'wood', mirror: 'xz' }] }, 'x', env);
  assert.equal(r.parts.length, 1);
  const big = B.cleanRecipe({ parts: [{ shape: 'sphere', pos: [1, 0.5, 0], scale: [0.2, 0.2, 0.2], color: 'wood', material: 'wood', mirror: 'xz', ring: 12 }] }, 'x', env);
  assert.ok(big.parts.length <= 40);
});

test('parts are attached by id, and a wrong id or a ring on the middle line is called out', () => {
  const box = { shape: 'box', scale: [1, 1, 1], color: 'wood', material: 'wood' };
  const ok = B.cleanRecipe({ parts: [{ ...box, id: 'base', pos: [0, 0.5, 0] }, { ...box, id: 'lid', on: 'BASE', side: 'top' }] }, 'x', env);
  near(B.partBox(ok.parts[1]).min[1], B.partBox(ok.parts[0]).max[1], 0.03); assert.deepEqual(ok.warn, []);
  const bad = B.cleanRecipe({ parts: [{ ...box, id: 'base', pos: [0, 0.5, 0] }, { ...box, id: 'x', on: 'nothing', side: 'top' },
    { ...box, id: 'petal', ring: 6, pos: [0, 2, 0] }, { ...box, on: 5, side: 'top' }] }, 'x', env);
  assert.equal(bad.warn.length, 3);
  assert.ok(B.checkRecipe(bad).soft.length >= 3);
});

test('two parts in exactly the same place are reported by their ids', () => {
  const p = { shape: 'sphere', scale: [0.3, 0.3, 0.3], color: 'pink', material: 'wood' };
  const r = B.cleanRecipe({ parts: [{ ...p, id: 'a', pos: [0, 0.5, 0] }, { ...p, id: 'b', pos: [0, 0.5, 0] }, { ...p, id: 'c', on: 'a', side: 'top' }] }, 'x', env);
  assert.match(B.checkRecipe(r).soft.join(), /"a" and "b"/);
});

test('a base part stands at the middle and the rest attach to it; a roof on the bottom is called out', () => {
  const base = { id: 'walls', shape: 'box', scale: [1, 1, 1], color: 'wood', material: 'wood' };
  const r = B.cleanRecipe({ base, parts: [{ id: 'roof', shape: 'wedge', on: 'walls', side: 'top', scale: [1.2, 0.5, 1.2], color: 'pink', material: 'wood' },
    { id: 'tip', shape: 'cone', on: 'walls', side: 'bottom', scale: [0.3, 0.3, 0.3], color: 'pink', material: 'wood' }] }, 'x', env);
  assert.equal(r.parts.length, 3); near(r.parts[0].pos[0], 0); near(Math.min(...r.parts.map(p => B.partBox(p).min[1])), 0);
  assert.match(B.checkRecipe(r).soft.join(), /BOTTOM/);
});

// ---- kits
const ALL = ['navy', 'indigo', 'violet', 'periwinkle', 'lavender', 'cream', 'white', 'pink', 'magenta', 'plum', 'teal', 'mint', 'yellow', 'orange', 'red', 'lime', 'green', 'wood', 'bark', 'stone'];
const kenv = { ...env, PAL: Object.fromEntries(ALL.map(c => [c, '#000'])), MATERIALS: Object.fromEntries('wood bark stone metal glass fabric cushion moss'.split(' ').map(m => [m, {}])) };

test('every kit makes a whole, valid thing at any size', () => {
  for (const type of B.KIT_NAMES) for (const size of [0.5, 1, 2]) {
    const r = B.cleanRecipe({ kit: { type, size, text: 'HELLO' }, parts: [] }, type, kenv);
    assert.ok(r && r.parts.length >= 3, `${type} has parts`);
    assert.deepEqual(B.checkRecipe(r), { hard: [], soft: [] }, `${type} at size ${size}`);
    near(Math.min(...r.parts.map(p => B.partBox(p).min[1])), 0);
  }
});

test('a kit keeps its use, its text, and takes extra parts on its own part ids', () => {
  const r = B.cleanRecipe({ kit: { type: 'sign', text: 'Honk was here', color: 'pink' }, parts: [
    { id: 'flag', shape: 'cone', on: 'trim', side: 'top', scale: [0.2, 0.4, 0.2], color: 'red', material: 'fabric' }] }, 'sign', kenv);
  assert.equal(r.parts.find(p => p.text)?.text, 'Honk was here');
  assert.equal(r.parts.find(p => p.text).color, 'pink');
  assert.equal(r.parts.length, 5); assert.equal(r.kit, 'sign');
  assert.deepEqual(B.checkRecipe(r).hard, []);
  const lamp = B.cleanRecipe({ kit: { type: 'lamp' }, parts: [] }, 'x', kenv); B.settleUse(lamp); assert.equal(lamp.use, 'lamp');
});

test('text only goes on boxes, and stays short', () => {
  const r = B.cleanRecipe({ base: { id: 'a', shape: 'box', scale: [1, 1, 0.1], color: 'wood', material: 'wood', text: 'x'.repeat(200) },
    parts: [{ id: 'b', shape: 'sphere', on: 'a', side: 'top', scale: [0.5, 0.5, 0.5], color: 'pink', material: 'wood', text: 'no' }] }, 'x', kenv);
  assert.equal(r.parts[0].text.length, 48); assert.equal(r.parts[1].text, undefined);
});

test('footprint: how far the thing reaches from its middle', () => {
  const big = B.cleanRecipe({ kit: { type: 'billboard' }, parts: [] }, 'x', kenv), small = B.cleanRecipe({ kit: { type: 'lamp' }, parts: [] }, 'x', kenv);
  assert.ok(B.footprint(big) > 1.5 && B.footprint(small) < 0.5);
});
