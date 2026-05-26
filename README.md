# python-vsdx

Microsoft Visio (`.vsdx`) authoring library for the `loadfix` OOXML
family. A fourth parent library anchored on top of the existing
shared-package stack (`python-ooxml-opc`, `python-ooxml-xmlchemy`,
`python-ooxml-docprops`, `python-ooxml-shared-drawingml`) — not an
extraction from an existing parent.

## Status

Pre-alpha. 0.1.0 is the authoring-floor milestone: document → pages
→ shapes (rectangle / ellipse / triangle) → connectors (Dynamic
Connector with endpoint glue) → in-shape text → masters (built-in
stencil catalog). API is unstable until the round-trip fidelity
harness has run green against the Microsoft-generated fixture
set.

## Scope

Only the **`.vsdx`** content-type
(`application/vnd.ms-visio.drawing.main+xml`). Macro-enabled
(`.vsdm`), stencil (`.vssx` / `.vssm`), and template (`.vstx` /
`.vstm`) content-types share the Visio schema but ship as separate
content-type variants; those are deferred to 0.2.0 (stencils) and
0.3.0 (templates).

The Visio schema is **not ECMA-standardised** — Microsoft publishes
it only on Microsoft Learn under the
`http://schemas.microsoft.com/office/visio/2011/1/core` namespace.
This library anchors on that schema via the MS Learn Elements /
Types reference pages and cross-checks against the
`dave-howard/vsdx` reference implementation (BSD-3) for real-world
Visio-emitted structure, with no vendored code.

### In scope for 0.1.0

- OPC packaging with the Visio content-type registry.
- `VisioDocument` root, `Pages` index, `PageContents` per page.
- `Masters` + `MasterContents` with built-in autoshape masters
  (Rectangle, Ellipse, Triangle) and the Dynamic Connector.
- Shape-level `Cell`/`Row`/`Section` descriptor model.
- `Connects` + `Connect` for shape-to-shape connectors.
- `<Text>` element with simple character-run / paragraph-run
  formatting.
- Formula strings: curated allow-list + raw-passthrough (no
  evaluator).
- Byte-identical round-trip on unmodified reads.
- Visio-Web compatible subset (no macro-enabled content, no OLE,
  no ActiveX, no `Type="Guard"`).

### Out of scope

- `.vsd` (binary legacy Visio).
- ShapeSheet formula evaluator (use Visio desktop's recompute-at-
  open path).
- Data graphics, data-recordsets, data-connections (0.3.0).
- Layers, groups, background pages (0.2.0).
- Validation rules, signatures, encryption, ink annotations,
  embedded charts (0.3.0+).

## Installation

```bash
pip install python-vsdx
```

Runtime dependencies:

- `lxml >= 4.9.1`
- `python-ooxml-opc >= 0.1.0` — OPC packaging + reproducible zip.
- `python-ooxml-xmlchemy >= 0.1.0` — shared descriptor DSL.
- `typing-extensions >= 4.9.0`.

## Usage

```python
from vsdx.oxml import parse_xml
from vsdx.oxml.document import CT_VisioDocument

xml = b'<VisioDocument xmlns="http://schemas.microsoft.com/office/visio/2011/1/core"/>'
doc = parse_xml(xml)
assert isinstance(doc, CT_VisioDocument)
```

## Round-trip support

Visio's `.vsdx` is also an OPC zip, so the cross-monorepo round-trip
gate at [`tests/round_trip/`](../tests/round_trip/README.md) covers it
on the same footing as the other three formats. The
`round-trip-fidelity` CI job opens each corpus fixture (including
`vsdx-default`), saves with `reproducible=True`, and asserts an empty
`Package.diff`.

The per-feature support matrix (what's "fully preserved" / "preserved
with caveats" / "lossy") lives at
[`docs/round-trip-fidelity.md`](../docs/round-trip-fidelity.md).

## Related projects

- [python-docx](https://github.com/loadfix/python-docx)
- [python-pptx](https://github.com/loadfix/python-pptx)
- [python-xlsx](https://github.com/loadfix/python-xlsx)
- [python-ooxml-xmlchemy](https://github.com/loadfix/python-ooxml-xmlchemy)
- [python-ooxml-opc](https://github.com/loadfix/python-ooxml-opc)

Community reference implementation:
[`dave-howard/vsdx`](https://github.com/dave-howard/vsdx) (BSD-3) —
a working read/write library we cross-checked real Visio output
against. No vendored code.

Apache-2.0.
