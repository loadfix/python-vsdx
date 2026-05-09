# Features

`loadfix/python-vsdx` is a from-scratch Microsoft Visio (`.vsdx`)
authoring library for the loadfix OOXML family, anchored on the
`python-ooxml-opc`, `python-ooxml-xmlchemy`, `python-ooxml-docprops`,
and `python-ooxml-shared-drawingml` shared packages. Pre-alpha — the
public API is unstable until the round-trip fidelity harness runs
green against the Microsoft-generated fixture set.

This document is a running catalogue of what the library can do
today. Each section covers one feature area; see the accompanying
[CHANGELOG.md](CHANGELOG.md) for the per-release delta and
pointers into the scoping docs for the in-flight tracks.

## Themes

DrawingML theme parts (`/visio/theme/theme%d.xml`) are surfaced as
the [`Theme`](src/vsdx/theme.py) proxy. Visio-authored packages
always carry at least the document-scoped default theme (usually
the upstream Office theme: `name="Office Theme"`); per-page theme
overrides — pages with a direct `RT.THEME` rel to a separate
`ThemePart` — are supported read-and-write.

### `vsdx.Theme`

- **`.name`** — the theme's `@name` attribute (read/write).
- **`.color_scheme`** — a [`ColorScheme`](src/vsdx/theme.py) proxy
  over `<a:clrScheme>`, or `None` when the theme has no scheme.
- **`.font_scheme`** — a [`FontScheme`](src/vsdx/theme.py) proxy
  over `<a:fontScheme>`, or `None` when absent.
- **`.color(slot)` / `.set_color(slot, rgb)`** — flat read/write
  accessors for the twelve canonical colour slots (`dk1` / `lt1` /
  `dk2` / `lt2` / `accent1`–`accent6` / `hlink` / `folHlink`).
  `.color` returns six-hex-digit RGB strings for `<a:srgbClr>` slots
  and `None` otherwise; use `.color_slot(slot)` to reach the raw
  lxml element for `<a:sysClr>` / `<a:schemeClr>` inspection.
- **`.major_latin_typeface` / `.set_major_latin_typeface(tf)`** —
  `<a:majorFont>/<a:latin @typeface>` (headings).
- **`.minor_latin_typeface` / `.set_minor_latin_typeface(tf)`** —
  `<a:minorFont>/<a:latin @typeface>` (body text).

### `vsdx.ColorScheme`

Dotted-attribute proxy over the colour scheme element. Each slot
property returns:

- the six-hex-digit uppercase `@val` when the slot wraps an
  `<a:srgbClr>` (e.g. `"1F497D"`);
- the raw `@val` when the slot wraps an `<a:sysClr>` (e.g.
  `"windowText"` / `"window"` — Office's default for `dk1` / `lt1`);
- `None` when the slot is missing or wraps a `<a:schemeClr>`.

Exposes `.name`, `.dk1`, `.lt1`, `.dk2`, `.lt2`, `.accent1` through
`.accent6`, `.hlink`, `.folHlink`.

### `vsdx.FontScheme`

Dotted-attribute proxy over the font scheme element. Exposes
`.name`, `.major_font`, `.minor_font` — the latter two are internal
`_ThemeFont` proxies carrying `.latin_typeface` over
`<a:latin @typeface>`.

### `vsdx.VisioDocument.theme` / `.themes`

- **`.theme`** — the theme related from the document part (the
  package-wide default), or `None` if the package has no theme.
- **`.themes`** — every `ThemePart` in the package, wrapped as
  `Theme`, in package-iteration order. Packages built via
  `vsdx.Visio()` return `[]` until seed-template injection lands.

### `vsdx.Page.theme`

Getter returns the theme effective on this page:

1. the per-page override (when the page part carries a direct
   `RT.THEME` rel to a `ThemePart`);
2. the document-wide `VisioDocument.theme` otherwise;
3. `None` when the package has no theme at all.

Setter:

- `page.theme = some_theme` — establish (or replace) the `RT.THEME`
  rel from the page part to `some_theme.part`. Any existing
  override rel is dropped first.
- `page.theme = None` — remove any override rel so the page
  inherits the document theme again. No-op when no override
  existed.
- Any other value raises `TypeError`.

### Round-trip fidelity

Theme mutations propagate into the part blob on the next save
(`Theme.set_color`, `Theme.set_*_latin_typeface`, `Theme.name`).
Unmodified theme parts round-trip byte-identical to the on-disk
blob — the lazy re-parse only kicks in after the proxy has touched
the tree. DrawingML namespaces are preserved across the round
trip.

---

Sections for other feature areas (pages, shapes, masters, layers,
text, connectors, hyperlinks, print setup, data graphics, scale,
kind variants, templates, stencils, VBA passthrough, …) will be
filled in as the 0.3.0 authoring surface stabilises. Until then
see [CHANGELOG.md](CHANGELOG.md) and the per-package `CLAUDE.md`.
