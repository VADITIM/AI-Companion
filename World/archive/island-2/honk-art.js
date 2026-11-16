// How Honk draws: he writes a small JSON recipe, code turns it into a clean SVG picture.
// Pure logic (no DOM), tested in tests/art.test.mjs.
//
// Why a recipe and not free drawing code: a 7B model asked to "draw a butterfly" in canvas code gets the coordinates wrong
// and the result looks like coloured dots. Here he picks MOTIFS (a butterfly, a cat, a flower...) that code draws properly,
// places them on a 100 x 100 canvas, and adds his own shapes around them. Symmetry ("mirror"), repetition ("ring") and a
// shared palette and outline make even a simple recipe look like one deliberate picture.

export const W = 100, H = 100;
const clamp = (x, lo, hi, d) => { x = Number(x); return Number.isFinite(x) ? Math.min(hi, Math.max(lo, x)) : d; };
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const f1 = n => Math.round(n * 100) / 100;

// named colours he can use besides his own palette (hex is fine too)
export const COLORS = {
  ink: '#1a1040', night: '#241a5c', indigo: '#4b47d6', violet: '#7a5cff', lilac: '#c9c2ff', pink: '#ff8fd8', rose: '#ff5c8a',
  red: '#e8453c', orange: '#ff9a3c', peach: '#ffb36b', yellow: '#ffd23f', cream: '#fff4d6', white: '#ffffff', mint: '#7ff0c6',
  green: '#3fbf6f', leaf: '#2e8b57', teal: '#1fa7a0', sky: '#9fd8ff', blue: '#3a7bd5', navy: '#1a2a6c', brown: '#8a5a3c',
  sand: '#e9c79a', grey: '#9a98a8', black: '#14121c',
};
export const SHAPES = ['circle', 'ellipse', 'rect', 'poly', 'line', 'star', 'blob', 'text'];
const hexOk = c => /^#[0-9a-f]{6}$/i.test(c);
const hex3 = c => /^#[0-9a-f]{3}$/i.test(c) ? '#' + [...c.slice(1)].map(x => x + x).join('') : c;
function colorOf(c, palette, d = COLORS.ink) {
  if (c == null || c === '') return d;
  if (typeof c === 'number') return palette[Math.abs(Math.round(c)) % palette.length] || d;
  c = hex3(String(c).trim().toLowerCase());
  const pi = c.match(/^p(\d)$/); if (pi) return palette[+pi[1]] || d;
  if (hexOk(c)) return c;
  return COLORS[c.replace(/[^a-z]/g, '')] || d;
}

// ---------------------------------------------------------------- motifs: things code knows how to draw well
// Each motif returns primitives around (0, 0) with a size of about 1 (from -0.5 to 0.5). c = main colour, a = accent, k = ink.
const E = (cx, cy, rx, ry, fill, rot = 0, o = {}) => ({ t: 'ellipse', cx, cy, rx, ry, fill, rot, ...o });
const Cc = (cx, cy, r, fill, o = {}) => ({ t: 'circle', cx, cy, r, fill, ...o });
const P = (pts, fill, o = {}) => ({ t: 'poly', pts, fill, ...o });
const L = (pts, stroke, w = 0.02, o = {}) => ({ t: 'line', pts, stroke, w, ...o });
const R = (x, y, w, h, fill, rx = 0, o = {}) => ({ t: 'rect', x, y, w, h, fill, rx, ...o });
const both = f => [f(1), f(-1)];   // left and right copies

export const MOTIFS = {
  butterfly: (c, a, k) => [
    ...both(s => E(s * 0.22, -0.13, 0.24, 0.17, c, s * -28)),                  // upper wings, tilted out
    ...both(s => E(s * 0.17, 0.13, 0.15, 0.12, c, s * 30)),                    // lower wings, smaller
    ...both(s => Cc(s * 0.27, -0.16, 0.065, a, { line: false })),             // wing spots
    ...both(s => Cc(s * 0.18, 0.15, 0.04, a, { line: false })),
    E(0, 0.0, 0.035, 0.24, k),                                                  // long thin body
    Cc(0, -0.25, 0.045, k),                                                     // head
    ...both(s => L([[s * 0.02, -0.28], [s * 0.09, -0.42], [s * 0.12, -0.44]], k, 0.018)),   // antennae
    ...both(s => Cc(s * 0.12, -0.44, 0.02, k)),
  ],
  flower: (c, a, k) => [
    L([[0, 0], [0.02, 0.25], [0, 0.5]], COLORS.leaf, 0.04),                   // stem
    E(0.09, 0.3, 0.09, 0.04, COLORS.green, -30), E(-0.08, 0.38, 0.08, 0.035, COLORS.green, 30),
    ...Array.from({ length: 8 }, (_, i) => { const t = i * Math.PI / 4; return E(Math.cos(t) * 0.15, Math.sin(t) * 0.15 - 0.1, 0.11, 0.06, c, t * 180 / Math.PI); }),
    Cc(0, -0.1, 0.08, a),
  ],
  cat: (c, a, k) => [
    E(0, 0.22, 0.3, 0.24, c),                                                   // body
    P([[0.22, 0.35], [0.45, 0.2], [0.42, 0.1], [0.24, 0.24]], c),               // tail
    Cc(0, -0.15, 0.24, c),                                                      // head
    ...both(s => P([[s * 0.08, -0.3], [s * 0.21, -0.48], [s * 0.24, -0.24]], c)),   // ears
    ...both(s => P([[s * 0.13, -0.31], [s * 0.2, -0.41], [s * 0.21, -0.27]], a, { line: false })),
    ...both(s => E(s * 0.09, -0.16, 0.035, 0.05, k)),                           // eyes
    ...both(s => Cc(s * 0.08, -0.18, 0.012, COLORS.white, { line: false })),
    P([[-0.025, -0.08], [0.025, -0.08], [0, -0.05]], a),                        // nose
    ...both(s => L([[s * 0.05, -0.06], [s * 0.26, -0.09]], k, 0.01)), ...both(s => L([[s * 0.05, -0.05], [s * 0.25, -0.02]], k, 0.01)),
  ],
  bird: (c, a, k) => [
    E(0, 0.05, 0.3, 0.22, c), Cc(0.22, -0.13, 0.15, c),
    P([[0.35, -0.15], [0.5, -0.11], [0.35, -0.08]], a),                         // beak
    Cc(0.26, -0.16, 0.03, k),
    E(-0.06, 0.03, 0.17, 0.1, a, -15),                                          // wing
    P([[-0.28, 0.0], [-0.48, -0.1], [-0.45, 0.12]], c),                         // tail
    L([[0.0, 0.26], [0.0, 0.4]], COLORS.orange, 0.025), L([[0.08, 0.25], [0.08, 0.4]], COLORS.orange, 0.025),
  ],
  fish: (c, a, k) => [
    E(0, 0, 0.32, 0.19, c), P([[-0.28, 0], [-0.5, -0.17], [-0.5, 0.17]], c),
    P([[-0.05, -0.17], [0.08, -0.3], [0.12, -0.15]], a),
    E(-0.02, 0, 0.05, 0.12, a, 0, { line: false }), Cc(0.18, -0.04, 0.035, k), Cc(0.19, -0.05, 0.01, COLORS.white, { line: false }),
  ],
  tree: (c, a, k) => [
    R(-0.06, 0.05, 0.12, 0.45, COLORS.brown, 0.02),
    Cc(0, -0.15, 0.27, c), Cc(-0.17, 0.0, 0.18, c), Cc(0.17, 0.0, 0.18, c),
    Cc(-0.08, -0.22, 0.04, a, { line: false }), Cc(0.12, -0.08, 0.04, a, { line: false }), Cc(-0.14, 0.02, 0.035, a, { line: false }),
  ],
  sun: (c, a, k) => [
    ...Array.from({ length: 12 }, (_, i) => { const t = i * Math.PI / 6; return L([[Math.cos(t) * 0.3, Math.sin(t) * 0.3], [Math.cos(t) * 0.46, Math.sin(t) * 0.46]], a, 0.04); }),
    Cc(0, 0, 0.25, c),
  ],
  moon: (c, a, k) => [{ t: 'crescent', cx: 0, cy: 0, r: 0.4, fill: c }, Cc(-0.12, -0.1, 0.04, a, { line: false }), Cc(-0.2, 0.12, 0.03, a, { line: false })],
  star: (c, a, k) => [{ t: 'star', cx: 0, cy: 0, r: 0.45, n: 5, fill: c }],
  heart: (c, a, k) => [P(Array.from({ length: 24 }, (_, i) => { const t = i / 24 * Math.PI * 2, x = 16 * Math.sin(t) ** 3, y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t); return [x / 34, -y / 34]; }), c), E(-0.15, -0.15, 0.06, 0.04, a, -30, { line: false })],
  house: (c, a, k) => [
    R(-0.32, -0.05, 0.64, 0.5, c, 0.02), P([[-0.42, -0.03], [0, -0.42], [0.42, -0.03]], a),
    R(-0.08, 0.17, 0.16, 0.28, COLORS.brown, 0.03), R(-0.25, 0.05, 0.12, 0.12, COLORS.sky, 0.01), R(0.13, 0.05, 0.12, 0.12, COLORS.sky, 0.01),
  ],
  mountain: (c, a, k) => [P([[-0.5, 0.4], [-0.1, -0.35], [0.2, 0.4]], c), P([[-0.1, 0.4], [0.25, -0.15], [0.5, 0.4]], c), P([[-0.18, -0.2], [-0.1, -0.35], [-0.02, -0.2], [-0.07, -0.16], [-0.13, -0.18]], a)],
  cloud: (c, a, k) => [Cc(-0.2, 0.05, 0.16, c), Cc(0.0, -0.05, 0.22, c), Cc(0.22, 0.06, 0.15, c), R(-0.2, 0.02, 0.42, 0.18, c, 0.08, { line: false })],
  mushroom: (c, a, k) => [R(-0.09, -0.02, 0.18, 0.4, COLORS.cream, 0.06), { t: 'dome', cx: 0, cy: 0, r: 0.38, fill: c }, Cc(-0.15, -0.14, 0.05, a, { line: false }), Cc(0.1, -0.22, 0.06, a, { line: false }), Cc(0.2, -0.07, 0.04, a, { line: false })],
  leaf: (c, a, k) => [E(0, 0, 0.18, 0.42, c, 20), L([[0.13, 0.35], [-0.13, -0.35]], a, 0.02)],
  goose: (c, a, k) => [   // a little self-portrait
    E(-0.05, 0.15, 0.3, 0.2, c), E(0.16, -0.1, 0.06, 0.2, c, 12), Cc(0.2, -0.27, 0.1, c),
    E(0.32, -0.26, 0.09, 0.035, COLORS.orange), Cc(0.23, -0.29, 0.022, k),
    E(-0.1, 0.12, 0.16, 0.09, a, -10), L([[-0.02, 0.33], [-0.02, 0.45]], COLORS.orange, 0.025), L([[0.08, 0.33], [0.08, 0.45]], COLORS.orange, 0.025),
  ],
};
export const MOTIF_NAMES = Object.keys(MOTIFS);

// ---------------------------------------------------------------- cleaning a recipe the model wrote
// recipe: { title, palette: [hex], background: { colors: [hex, hex?], angle }, ground: { color, height }, outline: 0..3,
//           texture: 'none'|'grain'|'dots'|'paper', layers: [ ... ] }
// a layer: { motif | shape, x, y (0..100), size (motif, 4..90), w, h, r, points, text, color, accent, opacity, rot, mirror: 'x', ring: n }
export function cleanArt(j) {
  if (!j || typeof j !== 'object') return null;
  const palette = (Array.isArray(j.palette) ? j.palette : []).map(c => colorOf(c, [], null)).filter(Boolean).slice(0, 6);
  if (!palette.length) palette.push(COLORS.indigo, COLORS.pink, COLORS.yellow, COLORS.cream);
  const bgIn = j.background || {}, bgc = (Array.isArray(bgIn.colors) ? bgIn.colors : [bgIn.color || bgIn]).map(c => colorOf(c, palette, null)).filter(Boolean).slice(0, 2);
  const art = {
    title: String(j.title || 'untitled').slice(0, 60),
    palette,
    background: { colors: bgc.length ? bgc : [COLORS.cream], angle: clamp(bgIn.angle, 0, 360, 90) },
    ground: j.ground && j.ground.color ? { color: colorOf(j.ground.color, palette), height: clamp(j.ground.height, 0, 60, 25) } : null,
    outline: clamp(j.outline, 0, 3, 1),
    texture: ['none', 'grain', 'dots', 'paper'].includes(j.texture) ? j.texture : 'none',
    layers: [],
  };
  for (const l of (Array.isArray(j.layers) ? j.layers : []).slice(0, 40)) {
    if (!l || typeof l !== 'object') continue;
    const m0 = String(l.motif || '').toLowerCase().trim(), motif = [m0, m0.replace(/ies$/, 'y'), m0.replace(/e?s$/, ''), m0.replace(/s$/, '')].find(x => MOTIFS[x]) || '';
    const shape = String(l.shape || '').toLowerCase();
    const base = { x: clamp(l.x, -10, 110, 50), y: clamp(l.y, -10, 110, 50), color: colorOf(l.color, palette, palette[0]), accent: colorOf(l.accent, palette, palette[1] || COLORS.yellow),
      opacity: clamp(l.opacity, 0.1, 1, 1), rot: clamp(l.rot, -360, 360, 0), mirror: ['x', 'y'].includes(l.mirror) ? l.mirror : '', ring: Math.round(clamp(l.ring, 0, 16, 0)) };
    if (MOTIFS[motif]) art.layers.push({ ...base, motif, size: clamp(l.size, 4, 95, 30) });
    else if (SHAPES.includes(shape)) {
      const L2 = { ...base, shape, w: clamp(l.w ?? l.size, 0.5, 120, 10), h: clamp(l.h ?? l.size, 0.5, 120, 10), r: clamp(l.r ?? (l.size != null ? l.size / 2 : undefined), 0.3, 70, 5) };
      if (shape === 'poly' || shape === 'line') {
        L2.points = (Array.isArray(l.points) ? l.points : []).filter(p => Array.isArray(p) && p.length >= 2).slice(0, 24).map(p => [clamp(p[0], -10, 110, 50), clamp(p[1], -10, 110, 50)]);
        if (L2.points.length < 2 || (shape === 'poly' && L2.points.length < 3)) continue;
        L2.width = clamp(l.width, 0.2, 10, 1);
      }
      if (shape === 'star') L2.n = Math.round(clamp(l.n, 3, 12, 5));
      if (shape === 'text') { L2.text = String(l.text || '').slice(0, 40); if (!L2.text.trim()) continue; L2.size = clamp(l.size, 2, 30, 8); }
      art.layers.push(L2);
    }
  }
  return art.layers.length ? art : null;
}

// every layer after "mirror" and "ring" copies are made (what actually gets drawn)
export function expand(art) {
  const out = [];
  for (const l of art.layers) {
    let copies = [l];
    if (l.ring >= 2) {   // copies around the middle of the canvas, at the layer's distance from it
      const dx = l.x - 50, dy = l.y - 50;
      copies = Array.from({ length: l.ring }, (_, i) => { const t = i * 2 * Math.PI / l.ring, c = Math.cos(t), s = Math.sin(t);
        return { ...l, x: 50 + dx * c - dy * s, y: 50 + dx * s + dy * c, rot: l.rot + t * 180 / Math.PI, points: l.points?.map(([x, y]) => [50 + (x - 50) * c - (y - 50) * s, 50 + (x - 50) * s + (y - 50) * c]) }; });
    }
    if (l.mirror === 'x') copies = copies.flatMap(c => Math.abs(c.x - 50) < 0.5 && !c.points ? [c] : [c, { ...c, x: 100 - c.x, rot: -c.rot, flip: !c.flip, points: c.points?.map(([x, y]) => [100 - x, y]) }]);
    if (l.mirror === 'y') copies = copies.flatMap(c => [c, { ...c, y: 100 - c.y, rot: -c.rot, points: c.points?.map(([x, y]) => [x, 100 - y]) }]);
    out.push(...copies);
  }
  return out.slice(0, 240);
}

// ---------------------------------------------------------------- SVG
function rnd(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
function hashStr(s) { let h = 2166136261; for (const ch of String(s)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return h >>> 0; }
const ptsStr = pts => pts.map(p => f1(p[0]) + ',' + f1(p[1])).join(' ');
function blobPath(cx, cy, r, seed) {
  const R = rnd(seed), n = 7, pts = Array.from({ length: n }, (_, i) => { const t = i / n * Math.PI * 2, rr = r * (0.75 + R() * 0.5); return [cx + Math.cos(t) * rr, cy + Math.sin(t) * rr]; });
  let d = `M${f1((pts[0][0] + pts[1][0]) / 2)},${f1((pts[0][1] + pts[1][1]) / 2)}`;
  for (let i = 1; i <= n; i++) { const p = pts[i % n], q = pts[(i + 1) % n]; d += ` Q${f1(p[0])},${f1(p[1])} ${f1((p[0] + q[0]) / 2)},${f1((p[1] + q[1]) / 2)}`; }
  return d + 'Z';
}
const starPts = (cx, cy, r, n) => Array.from({ length: n * 2 }, (_, i) => { const t = i * Math.PI / n - Math.PI / 2, rr = i % 2 ? r * 0.45 : r; return [cx + Math.cos(t) * rr, cy + Math.sin(t) * rr]; });

// one primitive as SVG. stroke: outline colour and width (0 = none)
function prim(p, sw, ink) {
  const line = p.line === false || sw <= 0 ? '' : ` stroke="${ink}" stroke-width="${f1(sw)}" stroke-linejoin="round"`;
  const rot = p.rot ? ` transform="rotate(${f1(p.rot)} ${f1(p.cx ?? p.x ?? 0)} ${f1(p.cy ?? p.y ?? 0)})"` : '';
  const op = p.opacity != null && p.opacity < 1 ? ` opacity="${f1(p.opacity)}"` : '';
  switch (p.t) {
    case 'circle': return `<circle cx="${f1(p.cx)}" cy="${f1(p.cy)}" r="${f1(p.r)}" fill="${p.fill}"${line}${op}/>`;
    case 'ellipse': return `<ellipse cx="${f1(p.cx)}" cy="${f1(p.cy)}" rx="${f1(p.rx)}" ry="${f1(p.ry)}" fill="${p.fill}"${line}${rot}${op}/>`;
    case 'rect': return `<rect x="${f1(p.x)}" y="${f1(p.y)}" width="${f1(p.w)}" height="${f1(p.h)}" rx="${f1(p.rx || 0)}" fill="${p.fill}"${line}${op}/>`;
    case 'poly': return `<polygon points="${ptsStr(p.pts)}" fill="${p.fill}"${line}${op}/>`;
    case 'line': return `<polyline points="${ptsStr(p.pts)}" fill="none" stroke="${p.stroke}" stroke-width="${f1(p.w)}" stroke-linecap="round" stroke-linejoin="round"${op}/>`;
    case 'star': return `<polygon points="${ptsStr(starPts(p.cx, p.cy, p.r, p.n || 5))}" fill="${p.fill}"${line}${op}/>`;
    case 'blob': return `<path d="${blobPath(p.cx, p.cy, p.r, p.seed)}" fill="${p.fill}"${line}${op}/>`;
    case 'crescent': return `<path d="M${f1(p.cx)},${f1(p.cy - p.r)} A${f1(p.r)},${f1(p.r)} 0 1 0 ${f1(p.cx)},${f1(p.cy + p.r)} A${f1(p.r * 0.5)},${f1(p.r)} 0 0 1 ${f1(p.cx)},${f1(p.cy - p.r)}Z" fill="${p.fill}"${line}${op}/>`;
    case 'dome': return `<path d="M${f1(p.cx - p.r)},${f1(p.cy)} A${f1(p.r)},${f1(p.r * 0.8)} 0 0 1 ${f1(p.cx + p.r)},${f1(p.cy)}Z" fill="${p.fill}"${line}${op}/>`;
    default: return '';
  }
}
// a motif scaled and placed: its primitives are in -0.5..0.5 space, so a <g> transform does the work
function motifSVG(l, sw, ink) {
  const parts = MOTIFS[l.motif](l.color, l.accent, ink), s = l.size;
  const inner = parts.map(p => prim({ ...p, opacity: l.opacity < 1 ? undefined : p.opacity }, sw / s, ink)).join('');
  const flip = l.flip ? ' scale(-1,1)' : '';
  return `<g transform="translate(${f1(l.x)} ${f1(l.y)}) rotate(${f1(l.rot)}) scale(${f1(s)})${flip}"${l.opacity < 1 ? ` opacity="${f1(l.opacity)}"` : ''}>${inner}</g>`;
}
function shapeSVG(l, sw, ink, i) {
  const base = { fill: l.color, opacity: l.opacity, rot: l.rot };
  switch (l.shape) {
    case 'circle': return prim({ t: 'circle', cx: l.x, cy: l.y, r: l.r, ...base }, sw, ink);
    case 'ellipse': return prim({ t: 'ellipse', cx: l.x, cy: l.y, rx: l.w / 2, ry: l.h / 2, ...base }, sw, ink);
    case 'rect': return `<g transform="rotate(${f1(l.rot)} ${f1(l.x)} ${f1(l.y)})">${prim({ t: 'rect', x: l.x - l.w / 2, y: l.y - l.h / 2, w: l.w, h: l.h, rx: Math.min(l.w, l.h) * 0.15, fill: l.color, opacity: l.opacity }, sw, ink)}</g>`;
    case 'poly': return prim({ t: 'poly', pts: l.points, ...base, rot: 0 }, sw, ink);
    case 'line': return prim({ t: 'line', pts: l.points, stroke: l.color, w: l.width, opacity: l.opacity }, 0, ink);
    case 'star': return `<g transform="rotate(${f1(l.rot)} ${f1(l.x)} ${f1(l.y)})">${prim({ t: 'star', cx: l.x, cy: l.y, r: l.r, n: l.n, fill: l.color, opacity: l.opacity }, sw, ink)}</g>`;
    case 'blob': return prim({ t: 'blob', cx: l.x, cy: l.y, r: l.r, seed: hashStr(l.x + ':' + l.y + ':' + i), ...base, rot: 0 }, sw, ink);
    case 'text': return `<text x="${f1(l.x)}" y="${f1(l.y)}" font-family="Georgia, serif" font-weight="700" font-size="${f1(l.size)}" text-anchor="middle" fill="${l.color}"${l.rot ? ` transform="rotate(${f1(l.rot)} ${f1(l.x)} ${f1(l.y)})"` : ''}>${esc(l.text)}</text>`;
    default: return '';
  }
}

export function toSVG(art, { size = 512 } = {}) {
  const ink = COLORS.ink, sw = art.outline * 0.45, [c0, c1] = art.background.colors, a = art.background.angle * Math.PI / 180;
  const gx = f1(50 - Math.cos(a) * 50), gy = f1(50 - Math.sin(a) * 50), gx2 = f1(50 + Math.cos(a) * 50), gy2 = f1(50 + Math.sin(a) * 50);
  const defs = [`<linearGradient id="bg" gradientUnits="userSpaceOnUse" x1="${gx}" y1="${gy}" x2="${gx2}" y2="${gy2}"><stop offset="0" stop-color="${c0}"/><stop offset="1" stop-color="${c1 || c0}"/></linearGradient>`];
  if (art.texture === 'grain' || art.texture === 'paper') defs.push(`<filter id="tx"><feTurbulence type="fractalNoise" baseFrequency="${art.texture === 'grain' ? 0.9 : 0.04}" numOctaves="2" seed="3"/><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 ${art.texture === 'grain' ? 0.18 : 0.12} 0"/></filter>`);
  if (art.texture === 'dots') defs.push(`<pattern id="tx" width="4" height="4" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="0.45" fill="${ink}" opacity="0.12"/></pattern>`);
  const body = [`<rect width="100" height="100" fill="url(#bg)"/>`];
  if (art.ground) body.push(`<path d="M0,${f1(100 - art.ground.height)} Q50,${f1(100 - art.ground.height - 4)} 100,${f1(100 - art.ground.height)} L100,100 L0,100Z" fill="${art.ground.color}"/>`);
  expand(art).forEach((l, i) => body.push(l.motif ? motifSVG(l, sw, ink) : shapeSVG(l, sw, ink, i)));
  if (art.texture === 'dots') body.push('<rect width="100" height="100" fill="url(#tx)"/>');
  else if (art.texture !== 'none') body.push('<rect width="100" height="100" filter="url(#tx)" opacity="1"/>');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${size}" height="${size}"><title>${esc(art.title)}</title><defs>${defs.join('')}</defs>${body.join('')}</svg>`;
}

// ---------------------------------------------------------------- critique: plain checks a picture should pass
export function luminance(hex) {
  const v = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
export const contrast = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

// -> list of problems in words he understands (empty = it is a proper picture)
export function critiqueArt(art) {
  const out = [], els = expand(art), motifs = els.filter(l => l.motif);
  if (els.length < 4) out.push('it is almost empty: add a setting around the subject (ground, sky details, smaller things in the back)');
  if (!motifs.length && els.length < 10) out.push('there is no clear subject: use a motif (or several) as the main thing in the picture');
  const big = els.filter(l => (l.motif ? l.size : Math.max(l.w || 0, l.h || 0, (l.r || 0) * 2)) >= 25);
  if (!big.length) out.push('everything is tiny: make the main subject big (size 30 to 60) and put it near the middle');
  const bg = art.background.colors[0], weak = motifs.filter(l => contrast(l.color, bg) < 1.6);
  if (weak.length) out.push(`the ${weak[0].motif} almost disappears into the background: give it a colour that stands out more`);
  const off = els.filter(l => l.x < -5 || l.x > 105 || l.y < -5 || l.y > 105);
  if (off.length > els.length / 3) out.push('a lot of it is off the edge of the canvas');
  const colors = new Set(els.map(l => l.color));
  if (colors.size > 7) out.push('too many different colours: keep to your palette');
  const centre = els.some(l => Math.abs(l.x - 50) < 30 && Math.abs(l.y - 50) < 30);
  if (!centre) out.push('nothing is near the middle: the composition feels empty');
  return out;
}
export const describeArt = art => {
  const m = [...new Set(art.layers.filter(l => l.motif).map(l => l.motif))];
  return m.length ? m.join(', ') : 'shapes';
};

// ---------------------------------------------------------------- pictures from words (the bots' images, and a fallback)
const WORDS = { butterfly: /butterfl|moth|wing/i, flower: /flower|bloom|garden|petal|rose|daisy|plant/i, cat: /cat|kitten|meow|pet/i, bird: /bird|crow|sparrow|feather|tweet/i,
  fish: /fish|sea|ocean|aquarium|swim/i, tree: /tree|forest|wood|park/i, sun: /sun|summer|morning|bright/i, moon: /moon|night|sleep|dream/i, star: /star|space|cosmic|galaxy/i,
  heart: /love|heart|kind|friend/i, house: /house|home|city|shop|store|build/i, mountain: /mountain|hike|travel|landscape/i, cloud: /cloud|weather|rain|sky/i,
  mushroom: /mushroom|fung|forest floor|mycel/i, leaf: /leaf|autumn|fall|green/i, goose: /goose|honk/i };
export function motifsIn(text) { return Object.entries(WORDS).filter(([, re]) => re.test(text || '')).map(([m]) => m); }

const SCHEMES = [
  ['#ffd6e8', '#c9c2ff', '#4b47d6', '#ffd23f'], ['#1a2a6c', '#4b47d6', '#ffd23f', '#fff4d6'], ['#fff4d6', '#ffb36b', '#e8453c', '#2e8b57'],
  ['#9fd8ff', '#e6f7ff', '#1fa7a0', '#ff8fd8'], ['#241a5c', '#7a5cff', '#7ff0c6', '#ff5c8a'], ['#e9f5db', '#b5e48c', '#3fbf6f', '#ff9a3c'],
];
export function sceneFromWords(text, seed = hashStr(text)) {
  const R = rnd(seed), pick = a => a[Math.floor(R() * a.length)], found = motifsIn(text);
  const main = found[0] || pick(['butterfly', 'flower', 'cat', 'bird', 'fish', 'tree', 'house', 'mushroom', 'star', 'heart']);
  const sch = pick(SCHEMES), night = /night|moon|star|space|dream/i.test(text) || R() < 0.2;
  const bg = night ? ['#241a5c', '#4b47d6'] : [sch[0], sch[1]];
  const layers = [{ motif: main, x: 50, y: 50, size: 48 + R() * 14, color: sch[2], accent: sch[3], rot: (R() - 0.5) * 16 }];
  const extra = found[1] || pick(night ? ['star', 'moon', 'cloud'] : ['cloud', 'sun', 'flower', 'leaf', 'star']);
  layers.push({ motif: extra, x: 18 + R() * 12, y: 18 + R() * 10, size: 14 + R() * 8, color: night ? '#fff4d6' : sch[3], accent: sch[2] });
  if (R() < 0.6) layers.push({ shape: 'circle', x: 82, y: 22, r: 2, color: night ? '#fff4d6' : sch[3], ring: 0, mirror: '' }, { motif: extra, x: 80, y: 26, size: 10, color: night ? '#fff4d6' : sch[3], accent: sch[2] });
  return cleanArt({ title: text.slice(0, 40), palette: sch, background: { colors: bg, angle: 90 }, ground: R() < 0.6 ? { color: night ? '#1a1040' : sch[1], height: 18 } : null, outline: 1, texture: pick(['none', 'grain', 'dots', 'paper']), layers });
}

// what he is told about drawing (in the draw prompt)
export const ART_GUIDE = `How a recipe works: the canvas is 100 x 100 (x to the right, y DOWN; the middle is 50, 50).
- "palette": 3 to 5 colours (hex) that go well together. Use them everywhere ("p0".."p4", or the colour itself).
- "background": {"colors": [top, bottom], "angle": 90}. "ground": {"color", "height": 10..40} for a floor or a hill (leave it out for a sky or a pattern).
- "outline": 0 (none), 1 (thin ink lines, like a picture book) or 2 (bold). "texture": none, grain, dots or paper.
- "layers", drawn in order (first = furthest back). A layer is either a MOTIF, which code draws properly, or a SHAPE.
  Motifs: ${MOTIF_NAMES.join(', ')}. Fields: "motif", "x", "y" (its centre), "size" (4..90), "color", "accent", "rot".
  Shapes: circle (r), ellipse (w, h), rect (w, h), star (r, n), blob (r: a soft organic lump), poly (points: [[x,y],...]), line (points, width), text (text, size). Fields: "x", "y", "color", "opacity", "rot".
  Any layer can have "mirror": "x" (a copy mirrored on the other side of the canvas) or "ring": 3..12 (copies in a circle around the middle).
A good picture: ONE clear subject, big (size 35..65) near the middle; a setting around it (ground, sky, small things in the back); 6 to 20 layers; colours that stand out from the background.`;
