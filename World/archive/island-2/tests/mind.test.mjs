// Tests for Honk's mind (World/honk-mind.js). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as Mind from '../honk-mind.js';

const calm = { curiosity: 0.6, energy: 0.8, joy: 0.6, comfort: 0.6, calm: 0.7 };

test('a goal said in other words is the same goal', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, "Understand the sparkling pond's behavior and purpose better", '', calm, 0);
  for (const g of ['Discover the purpose and nature of the sparkling pond', 'Find out more about the sparkling pond and its purpose'])
    assert.equal(Mind.proposeGoal(G, g, '', calm, 10).verdict, 'same');
  assert.equal(G.ideas.length, 0);
  Mind.setSteps(G.now, ['Look for a flat, open area near the far island']);
  assert.equal(Mind.proposeGoal(G, 'find a flat, open area near the far island', '', calm, 20).verdict, 'same');   // one of its own steps
  assert.equal(G.ideas.length, 0);
});

test('a passing idea is set aside while he is content and committed', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, 'build a comfy chair for my desk', '', calm, 0);
  const r = Mind.proposeGoal(G, 'learn how clouds float', '', calm, 30);
  assert.equal(r.verdict, 'park');
  assert.equal(G.now.text, 'build a comfy chair for my desk');
  assert.equal(G.ideas[0].text, 'learn how clouds float');
});

test('strong feelings (bored, stuck, restless) win over commitment', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, 'build a comfy chair for my desk', '', calm, 0);
  G.now.setbacks = 4;
  const r = Mind.proposeGoal(G, 'learn how clouds float', 'it keeps nagging me', { ...calm, joy: 0.15, curiosity: 0.95 }, 600);
  assert.equal(r.verdict, 'switch');
  assert.equal(G.now.text, 'learn how clouds float');
});

test('steps advance only when the previous action was for the goal', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, 'make a music toy', '', calm, 0);
  Mind.setSteps(G.now, ['search how sound works', 'write a first program']);
  assert.equal(Mind.progress(G, { forGoal: true, lastForGoal: false, report: 'step done' }, 5), null);
  assert.equal(Mind.progress(G, { forGoal: true, lastForGoal: true, report: 'step done' }, 10).event, 'step');
  assert.equal(Mind.currentStep(G.now).text, 'write a first program');
  assert.equal(Mind.progress(G, { forGoal: true, lastForGoal: true, report: 'step done' }, 20).event, 'plan');
});

test('breaks do not count as distraction, but drifting away does', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, 'make a music toy', '', calm, 0);
  for (let i = 0; i < 10; i++) Mind.progress(G, { brk: true }, i);
  assert.equal(G.now.drift, 0);
  let r = null;
  for (let i = 0; i < 12 && !r?.event; i++) r = Mind.progress(G, { forGoal: false }, 600 + i * 30);
  assert.equal(r.event, 'slipped');
  assert.equal(G.now, null);
});

test('a goal he keeps getting stuck on gets rethought, then let go', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, 'understand what the sparkling pond is', '', calm, 0);
  Mind.setSteps(G.now, ['look at it closely']);
  const events = [];
  for (let i = 1; i < 30 && G.now; i++) events.push(Mind.progress(G, { forGoal: true, lastForGoal: true, report: 'stuck' }, i * 60)?.event);
  assert.ok(events.includes('replan'));
  assert.equal(G.now, null);
  assert.equal(G.ideas[0].text, 'understand what the sparkling pond is');   // he worked on it, so it waits as unfinished
});

test('picking a set-aside goal up again keeps its progress', () => {
  const G = Mind.freshGoals();
  Mind.proposeGoal(G, 'make a music toy', '', calm, 0);
  Mind.setSteps(G.now, ['a', 'b', 'c']);
  Mind.progress(G, { forGoal: true, lastForGoal: true, report: 'step done' }, 10);
  G.now.work = 5;
  Mind.proposeGoal(G, 'learn about clouds', '', { ...calm, joy: 0.1, curiosity: 1 }, 2000);
  Mind.finish(G, 2100);
  const r = Mind.proposeGoal(G, 'make my music toy', '', calm, 2200);
  assert.equal(r.verdict, 'adopt'); assert.ok(r.resumed);
  assert.equal(Mind.stepsDone(G.now), 1);
});

test('familiar things lose their pull and recover after a while', () => {
  const A = {};
  assert.equal(Mind.salience(A, 'human', 0), 1);
  for (let i = 0; i < 8; i++) Mind.expose(A, 'human', i * 10);
  const s = Mind.salience(A, 'human', 80);
  assert.ok(s < 0.25, `salience ${s}`);
  assert.ok(Mind.salience(A, 'human', 80 + 1440 * 3) > s * 2);
  assert.ok(Mind.watcherWindow(A, 80) < 10);
  assert.equal(Mind.watcherWindow({}, 0), Mind.MIND_CONFIG.watcherWindowMin);
});

test('journal: notes every few hours, sooner after something big, never back to back', () => {
  const J = { lastAt: 0, lastEvents: 0 };
  assert.equal(Mind.journalDue(J, 30, 20, true), false);    // too soon
  assert.equal(Mind.journalDue(J, 90, 3, true), true);      // a milestone after an hour
  assert.equal(Mind.journalDue(J, 120, 20, false), false);  // ordinary: wait the full three hours
  assert.equal(Mind.journalDue(J, 181, 8, false), true);
  assert.equal(Mind.journalDue(J, 181, 2, false), false);   // nothing to write about
});

test('an interest kept up for two days becomes a hobby, and fades when dropped', () => {
  const H = {};
  Mind.updateHobbies(H, { drawing: 8, rocks: 7 }, 1);
  assert.deepEqual(Mind.updateHobbies(H, { drawing: 9 }, 2).fresh, ['drawing']);
  assert.deepEqual(Mind.hobbyList(H), ['drawing']);
  assert.deepEqual(Mind.updateHobbies(H, { drawing: 1 }, 6).faded, ['drawing']);
});

test('wishes are kept once', () => {
  const G = Mind.freshGoals();
  assert.ok(Mind.wish(G, 'a GitHub account to put my programs on', 0));
  assert.ok(!Mind.wish(G, 'a GitHub account for my programs', 5));
  assert.ok(!Mind.wish(G, 'none', 5));
});

test('the watcher never becomes a goal, a step, a wish or an interest', () => {
  const G = Mind.freshGoals();
  assert.equal(Mind.proposeGoal(G, 'Understand the floating light and what it wants', '', calm, 0).verdict, 'none');
  assert.equal(Mind.proposeGoal(G, 'find out why the human keeps watching me', '', calm, 0).visitor, true);
  assert.equal(G.now, null);
  assert.equal(Mind.proposeGoal(G, 'learn how humans sleep', '', calm, 0).verdict, 'adopt');   // people in general are fair game
  Mind.setSteps(G.now, ['search how people rest', 'watch what the human is doing', 'write it down']);
  assert.deepEqual(G.now.steps.map(s => s.text), ['search how people rest', 'write it down']);
  assert.equal(Mind.wish(G, 'a way to talk to the floating light', 0), false);
  assert.equal(Mind.withoutVisitor('I love the grass. The floating light watched me. I slept well.'), 'I love the grass. I slept well.');
});

test('old saves lose every plan that was about the watcher', () => {
  const G = Mind.freshGoals(), interests = { 'floating light': 9, rocks: 2 };
  Mind.proposeGoal(G, 'work out what the floating light is', '', calm, 0);   // slips past: the guard is new, the save is old
  G.now = Mind.newGoal('watch the floating light', '', 0);
  G.ideas.push({ text: 'ask the floating light something', since: 0 }, { text: 'build a lamp', since: 0 });
  assert.equal(Mind.purgeVisitor(G, interests), true);
  assert.equal(G.now, null);
  assert.deepEqual(G.ideas.map(i => i.text), ['build a lamp']);
  assert.deepEqual(Object.keys(interests), ['rocks']);
});

test('he is a maker: study goals are spotted, and a long run of research is called out', () => {
  assert.equal(Mind.isStudy('Understand how clouds float'), true);
  assert.equal(Mind.isStudy('Learn JavaScript by writing a small game'), false);
  assert.equal(Mind.isStudy('Build a cloud toy'), false);
  const G = Mind.freshGoals();
  assert.equal(Mind.proposeGoal(G, 'find out how music works', '', calm, 0).goal.study, true);
  assert.equal(Mind.studyRun(['code', 'search', 'read']), 2);
  assert.equal(Mind.studyRun(['search', 'rest', 'read', 'look', 'think']), 4);   // breaks do not interrupt
  assert.equal(Mind.studyRun(['search', 'read', 'look', 'build']), 0);          // making resets it
  assert.equal(Mind.studyRun(['search', 'read', 'look', 'wander']), 0);
});

test('"false" and "null" are not goals, and a junk goal in an old save is dropped', () => {
  const G = Mind.freshGoals();
  for (const x of ['false', 'null', 'None.', false, undefined]) assert.equal(Mind.proposeGoal(G, x, '', calm, 0).verdict, 'none');
  G.now = Mind.newGoal('false', '', 0);
  assert.equal(Mind.purgeVisitor(G, {}), true);
  assert.equal(G.now, null);
  assert.equal(Mind.wish(G, 'false', 0), false);
});

// ---------------------------------------------------------------- everyday life without the model

const things = [{ word: 'flower', d: 2, seen: false, verbs: [{ detail: 'smell it' }] }, { word: 'tree', d: 3, seen: true, verbs: [{ detail: 'lean on it', like: 0.4 }, { detail: 'climb it', like: -0.3 }] }];
const life = (over = {}) => ({ feel: calm, explored: 40, here: 'the desk', places: ['the desk', 'the pond'], recent: [], focus: '', things, ...over });
const mid = () => 0.5;

test('the model is asked for goal work, for news, and after a while with nothing to aim at', () => {
  assert.equal(Mind.attention({ online: false, goal: true, news: true, run: 9, feel: calm }), '');   // no model: life goes on
  assert.equal(Mind.attention({ online: true, goal: true, news: false, run: 0, feel: calm }), 'goal');
  assert.equal(Mind.attention({ online: true, goal: false, news: true, run: 0, feel: calm }), 'news');
  assert.equal(Mind.attention({ online: true, goal: false, news: false, run: Mind.LIFE.idleRun - 1, feel: calm }), '');
  assert.equal(Mind.attention({ online: true, goal: false, news: false, run: Mind.LIFE.idleRun, feel: calm }), 'idle');
});

test('a worn-out body comes before the goal, but only briefly', () => {
  const tired = { ...calm, energy: 0.2 };
  assert.equal(Mind.attention({ online: true, goal: true, news: false, run: 0, feel: tired }), '');
  assert.equal(Mind.attention({ online: true, goal: true, news: false, run: Mind.LIFE.careRun, feel: tired }), 'goal');
});

test('everyday life: new things first, never what felt bad, rest when worn out', () => {
  const c = Mind.routine(life(), mid);
  assert.equal(c[0].action, 'wander');                                    // poking at things comes after seeing more of his world
  const poke = c.filter(x => ['look', 'use'].includes(x.action));
  assert.equal(poke[0].action, 'look'); assert.equal(poke[0].target, 'flower');
  assert.ok(!c.some(x => x.detail === 'climb it'));                       // it hurt last time
  assert.ok(c.some(x => x.detail === 'lean on it'));
  const worn = Mind.routine(life({ feel: { ...calm, energy: 0.05, comfort: 0.1, curiosity: 0.1 }, things: [] }), mid);
  assert.equal(worn[0].action, 'rest');
});

test('he stays with the thing he is finding out about, and does not repeat himself', () => {
  const two = [{ word: 'pond', d: 6, seen: true, verbs: [{ detail: 'splash in it' }] }, { word: 'bush', d: 1, seen: true, verbs: [{ detail: 'smell it' }] }];
  const use = c => c.filter(x => x.action === 'use');
  assert.equal(use(Mind.routine(life({ things: two }), mid))[0].target, 'bush');                     // nearer
  assert.equal(use(Mind.routine(life({ things: two, focus: 'pond' }), mid))[0].target, 'pond');      // but he was busy with the pond
  const liked = [{ word: 'tree', d: 1, seen: true, verbs: [{ detail: 'lean on it', like: 0.3 }] }];
  const again = Mind.routine(life({ things: liked, explored: 100, feel: { ...calm, curiosity: 0.2 } }), mid);
  const worn = Mind.routine(life({ things: liked, explored: 100, feel: { ...calm, curiosity: 0.2 }, recent: ['use tree', 'use tree', 'use tree'] }), mid);
  const u = c => c.find(x => x.key === 'use tree').u;
  assert.ok(again.slice(0, 3).some(x => x.key === 'use tree')); assert.notEqual(worn[0].key, 'use tree');
  assert.ok(u(worn) < u(again) - 0.9);                                                           // the same thing three times: worn right out
  assert.ok(['look', 'use', 'wander', 'rest'].includes(Mind.pickRoutine(again, mid).action));
});

test('a thought he has just had is not voiced again', () => {
  const th = [{ m: 100, text: 'Exploring feels exciting, I wonder what I can find.' }];
  assert.equal(Mind.freshThought(th, 'Exploring feels exciting! I wonder what I will find.', 130), false);
  assert.equal(Mind.freshThought(th, 'The pond water is colder than I expected.', 130), true);
  assert.equal(Mind.freshThought(th, 'Exploring feels exciting, I wonder what I can find.', 100 + Mind.LIFE.quietMin + 1), true);   // long ago
});
