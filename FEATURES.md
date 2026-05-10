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

## Ink annotations

Visio ink annotations ride on the shared
[`python-ooxml-ink`](../python-ooxml-ink/) 0.2 package — the same
InkML-1.0 payload docx (`word/ink/`) and pptx (`ppt/ink/`) emit,
parked under `/visio/ink/ink{n}.xml` and linked from the page part
via the Microsoft ink relationship
(`http://schemas.microsoft.com/office/2010/relationships/ink`).

### `vsdx.Page.ink_strokes`

Flat list of [`InkStroke`](src/vsdx/ink.py) for every `<inkml:trace>`
on this page. Walks every ink relationship on the page part and
enumerates traces in document order. Returns `[]` when the page has
no ink parts.

### `vsdx.Page.add_ink_stroke(points, pressure=None, color=None, width=None)`

Append a stroke to the page and return its `InkStroke` proxy.
Creates — or reuses — a single `/visio/ink/ink{n}.xml` part per page
so repeated `add_ink_stroke` calls group into one file (mirroring how
Office stores strokes drawn in a single "pen-down to pen-up"
sequence). `points` is a list of `(x, y)` pairs or 3-tuples
`(x, y, pressure)`; `color` is hex-RGB; `width` is pixel nib width.

### `vsdx.VisioDocument.ink_strokes`

Flat list of `InkStroke` across every page in the document, in
source-order concatenation.

### `vsdx.InkStroke`

Read proxy over a single `<inkml:trace>`:

- **`.points`** — list of 2-tuple `(x, y)` or 3-tuple `(x, y, pressure)`
  sample points.
- **`.color` / `.width`** — resolved brush properties from
  `<inkml:definitions>`.
- **`.pressure`** — third-channel values when every point carries
  pressure, else `None`.
- **`.id`** — the `xml:id` attribute on the trace (populated by
  Office, unset on library-authored strokes).

### Round-trip

Strokes authored via `add_ink_stroke` survive `save` → `Visio(buf)`
reload with their geometry, colour, width, and pressure intact. The
`application/inkml+xml` content type is declared in
`[Content_Types].xml` on save.

## ECMA-376 Strict conformance class

Visio packages are opened and saved in ECMA-376 *Transitional* mode
by default. Strict-OOXML packages (those that declare the
`purl.oclc.org/ooxml/...` namespace family on the OPC core relationships
and content types) are auto-detected on open via the shared
[`python-ooxml-opc`](../python-ooxml-opc/) 0.2+ runtime; callers that
need to force the class, or round-trip a Strict package, use the
`strict=` keyword plumbed through the factories and
`VisioDocument.open()` / `.save()`.

```python
import vsdx

# auto-detect (default)
doc = vsdx.Visio("report.vsdx")

# force Strict loading (useful for Flat-OPC Strict or ambiguous sniffs)
doc = vsdx.Visio("report.vsdx", strict=True)
print(doc.is_strict)  # True

# preserve the loaded class on save (default — round-trip-preserving)
doc.save("out.vsdx")

# force Transitional emit regardless of source
doc.save("out.vsdx", strict=False)

# author a fresh package and tag it as Strict
doc = vsdx.Visio()
doc.is_strict = True
doc.save("strict.vsdx")
```

- `vsdx.Visio(source=None, strict=False)` — `strict=` forces Strict
  conformance handling on open. `[Added in 0.3.0]`
- `vsdx.Stencil(source=None, strict=False)` — same keyword on the
  stencil factory. `[Added in 0.3.0]`
- `vsdx.Template(source=None, strict=False)` — same keyword on the
  template factory. `[Added in 0.3.0]`
- `VisioDocument.open(source, password=None, strict=False)` —
  explicit low-level opener. `[Added in 0.3.0]`
- `VisioDocument.save(target, password=None, strict=None)` —
  `strict=None` (default) preserves the class the package was loaded
  with; `True` / `False` force Strict / Transitional emit.
  `[Added in 0.3.0]`
- `VisioDocument.is_strict` — read / write the package's conformance
  flag. `[Added in 0.3.0]`

## Connectors — auto-routing + typed endpoints

Dynamic connectors are wired into a page with
`Page.connect(source, target)` — the high-level helper that drops
the connector `<Shape>`, writes the two `<Connect>` glue entries
into the page's `<Connects>` element, and materialises the
`BeginX` / `BeginY` / `EndX` / `EndY` endpoint cells so the file
renders without a Visio desktop reroute pass.

```python
import vsdx

doc = vsdx.Visio()
page = doc.pages.add_page(name="Flow")
a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(2, 1))
b = page.shapes.add_shape("Ellipse",   at=(6, 1), size=(2, 1))

# simplest form — centre-pin glue (ToCell="PinX")
c = page.connect(a, b)

# glue to specific connection points
pa = a.connection_points.add(2.0, 0.5)     # right edge of `a`
pb = b.connection_points.add(0.0, 0.5)     # left edge of `b`
c = page.connect(a, b, source_point=pa, target_point=pb)

# recompute endpoint cells after moving an anchor
a.pin_x = 3.0
c.reroute()

# connector neighbourhood on either anchor
assert a.connections_out[0] is c
assert b.connections_in[0] is c

# typed endpoint proxies over the <Connect> rows
assert c.source_shape is a
assert c.target_shape is b
assert c.source_point is pa
assert c.target_point is pb
```

- `Page.connect(source_shape, target_shape, source_point=None,
  target_point=None, connector_master="Dynamic connector")` — drop a
  connector between two shapes. When `source_point` / `target_point`
  are `None`, the nearest-edge connection point on each shape is
  auto-picked (fallback: centre-pin glue, `ToCell="PinX"`). Specify
  a `ConnectionPoint` to pin an endpoint to a specific anchor —
  written as `ToCell="Connections.X<index>"`. `[Added in 0.3.0]`
- `Shape.connections_in` — list of `Connector` instances whose target
  endpoint (`FromCell="EndX"`) is glued to this shape. `[Added in 0.3.0]`
- `Shape.connections_out` — list of `Connector` instances whose
  source endpoint (`FromCell="BeginX"`) is glued to this shape.
  `[Added in 0.3.0]`
- `Connector.source_shape` / `Connector.target_shape` — the shapes
  this connector's `BeginX` / `EndX` endpoints glue to. `None` on a
  degenerate connector authored without glue entries. `[Added in
  0.3.0]`
- `Connector.source_point` / `Connector.target_point` — the
  `ConnectionPoint` each endpoint is glued to, or `None` for
  centre-pin (`ToCell="PinX"`) glue. `[Added in 0.3.0]`
- `Connector.reroute()` — recompute the connector's `BeginX` /
  `BeginY` / `EndX` / `EndY` cells from the currently-resolved glue
  (source / target shapes, and their connection points when
  specified). Use after a `Shape.set_geometry` / pin move to snap
  the connector to the new anchor positions. No-op on an unglued
  connector. `[Added in 0.3.0]`

Geometry approximation: world-coordinate resolution of connection
points assumes Visio's default `LocPinX = Width/2` / `LocPinY =
Height/2` and zero rotation. Shapes with bespoke `LocPinX/Y` or
non-zero `Angle` will draft slightly off-centre until rotation lands
on the authoring surface.

---

Sections for other feature areas (pages, shapes, masters, layers,
text, hyperlinks, print setup, data graphics, scale, kind variants,
templates, stencils, VBA passthrough, …) will be filled in as the
0.3.0 authoring surface stabilises. Until then see
[CHANGELOG.md](CHANGELOG.md) and the per-package `CLAUDE.md`.
