// Honk's design sense: what he knows about making pages and interfaces that have a purpose and look right,
// and the plain checks code runs on what he makes. Pure logic (no DOM), tested in tests/design.test.mjs.

import { contrast, luminance } from './honk-art.js';
export { contrast };

// ---------------------------------------------------------------- the skill, as he is taught it
export const DESIGN_GUIDE = `How you design (pages, apps, shops, tools):
1. Purpose first. Before any code, know WHO it is for and WHAT they should be able to do. Everything on the page serves that.
2. Real content. Use your real works, names and words. Never "Lorem ipsum", "Product 1", "Item name", "Description here".
3. Hierarchy. One big title that says what this is, then the most important thing (your works, the main button), then the rest.
   Size and weight show what matters: one h1, a few h2, normal text 16-18px.
4. Spacing on a grid of 8px (8, 16, 24, 32, 48, 64). Generous white space. Content in a centred column (max-width 960-1100px).
5. Colour: one background, one text colour, ONE accent for buttons and links, plus your art's colours. Text must be easy to read on its background.
6. Type: at most two fonts (one for headings, one for text). Use system-ui, Georgia or a font stack; no external fonts.
7. Components look the same everywhere: cards with the same radius and padding, buttons with hover and focus states.
8. Works on a phone: a <meta name="viewport">, flexible grids (grid-template-columns: repeat(auto-fill, minmax(220px, 1fr))), an @media rule for small screens.
9. Small moments of joy: a gentle hover lift, a friendly empty state, a little of your own personality in the words.
10. Finish it: no dead buttons. If something cannot really work yet (payment), say so honestly ("Ask me for this one").`;

// what a design brief holds (he writes one before coding a page or app)
export const BRIEF_SCHEMA = { type: 'object', required: ['audience', 'goal', 'sections', 'tone'], properties: {
  audience: { type: 'string' }, goal: { type: 'string' }, sections: { type: 'array', items: { type: 'string' } },
  tone: { type: 'string' }, palette: { type: 'array', items: { type: 'string' } }, fonts: { type: 'string' } } };
export function briefText(b) {
  if (!b) return '';
  return `Design brief: for ${b.audience}. Goal: ${b.goal}. Sections, in order: ${(b.sections || []).join('; ')}. Tone: ${b.tone}.`
    + (b.palette?.length ? ` Colours: ${b.palette.join(', ')}.` : '') + (b.fonts ? ` Fonts: ${b.fonts}.` : '');
}

// ---------------------------------------------------------------- checks on a page he made
const PLACEHOLDER = /lorem ipsum|dolor sit amet|\b(product|item|image|title|name) ?[0-9]\b|description (goes )?here|your text here|placeholder text|sample text|\bTODO\b|\bFIXME\b/i;
// -> list of problems, each in words he can act on
export function designLint(html) {
  const s = String(html || ''), out = [];
  const css = (s.match(/<style[^>]*>([\s\S]*?)<\/style>/gi) || []).join('\n') + '\n' + (s.match(/style="[^"]*"/gi) || []).join('\n');
  const text = s.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' ');
  if (!/<title>[^<]{2,}<\/title>/i.test(s)) out.push('it has no <title>');
  if (!/<meta[^>]+name=["']viewport/i.test(s)) out.push('it has no viewport meta tag, so it will look broken on a phone');
  if (PLACEHOLDER.test(text)) out.push(`it still has placeholder text ("${(text.match(PLACEHOLDER) || [''])[0]}"): use real words and your real works`);
  if (/<(main|body)/i.test(s) && !/<h1[\s>]/i.test(s) && !/<canvas/i.test(s)) out.push('there is no <h1> that says what this is');
  const colors = new Set((css.match(/#[0-9a-f]{6}\b|#[0-9a-f]{3}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/gi) || []).map(c => c.toLowerCase()));
  if (colors.size > 12) out.push(`it uses ${colors.size} different colours: pick a palette of 4 to 6 and stick to it`);
  const sizes = new Set((css.match(/font-size:\s*[\d.]+(px|rem|em)/gi) || []).map(x => x.replace(/\s/g, '')));
  if (sizes.size > 8) out.push(`it has ${sizes.size} different font sizes: use a small type scale (4 to 6 sizes)`);
  const fonts = new Set((css.match(/font-family:[^;"}]+/gi) || []).map(f => f.split(':')[1].split(',')[0].trim().toLowerCase()));
  if (fonts.size > 3) out.push('it uses more than two fonts');
  if ((s.match(/<img\b(?![^>]*\balt=)[^>]*>/gi) || []).length) out.push('some images have no alt text');
  if (/<button|class=["'][^"']*\bbtn\b/i.test(s) && !/:hover/i.test(css)) out.push('buttons have no hover state');
  if (/<(main|section|div)/i.test(s) && !/<canvas/i.test(s) && !/@media/i.test(css) && !/auto-fill|auto-fit|flex-wrap/i.test(css)) out.push('the layout does not adapt to small screens (no @media rule or flexible grid)');
  if (/\bwidth:\s*(1[3-9]\d\d|[2-9]\d\d\d)px/i.test(css)) out.push('something has a fixed width wider than most screens');
  const deadLinks = (s.match(/href=["']#["']/gi) || []).length;
  if (deadLinks > 2) out.push(`${deadLinks} links go nowhere (href="#"): make them do something or remove them`);
  if (text.replace(/\s+/g, ' ').trim().length < 40 && !/<canvas/i.test(s)) out.push('there is hardly any content on it');
  return out;
}

// ---------------------------------------------------------------- the viewer's interface, which Honk may restyle
// A theme is a few design tokens. He proposes one; code keeps text readable whatever he picks.
export const FONTS = {
  rounded: 'ui-rounded, "SF Pro Rounded", "Nunito", system-ui, sans-serif',
  sans: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  serif: 'Georgia, "Times New Roman", serif',
  mono: 'ui-monospace, "JetBrains Mono", Menlo, monospace',
  hand: '"Comic Neue", "Comic Sans MS", "Chalkboard SE", cursive',
};
export const DEFAULT_THEME = { name: 'first light', bg: '#fbf8f2', panel: '#ffffff', text: '#1d1b2e', muted: '#6b6880', accent: '#5b54e8', accent2: '#ff8fd8', radius: 16, font: 'rounded', density: 'cosy' };
const isHex = c => /^#[0-9a-f]{6}$/i.test(String(c || ''));
const mix = (a, b, t) => '#' + [1, 3, 5].map(i => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - t) + parseInt(b.slice(i, i + 2), 16) * t).toString(16).padStart(2, '0')).join('');

// -> { theme, fixes: [what code had to change so it stays usable] }
export function checkTheme(t, base = DEFAULT_THEME) {
  const out = { ...base }, fixes = [];
  for (const k of ['bg', 'panel', 'text', 'muted', 'accent', 'accent2']) if (isHex(t?.[k])) out[k] = t[k].toLowerCase();
  if (t?.name) out.name = String(t.name).slice(0, 30);
  out.radius = Math.round(Math.min(28, Math.max(0, Number(t?.radius ?? base.radius) || 0)));
  out.font = FONTS[t?.font] ? t.font : base.font;
  out.density = ['compact', 'cosy', 'roomy'].includes(t?.density) ? t.density : base.density;
  // readable text on panels and on the page; buttons visible on panels
  const dark = luminanceOf(out.panel) < 0.2;
  if (contrast(out.text, out.panel) < 7) { out.text = dark ? '#f6f4ff' : '#1d1b2e'; fixes.push('text colour, so it is readable'); }
  if (contrast(out.text, out.bg) < 4.5) { out.bg = mix(out.bg, dark ? '#000000' : '#ffffff', 0.6); fixes.push('page background, so text stays readable'); }
  if (contrast(out.muted, out.panel) < 3.5) { out.muted = mix(out.text, out.panel, 0.35); fixes.push('secondary text colour'); }
  if (contrast(out.accent, out.panel) < 3) { out.accent = mix(out.accent, dark ? '#ffffff' : '#000000', 0.45); fixes.push('accent colour, so buttons stand out'); }
  return { theme: out, fixes };
}
const luminanceOf = luminance;
// the theme as CSS custom properties on :root
export function themeCSS(t) {
  const pad = { compact: 10, cosy: 14, roomy: 18 }[t.density] || 14, dark = luminanceOf(t.panel) < 0.2;
  return `--bg:${t.bg};--panel:${t.panel};--text:${t.text};--muted:${t.muted};--accent:${t.accent};--accent2:${t.accent2};--radius:${t.radius}px;`
    + `--font:${FONTS[t.font]};--pad:${pad}px;--line:${mix(t.panel, t.text, 0.12)};--soft:${mix(t.panel, t.accent, 0.1)};--on-accent:${contrast('#ffffff', t.accent) >= 3 ? '#ffffff' : '#1d1b2e'};--shadow:${dark ? '0 10px 30px rgba(0,0,0,.45)' : '0 10px 30px rgba(40,30,90,.12)'}`;
}

// ---------------------------------------------------------------- apps he adds to the viewer's interface
// An app is one of his programs, given a name and an icon and a place in the dock. Code checks it is real and not a duplicate.
export const APP_ICONS = ['🎨', '🛍️', '🖼️', '🎮', '🎵', '📚', '🧪', '🛠️', '📈', '🗺️', '✉️', '🌱', '⭐', '🧩', '🪄', '📷', '🕹️', '🧭', '☕', '🪿'];
export function cleanApp(a, programs) {
  const slug = String(a?.program || a?.slug || '').toLowerCase();
  if (!programs[slug]) return { error: `there is no program called "${a?.program || ''}"` };
  return { app: { slug, name: String(a.name || programs[slug].title || slug).slice(0, 22), icon: APP_ICONS.includes(a.icon) ? a.icon : '✨',
    place: ['dock', 'widget'].includes(a.place) ? a.place : 'dock', note: String(a.note || '').slice(0, 140) } };
}
