// Tests for the sparks that pop into Honk's head (World/honk-ideas.js). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as I from '../honk-ideas.js';

const seq = (...xs) => { let i = 0; return () => xs[i++ % xs.length]; };

test('topics he has done too often are found', () => {
  const st = I.staleTopics(['build a flower sculpture', 'write a flower simulation', 'make a flower shape sketch', 'build a bench']);
  assert.deepEqual(st, ['flower']);
  assert.deepEqual(I.staleTopics(['build a simple little thing', 'make a simple little game']), []);   // words that say nothing do not count
});

test('a spark never leans on a topic he is worn out on', () => {
  const avoid = ['build a giant mushroom', 'make a mushroom game', 'a mushroom garden'];
  for (let i = 0; i < 300; i++) assert.ok(!/mushroom/.test(I.spark({ avoid }).text));
});

test('sparks come from different corners, and scenes only when he is ready', () => {
  let scene = false;
  for (let i = 0; i < 400; i++) { const s = I.spark({}); assert.ok(s.text.length > 5); if (s.kind === 'scene') scene = true; }
  assert.equal(scene, false);
  let any = false; for (let i = 0; i < 400 && !any; i++) any = I.spark({ ready: true }).kind === 'scene';
  assert.ok(any);
  const two = I.sparks(2, { rnd: Math.random });
  assert.equal(two.length, 2); assert.notEqual(two[0].kind, two[1].kind);
});

test('sparks are deterministic with a fixed random source', () => {
  assert.deepEqual(I.spark({ rnd: seq(0.1, 0.2, 0.3) }), I.spark({ rnd: seq(0.1, 0.2, 0.3) }));
});
