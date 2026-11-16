# Honk: rules for agents

- Keep Honk's look. The interface (panels, colours, fonts, layout) and the world's rendering (the island and its dither/pixel shader) in `World/main-hub.html` stay exactly as they are. Add features inside the existing UI and style; never rewrite the page or swap in a new look unless the user asks for it.
- Old scenes are kept, read-only, in `World/archive/` (`island/` is a snapshot of the island, `grid-town/` is the abandoned flat-grid town).
