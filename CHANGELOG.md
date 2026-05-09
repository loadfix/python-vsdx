# Changelog

All notable changes to `python-vsdx` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses a CalVer-ish `0.MAJOR.MINOR` scheme until 1.0.

## [Unreleased]

### Added — oxml element-class layer (track 1 of the 0.1.0 fan-out)

- **`vsdx.constants`** — namespace URIs (`NS_VSDX_CORE`, `NS_R`),
  Visio content-type constants (`CT_VSDX_DRAWING_MAIN`,
  `CT_VSDX_PAGE`, `CT_VSDX_PAGES`, `CT_VSDX_MASTER`,
  `CT_VSDX_MASTERS`, `CT_VSDX_WINDOWS`, ...) and relationship-type
  constants (`RT_VISIO_DOCUMENT`, `RT_VISIO_PAGES`, `RT_VISIO_PAGE`,
  `RT_VISIO_MASTERS`, `RT_VISIO_MASTER`, `RT_VISIO_WINDOWS`,
  `RT_VISIO_EXTENSIONS`). The loadfix `python-ooxml-opc` package
  does not yet carry these — once it does, this module will
  re-export rather than redeclare.
- **`vsdx.oxml.simpletypes`** — Visio-specific `ST_*` simple types
  (`ST_FormulaString`, `ST_Boolean`, `ST_PageIndex`, `ST_ShapeType`,
  `ST_LineStyle`, `ST_RouteStyle`, `ST_RowType`, `ST_SectionName`,
  `ST_UnitString`, `ST_WindowType`, `ST_ShapeIndex`, `ST_BaseID`,
  `ST_UniqueID`).
- **`vsdx.oxml.cell`** — `CT_Cell`, the universal name/value element
  with `@N` / `@V` / `@F` / `@U` / `@E` attributes that unifies ~150
  XSD element pages from Visio's ShapeSheet vocabulary into one
  class.
- **`vsdx.oxml.row`** — `CT_Row`, a grouping of cells with `@IX` /
  `@N` / `@T` attributes supporting Visio's three row flavours
  (indexed, named, geometry-typed).
- **`vsdx.oxml.section`** — `CT_Section`, a collection of rows with
  `@N` / `@IX` attributes (Geometry, Char, Para, Scratch,
  Connection, Controls, Layer, User, Property, Action, Hyperlink
  among others).
- **`vsdx.oxml.shape`** — `CT_Shape`, the core recursive shape
  element with nested Cells, Rows, Sections, Text, and child Shapes.
- **`vsdx.oxml.shapes`** — `CT_Shapes`, the container; recursive to
  support group shapes.
- **`vsdx.oxml.page`** — `CT_Page` + `CT_PageSheet` + `CT_PageContents`
  (the page-index entry and the page-part root).
- **`vsdx.oxml.pages`** — `CT_Pages`, the document-level page
  collection.
- **`vsdx.oxml.master`** — `CT_Master`, `CT_MasterContents`, and
  `CT_Icon` (master-index entry + master-part root + master icon).
- **`vsdx.oxml.masters`** — `CT_Masters`, the document-level master
  collection.
- **`vsdx.oxml.document`** — `CT_VisioDocument`, the root of
  `/visio/document.xml`, plus `CT_DocumentSettings`,
  `CT_DocumentSheet`, `CT_StyleSheets`, `CT_StyleSheet`,
  `CT_Colors`, `CT_FaceNames`, `CT_EventList`.
- **`vsdx.oxml.connects`** — `CT_Connects`, `CT_Connect`
  (shape-to-shape connector references).
- **`vsdx.oxml.window`** — `CT_Windows`, `CT_Window` (window/viewport
  state in `/visio/windows.xml`).
- **`vsdx.oxml`** — `parse_xml` (hardened lxml parser),
  `NamespaceRegistry` install, `qn` / `nsdecls` / `nsmap` /
  `register_element_cls`. Installs the same
  `resolve_entities=False, no_network=True, huge_tree=False` config
  used by every other shared-package parser in the loadfix family.
- BDD-style unit tests under `tests/unit/` exercising cell /
  row / section / shape / shapes / page / master / document /
  connects / window round-trips plus the XXE + billion-laughs
  parser-hardening canaries.

### Not yet in this release

- **Parts layer** (`vsdx.parts.*`) — track 2 of the 0.1.0 fan-out.
- **Proxy layer** (`vsdx.document`, `vsdx.page`, `vsdx.shapes.*`,
  `vsdx.api`) — track 3.
- **Formula passthrough + fixture corpus + CI fidelity harness** —
  track 4.
