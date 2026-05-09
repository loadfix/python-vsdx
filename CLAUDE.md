# python-vsdx — project notes for Claude

Microsoft Visio (`.vsdx`) authoring library for the loadfix OOXML
family. A **fourth parent library** anchored on top of the existing
shared-package stack. Unlike `python-docx` / `python-pptx` /
`python-xlsx` (which each share chunks of markup via the shared
packages), vsdx is a greenfield parent sibling — it *consumes* the
shared packages without having an extraction heritage.

Sibling shared packages (runtime deps in 0.1.0):

- `loadfix/python-ooxml-opc` — OPC packaging, reproducible zip,
  part/relationship model.
- `loadfix/python-ooxml-xmlchemy` — descriptor DSL
  (`BaseOxmlElement`, `ZeroOrOne`, `ZeroOrMore`, `OptionalAttribute`,
  `RequiredAttribute`, `OneAndOnlyOne`).
- `loadfix/python-ooxml-docprops` (0.1.0+1, not a direct import
  target of this oxml track — the parts layer wires it in).

Runtime deps we do NOT declare in 0.1.0:

- `python-ooxml-shared-drawingml` — Visio *does* emit a DrawingML
  theme, but the theme part is a pass-through in 0.1.0 (bundled
  verbatim from the seed template). Adoption deferred to track 5
  of a later fan-out.
- `python-ooxml-chart` — chart embed deferred to 0.3.0.
- `python-ooxml-ink` / `-signatures` / `-crypto` — deferred.
- `python-ooxml-comments` — Visio has its own native comment schema,
  not ECMA-376 WML/PML comments. Won't join the comments package.

## Scope (schema-grounded)

The authoritative schema lives on Microsoft Learn at
`http://schemas.microsoft.com/office/visio/2011/1/core` (namespace
URI; the docs are the `office/client-developer/visio/*` topic tree
sourced from `MicrosoftDocs/office-developer-client-docs` on GitHub).
**Visio is not ECMA-standardised** — there is no ECMA/ISO XSD
bundle. See `audits/2026-05-09-vsdx-scoping.md` §2 for the full
analysis.

### In scope for 0.1.0 — the authoring floor

- `VisioDocument` root in `/visio/document.xml`.
- `Pages` + `Page` + `PageSheet` (index) + `PageContents` (page
  parts).
- `Masters` + `Master` + `MasterContents` (master catalog with
  built-in Rectangle / Ellipse / Triangle / Dynamic Connector).
- `Shape` hierarchy (recursive): `Shape` → {singleton `Cell`s,
  `Section` with tabular `Row`s, `Text` with cp/pp/tp formatting
  runs, nested `Shapes` for group shapes}.
- `Connects` / `Connect` for connector glue.
- `Windows` / `Window` for viewport state.
- Hardened lxml parser (`resolve_entities=False, no_network=True,
  huge_tree=False`).
- Byte-identical round-trip on unmodified reads.

### Out of scope

- **ChartEx**, **ChartShape**, **DataGraphics** — all 0.3.0.
- **`.vsdm` / `.vssx` / `.vssm` / `.vstx` / `.vstm`** —
  content-type variants over the same schema; 0.2.0+.
- **ShapeSheet formula evaluator** — `Cell/@F` is always
  pass-through; Visio desktop recomputes on open.
- **Layers, groups (beyond autoshape default), background pages** —
  0.2.0.
- **Digital signatures, encryption, ink** — 0.3.0+.
- **Comments** — Visio-native schema; 0.3.0+ and it will ship
  vsdx-local (not join `python-ooxml-comments`).

## The Cell / Row / Section unification insight

Visio's inner XML is fundamentally different from docx / pptx / xlsx.
Where DrawingML gives every named property a dedicated element
(`<a:srgbClr val="FF0000"/>`), Visio gives every property the same
generic `<Cell>` element distinguished by its `@N` (name) attribute:

```xml
<Shape ID="1" Type="Shape">
  <Cell N="PinX"  V="2" U="IN"/>
  <Cell N="PinY"  V="3" U="IN"/>
  <Cell N="Width" V="1" U="IN"/>

  <Section N="Geometry" IX="0">
    <Row IX="1" T="LineTo">
      <Cell N="X" V="0" F="Width*0"/>
      <Cell N="Y" V="0" F="Height*0"/>
    </Row>
  </Section>
</Shape>
```

Direct consequence: the ~150 element pages in MS Learn's Elements
reference **collapse into ~12 `CT_*` classes** in this package
(`CT_Cell`, `CT_Row`, `CT_Section`, `CT_Shape`, `CT_Shapes`,
`CT_Page`, `CT_Pages`, `CT_PageSheet`, `CT_PageContents`,
`CT_Master`, `CT_MasterContents`, `CT_Masters`, `CT_VisioDocument`,
`CT_Connects`, `CT_Connect`, `CT_Windows`, `CT_Window` + a handful
of DocumentSettings children). Named-cell semantics (`.pin_x`,
`.line_weight`, `.fill_foregnd`) are **proxy-layer concerns** —
value-level dispatch on `cell.name_`, not xmlchemy subclasses.

## Architecture

```
src/vsdx/
├── __init__.py        — public-API re-exports + __version__
├── constants.py       — NS / CT / RT constants
├── oxml/
│   ├── __init__.py    — parse_xml + namespace registry install
│   ├── simpletypes.py — Visio-specific ST_*
│   ├── cell.py        — CT_Cell
│   ├── row.py         — CT_Row
│   ├── section.py     — CT_Section
│   ├── shape.py       — CT_Shape (+ CT_Text, CT_ForeignData)
│   ├── shapes.py      — CT_Shapes
│   ├── page.py        — CT_Page, CT_PageSheet, CT_PageContents
│   ├── pages.py       — CT_Pages
│   ├── master.py      — CT_Master, CT_MasterContents, CT_Icon
│   ├── masters.py     — CT_Masters
│   ├── document.py    — CT_VisioDocument + DocumentSettings kids
│   ├── connects.py    — CT_Connects, CT_Connect
│   └── window.py      — CT_Windows, CT_Window
└── py.typed           — PEP 561 marker

tests/unit/            — BDD-style Describe* / it_* / they_*
```

## Three conformance constraints (non-negotiable)

1. **Byte-identical round-trip on unmodified reads.** Load a
   `.vsdx`, serialise, assert the zip entries byte-compare
   identically. Lives in track 4 (fidelity harness), but the oxml
   layer supports it by:
   - preserving attribute order on write (never re-sort in a
     descriptor setter);
   - preserving `<Text>` cp/pp/tp run indices verbatim;
   - using `xml_declaration=True` and the hardened parser's
     default serialisation config.
2. **Opens cleanly in Microsoft Visio desktop.** Asserted manually
   at 0.1.0 (Visio has no headless Linux automation). The oxml
   layer supports this by never emitting:
   - `<VisioDocument>` without at least one `<StyleSheets>` with
     the default `LineStyle`/`FillStyle`/`TextStyle` entries;
   - a `<Shape Master="@ID">` whose `@ID` isn't declared in
     `/visio/masters/masters.xml`;
   - a `<Connect From/ToSheet="…">` whose value isn't a shape-ID
     on the same page.
3. **Visio-Web compatible.** Don't emit macro content, ActiveX,
   OLE, or `Type="Guard"` shapes. 0.1.0 scope already excludes all
   of these.

## Build & test

```bash
pip install -e '.[dev]'

pytest tests/
pyright src/
ruff check src/ tests/
```

Test naming follows the loadfix family convention: `Describe*`
classes, `it_*` / `its_*` / `they_*` methods. No docstrings on
test methods.

### Running the conformance (round-trip) harness

`tests/conformance/` hosts the byte-identical round-trip harness —
the enforcement arm of constraint #1 in **Three conformance
constraints** below. It iterates every `.office.vsdx` fixture
under `~/code/ooxml-reference-corpus/fixtures/vsdx/` (plus the
bundled `src/vsdx/templates/default.vsdx` once it lands), loads
each via `VisioPackage.open`, re-serialises via `.save(BytesIO)`,
and asserts that every zip entry is byte-identical to the
original's.

```bash
# Run only the conformance harness
pytest -m conformance tests/conformance/ -v

# Run everything except the conformance harness (fast unit loop)
pytest -m 'not conformance' tests/

# Override the corpus lookup path
VSDX_CORPUS_ROOT=/path/to/alt/corpus pytest -m conformance tests/conformance/

# See the list of fixtures pytest discovered without running them
pytest -m conformance --collect-only -q tests/conformance/
```

The harness **skips cleanly** when no fixtures are present (clean
checkout, CI without the corpus mounted, `default.vsdx` not yet
bundled) — landing or removing fixtures never causes a green run
to go red for infrastructure reasons.

Per-entry diff: when a part's bytes drift, the failure names the
drifting zip entry and shows the first 200 chars of the original
and saved XML side-by-side. Whole-file dumps are deliberately
avoided — the investigator gets a scannable hint, not a megabyte
of XML. See `tests/conformance/diff.py` for the format. The
harness is **pure instrumentation**: when a fixture fails, fix the
underlying writer bug in a separate commit; never relax the
harness's byte-equality contract to mask a drop.

Expected fixtures are listed in
`audits/2026-05-09-vsdx-fixture-guide.md` (18 `.office.vsdx` /
`.office.vssx` produced by Microsoft Visio desktop).

## Release discipline

- CalVer-ish `0.MAJOR.MINOR` pre-1.0.
- `[Unreleased]` at the top of CHANGELOG.md; bump in the same
  commit as the feature.
- `from __future__ import annotations` at the top of every `.py`.
- `.. versionadded:: X.Y.Z` on every public API.
- `# pyright: …` pragmas at the top of every CT_* module (copy the
  set from `ooxml_chart.oxml.shared`).

## OOXML spec vs Microsoft reality

- Visio desktop is the reference. When MS Learn docs disagree with
  a real `.office.vsdx` fixture, match the fixture.
- `Cell/@V` with a `float`-shaped value may legitimately be a
  decimal, integer, or sentinel like `"Themed"` (for themed
  colour). 0.1.0 treats `@V` as an opaque string at the oxml
  layer; the proxy layer (track 3) handles typed views.
- `xml:space="preserve"` on `<Text>` matters for round-trip
  fidelity.
