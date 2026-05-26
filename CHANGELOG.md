# Changelog

All notable changes to `python-vsdx` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses a CalVer-ish `0.MAJOR.MINOR` scheme until 1.0.

## [Unreleased]

### Added — ShapeSheet formula evaluator integration (vsdx-maturity-formula)

- **`Shape.recompute()`** / **`Page.recompute()`** /
  **`VisioDocument.recompute()`** — walk every cell with a non-empty
  ``@F``, evaluate against a live :class:`ShapeContext` rooted on the
  shape, and write the stringified result back to ``@V``. Returns the
  number of cells whose value actually changed; failures stamp
  ``@E`` rather than poisoning the rest of the pass.
- **`Shape.cell(name)`** — returns a :class:`vsdx.cell.Cell` proxy for
  a singleton ``<Cell>`` child, exposing typed
  ``name``/``value``/``formula``/``unit`` accessors plus
  ``evaluate(context=None)`` / ``recompute(context=None)``.
- **`vsdx.formula.Context.for_shape(shape)`** — build a live resolver
  that walks the owning shape's oxml tree (singletons, sections,
  rows) and the page's sibling shapes for ``Sheet.N!`` / ``Name!``
  cross-shape refs. ``Context.for_mapping(...)`` is the existing
  unit-test path.
- **`CONCAT`** alias of ``CONCATENATE`` (Visio 2013+ spelling).
- Coverage doc at ``src/vsdx/formula/COVERAGE.md`` listing every
  supported operator and builtin with edge-case notes.

### Added — stencil builder API (R16-2)

- **`vsdx.Stencil`** is now a class with authoring-first classmethods
  alongside the pre-existing load factory. ``Stencil()`` with no
  argument still returns a :class:`VisioDocument` for backwards
  compatibility with the 0.2.0 factory; ``Stencil.new()`` returns a
  dedicated ``Stencil`` instance wrapping a fresh stencil package.
- **`Stencil.add_master(name, width, height, content_callback=None)`** —
  append a new master, stamp ``Width`` / ``Height`` cells on its
  index-level ``<PageSheet>``, and optionally invoke
  ``content_callback(master)`` so the caller can populate shapes
  inline.
- **`Master.add_shape(name, x, y, width, height)`** — build-time
  shape-authoring complement of :meth:`ShapeTree.add_shape`; stamps a
  ``<Shape>`` into the master's ``<MasterContents>`` with named
  geometry cells (``PinX`` / ``PinY`` / ``Width`` / ``Height``) and a
  sheet-scoped ID.
- **`Stencil.save(path)`** — write the stencil out as ``.vssx`` via
  the underlying :class:`VisioDocument` save path.
- **`Stencil.from_shape_library(shapes)`** — bulk-import an iterable
  of ``(name, payload_bytes)`` pairs; each pair becomes a master and
  the bytes are stashed on ``master._payload`` for caller round-trip.
- Load path: :attr:`MastersPart._master_parts` now wires each
  :class:`MasterPart`'s ``master_element`` back-reference from the
  loaded ``<Master>`` index entries (paired via ``r:id``), so
  loaded-from-disk masters expose ``@NameU`` / ``@Name`` / ``@ID``
  through the proxy after a round-trip.

### Added — connector auto-routing + typed endpoints (R14-4)

- **`vsdx.Page.connect(source, target, source_point=None,
  target_point=None, connector_master="Dynamic connector")`** —
  high-level helper that drops a connector shape linking two anchor
  shapes, writes the two ``<Connect>`` glue entries, and materialises
  the connector's endpoint cells.  When ``source_point`` /
  ``target_point`` are ``None``, the nearest-edge connection point on
  each shape is auto-picked (fallback: centre-pin glue,
  ``ToCell="PinX"``).  Specific :class:`ConnectionPoint` instances
  write ``ToCell="Connections.X<index>"``.
- **`vsdx.shapes.Shape.connections_in`** / **`.connections_out`** —
  lists of :class:`~vsdx.shapes.Connector` instances whose target
  (``EndX``) / source (``BeginX``) endpoint is glued to this shape.
- **`vsdx.shapes.Connector.source_shape`** / **`.target_shape`** —
  typed proxies over the ``<Connect>`` rows resolving the two
  anchor-glue shapes, or ``None`` for unglued endpoints.
- **`vsdx.shapes.Connector.source_point`** / **`.target_point`** —
  typed :class:`~vsdx.connection_points.ConnectionPoint` proxies when
  the endpoint glues to a numbered connection point; ``None`` for
  centre-pin glue (``ToCell="PinX"``).
- **`vsdx.shapes.Connector.reroute()`** — recompute the connector's
  ``BeginX`` / ``BeginY`` / ``EndX`` / ``EndY`` cells from the
  currently-resolved source/target shapes (or their specific
  connection points).  Use after a ``Shape.set_geometry`` / pin move
  to snap the connector to the new anchor positions.  No-op on an
  unglued connector.

Known limitation: world-coordinate resolution of connection points
assumes Visio's default ``LocPinX = Width/2`` / ``LocPinY = Height/2``
and zero rotation.  Shapes with bespoke ``LocPinX/Y`` or non-zero
``Angle`` will draft slightly off-centre until rotation lands on the
authoring surface.

### Added — password-protected save/open via `python-ooxml-crypto` 0.3 (R12-2)

- **`vsdx.VisioDocument.save(target, password=None)`** — when
  ``password`` is provided, the produced ``.vsdx`` zip is wrapped in
  an ECMA-376 Agile Encryption CFB container, matching the format
  Microsoft Visio/Office writes when a user sets a password in the
  desktop app. Requires the optional
  [`python-ooxml-crypto`](https://github.com/loadfix/python-ooxml-crypto)
  dependency (``pip install 'python-vsdx[encryption]'``).
- **`vsdx.VisioDocument.open(source, password=None)`** — transparent
  decryption of an encrypted ``.vsdx``. When ``source`` starts with
  the OLE2 CFB magic (``D0 CF 11 E0 …``) the stream is decrypted
  with ``password`` before being handed to the OPC loader. Raises
  :class:`~vsdx.document.EncryptedPackageError` on a wrong password
  or when ``password`` is omitted against an encrypted container.
- **`vsdx.document.EncryptedPackageError`** — surface exception
  for password-protected read/write. Inherits from :class:`ValueError`
  for symmetry with the sister ``python-docx`` / ``python-pptx``
  exception hierarchies. The supplied password is **never** echoed
  in the exception message.
- **Unicode passwords pass through unchanged** — the vsdx wrapper
  hands the string verbatim to ``ooxml_crypto``, which applies the
  MS-OFFCRYPTO UTF-16-LE encoding. Composed characters survive the
  round-trip without normalisation.

### Added — ink-annotation authoring via `python-ooxml-ink` 0.2 (R11-7)

- **`vsdx.Page.ink_strokes`** — list of
  [`InkStroke`](src/vsdx/ink.py) for every `<inkml:trace>` attached
  to this page. Walks each ``RELATIONSHIP_TYPE_INK`` rel on the page
  part, resolves the target :class:`~vsdx.parts.ink.InkPart`, and
  enumerates traces in document order.
- **`vsdx.Page.add_ink_stroke(points, pressure=None, color=None,
  width=None)`** — append a new stroke to this page and return its
  `InkStroke` proxy. Creates — or reuses — a single
  ``/visio/ink/ink{n}.xml`` part per page. Accepts 2-tuple
  ``(x, y)`` or 3-tuple ``(x, y, pressure)`` point lists; ``color``
  is hex-RGB (``"#RRGGBB"`` or ``"RRGGBB"``); ``width`` is a pixel
  nib width. `ValueError` on empty *points* or a pressure-length
  mismatch.
- **`vsdx.VisioDocument.ink_strokes`** — flat list of `InkStroke`
  across every page in the document.
- **`vsdx.InkStroke`** — read proxy over an ``<inkml:trace>``
  exposing ``.points``, ``.color``, ``.width``, ``.pressure``, and
  ``.id``. Resolved through the shared
  [`ooxml_ink.Stroke`](../python-ooxml-ink/) semantics.
- **`vsdx.parts.ink.InkPart`** — Visio subclass of
  :class:`ooxml_ink.part.InkPart` with a
  ``/visio/ink/ink{n}.xml`` partname allocator. Registered on the
  shared ``PartFactory`` by
  :func:`~vsdx.package.register_visio_parts` so load picks it up
  automatically.
- **dependency** — ``python-ooxml-ink`` pinned as ``git+https:`` for
  0.2 authoring surface (``InkContent.add_stroke`` / ``Stroke`` /
  brush authoring).

### Tests — ink-annotation authoring (`tests/test_ink.py`)

- **16 unit tests** across four describe classes:
  - `DescribePageInkStrokes` — empty-by-default, append-and-expose,
    color + width recording, per-point pressure (3-tuple and kwarg),
    ink-part reuse across multiple strokes, `ValueError` on empty
    points, `ValueError` on mismatched pressure length.
  - `DescribeDocumentInkStrokes` — empty-by-default and cross-page
    aggregation.
  - `DescribeInkStrokeRoundTrip` — save + reload preserves
    geometry / colour / width / pressure; ``/visio/ink/ink*.xml``
    part appears in the saved zip; ``application/inkml+xml`` is
    declared in ``[Content_Types].xml``; two consecutive round-trips.
  - `DescribePublicSurface` — ``vsdx.InkStroke`` re-export.

### Added — theme proxies + per-page theme overrides (R8-14)

- **`vsdx.theme.ColorScheme`** — dotted-attribute proxy over the
  ``<a:clrScheme>`` element. Exposes the twelve canonical DrawingML
  colour slots (``dk1`` / ``lt1`` / ``dk2`` / ``lt2`` /
  ``accent1``–``accent6`` / ``hlink`` / ``folHlink``) as read-only
  properties returning a six-hex-digit RGB string for ``<a:srgbClr>``
  slots, the raw system-colour name (``"windowText"`` / ``"window"``)
  for ``<a:sysClr>`` slots, or ``None`` when the slot is absent /
  wraps a ``<a:schemeClr>``. ``.name`` surfaces the scheme's
  ``@name`` attribute.
- **`vsdx.theme.FontScheme`** — dotted-attribute proxy over the
  ``<a:fontScheme>`` element. Exposes ``.name``, ``.major_font``,
  and ``.minor_font`` — the last two are internal
  ``_ThemeFont`` proxies with ``.latin_typeface`` over
  ``a:latin@typeface``.
- **`vsdx.theme.Theme.color_scheme`** — returns the
  :class:`ColorScheme` proxy for this theme, or ``None`` when the
  theme has no ``<a:clrScheme>``.
- **`vsdx.theme.Theme.font_scheme`** — returns the
  :class:`FontScheme` proxy, or ``None`` when the theme has no
  ``<a:fontScheme>``.
- **`vsdx.document.VisioDocument.themes`** — list of every
  :class:`Theme` proxy in the package (each
  :class:`~vsdx.parts.theme.ThemePart` reachable from the package).
  Returns an empty list for fresh packages until seed-template
  injection (track 4) lands.
- **`vsdx.page.Page.theme`** — getter returns the theme effective
  on this page: the per-page override theme (an ``RT.THEME`` rel on
  the page part) when present, else the document-wide theme
  (:attr:`VisioDocument.theme`), else ``None``. Setter accepts a
  :class:`Theme` (establishes/replaces the override rel) or ``None``
  (removes the override so the page inherits the document theme
  again). ``TypeError`` on any other value.
- **`vsdx.ColorScheme` / `vsdx.FontScheme`** — public re-exports on
  the top-level ``vsdx`` namespace.

### Tests — theme proxies + per-page overrides

- **26 additional unit tests** (`tests/unit/test_theme.py`):
  ``ColorScheme`` slot coverage (srgb values normalised to
  uppercase hex, sysClr values surfaced as the raw ``@val`` name,
  ``None`` for bare themes), ``FontScheme`` major/minor latin
  typeface reads, round-trip via ``Theme.set_color`` reflected
  through the proxy, ``VisioDocument.themes`` enumeration of
  document-scoped plus per-page theme parts, ``Page.theme``
  document-fallback / per-page-override reads, setter creating
  and replacing the page's ``RT.THEME`` rel, setter ``None``
  removing the rel, and ``TypeError`` on non-``Theme``
  assignments.

### Added — page scale + print setup (R8-6, R8-7)

- **`vsdx.page.Page.page_scale`** / **`Page.drawing_scale`** — float
  accessors over the ``<PageSheet><Cell N="PageScale">`` and
  ``<Cell N="DrawingScale">`` singletons. Writes emit ``U="IN"``;
  `None` clears the cell so Visio falls back to the 1:1 default.
- **`Page.drawing_size_type`** / **`Page.drawing_scale_type`** — int
  accessors over ``DrawingSizeType`` / ``DrawingScaleType`` (Visio's
  ``visDrawSize*`` / ``visDrawScaleType`` enum codes).
- **`Page.inhibit_snap`** — bool accessor over ``<Cell N="InhibitSnap">``.
  Tolerates ``TRUE`` / ``FALSE`` / ``1`` / ``0`` on read; emits
  ``"1"`` / ``"0"`` on write.
- **`Page.ui_visibility`** — int accessor over ``<Cell N="UIVisibility">``.
- **`vsdx.print_setup.PrintSetup`** — page-scope print-configuration
  proxy over the print-related singleton cells on the page's
  ``<PageSheet>``. Accessed via **`Page.print_setup`** (lazy — the
  proxy is always returned and walks the sheet on every read so
  concurrent oxml-layer edits stay consistent). Accessors:
  ``.orientation`` (:class:`PRINT_ORIENTATION`), ``.paper_size``
  (int — Windows ``DEVMODE.dmPaperSize`` enum), ``.margin_top``
  / ``.margin_bottom`` / ``.margin_left`` / ``.margin_right`` (float
  inches, ``U="IN"`` on write), ``.centered_x`` / ``.centered_y``
  (bool), and ``.tile_scale`` (float — writes both ``ScaleX`` and
  ``ScaleY`` in lockstep with Visio UI).
- **`vsdx.print_setup.PRINT_ORIENTATION`** — ``str``-enum mirroring
  ``<Cell N="PrintPageOrientation">`` ``@V``: ``SAME_AS_PRINTER``
  (``"0"``), ``PORTRAIT`` (``"1"``), ``LANDSCAPE`` (``"2"``).
  ``.orientation =`` accepts the enum, raw string, or integer; unknown
  codes raise ``ValueError`` on authoring and read as ``None`` on
  parse (load-preserve-save invariant).
- **Zero new `CT_*` classes** — reuses the existing `CT_PageSheet`
  direct-child ``<Cell>`` slot with value-level dispatch on
  ``cell.@N``. Matches the R4-12 geometry / R8-3 shape-data pattern.
- **`vsdx.PrintSetup` / `vsdx.PRINT_ORIENTATION`** — public re-exports
  on the top-level package namespace.

### Tests — page scale + print setup

- **46 unit tests** (`tests/unit/test_print_setup.py`): scale-accessor
  defaults (absent-cell → ``None`` / ``False``), authoring (cell
  materialisation with ``U="IN"`` on scale cells, integer / float
  preservation, tolerant boolean tokens, non-numeric parse-fallback),
  clear-by-``None`` semantics; ``PrintSetup`` proxy instantiation +
  lazy caching, orientation setter accepting enum / string / int +
  unknown-code rejection + ``None``-on-parse for unknown values,
  paper_size / margin / centering / tile_scale round-trips (tile_scale
  writes both ``ScaleX`` and ``ScaleY``), and an 18-cell fixture-shaped
  parse → mutate → read round-trip asserting sibling-cell preservation.

### Added — hyperlinks (R8-4)

- **`vsdx.hyperlinks.Hyperlink`** — per-hyperlink proxy over one
  ``<Row>`` inside ``<Section N="Hyperlink">``. Accessors: `.name`,
  `.address`, `.sub_address`, `.description`, `.extra_info`,
  `.new_window`, `.default`, `.invisible`, `.sort_key`. Boolean
  setters tolerate ``TRUE`` / ``FALSE`` tokens on read and emit
  ``1`` / ``0`` on write.
- **`vsdx.hyperlinks.HyperlinkCollection`** — list-like +
  description-keyed collection over the shape's
  ``<Section N="Hyperlink">``. Accessed via **`Shape.hyperlinks`**.
  Supports ``shape.hyperlinks[0]`` integer indexing,
  ``shape.hyperlinks["Support site"]`` description lookup, ``len`` /
  iteration / ``in`` (by description), plus ``.get(description,
  default=None)`` and ``.default_hyperlink`` helpers.
- **`HyperlinkCollection.add(address, *, description=None,
  sub_address=None, extra_info=None, new_window=False, default=False,
  invisible=False, sort_key=None, name=None)`** — appends a new
  ``<Row>``. Auto-names rows ``Row_<n>`` matching Visio desktop.
  Only emits cells the caller supplied (absent-is-falsey semantics).
  Materialises the ``<Section N="Hyperlink">`` on first call.
- **`HyperlinkCollection.remove(key)`** — deletes a hyperlink by
  integer index, description string, or `Hyperlink` proxy.
  Preserves the Section element even when the last row is removed
  for round-trip byte-identity on re-add.
- **One-default invariant** — setting `.default = True` on any
  hyperlink (or passing `default=True` to `.add(...)`) auto-clears
  the flag on every sibling so at most one hyperlink per shape is
  marked default, matching Visio desktop's Ctrl+Click behaviour.
- **`VisioDocument.hyperlink_base`** — document-wide relative-URL
  base (``<DocumentSheet><Cell N="HyperlinkBase">``). Setter
  materialises the DocumentSheet on demand; assigning `None` or
  the empty string removes the cell.
- **Zero new `CT_*` classes** — reuses the existing `CT_Section` /
  `CT_Row` / `CT_Cell` trio with value-level dispatch on
  ``section.@N == "Hyperlink"`` and ``row.@N`` for the hyperlink
  name. Matches the R4-12 geometry + R8-3 shape-data pattern.
- **`vsdx.Hyperlink` / `vsdx.HyperlinkCollection`** — public
  re-exports on the top-level package namespace.

### Tests — hyperlinks

- **42 hyperlinks unit tests** (`tests/unit/test_hyperlinks.py`):
  empty collection, first-add section materialisation, indexing
  (int, negative int, by description), iteration, ``in`` membership,
  error paths (`KeyError`, `IndexError`, `TypeError`); authoring
  (auto-naming, explicit names, minimal-cell emission, sub-address-
  only intra-document jumps, flag propagation); one-default invariant
  (sibling auto-clear on add, on flag-setter flip, clearing without
  replacement); cell accessors (textual, flag tokens including
  TRUE/FALSE tolerance, absent-cell defaults); removal (by index /
  description / proxy, error paths, section preservation); parse-
  existing multi-hyperlink fixture + parse-mutate-read round trip;
  `VisioDocument.hyperlink_base` (fresh = None, settable, DocumentSheet
  materialisation, update-not-duplicate, None / empty-string clear,
  no-op clear on empty); repr strings.
### Added — connection points (R8-17)

- **`vsdx.connection_points.ConnectionPoints`** — list-like proxy over
  the shape's ``<Section N="Connection">``. Accessed via
  **`Shape.connection_points`**. Supports
  ``shape.connection_points[i]`` indexed lookup, iteration in ``@IX``
  order, ``len``, and ``shape.connection_points.add(x, y, *,
  dir_x=0, dir_y=0, type=CONNECTION_TYPE.INWARD, auto_gen=False)`` /
  ``remove(index)`` authoring.
- **`vsdx.connection_points.ConnectionPoint`** — per-row proxy
  exposing `.index`, `.x`, `.y`, `.dir_x`, `.dir_y`, `.type`,
  `.auto_gen` accessors. Coordinates emitted with the ``IN`` unit;
  Type cell always materialised on authoring for fixture-corpus
  byte-identity.
- **`vsdx.connection_points.CONNECTION_TYPE`** — ``str``-enum
  mirroring the ``<Cell N="Type">`` ``@V``: ``INWARD`` (``"0"``),
  ``OUTWARD`` (``"1"``), ``INWARD_OUTWARD`` (``"2"``). ``.add()`` /
  ``.type =`` accept the enum, raw ``"0"``/``"1"``/``"2"``, or the
  integer ``0``/``1``/``2``; unknown codes raise ``ValueError`` on
  authoring and fall back to ``INWARD`` on parse (load-preserve-save
  invariant).
- **`AutoGen` round-trip** — the ``<Cell N="AutoGen">`` flag is
  preserved verbatim on parse and authored only when explicitly set
  to ``True`` (absence and ``V="0"`` both read as ``False``).
- **Zero new `CT_*` classes** — reuses the existing `CT_Section` /
  `CT_Row` / `CT_Cell` trio with value-level dispatch on
  ``section.@N == "Connection"`` and ``row.@IX`` for the point's
  ordinal. Matches the R4-12 geometry / R8-3 shape-data pattern.

### Tests

- **30 connection-point unit tests** (`tests/unit/test_connection_points.py`):
  Sequence surface (index / iter / len / empty-on-fresh-shape),
  ``add`` authoring (static/inward default, dynamic/outward + DirX/DirY,
  inward-outward, integer + string + enum type codes, auto-gen flag,
  monotonic ``@IX`` from 1, ``U="IN"`` on coordinate cells, invalid
  type rejection), typed accessors (coordinate / direction / type /
  auto-gen getters & setters, invalid-type assignment rejection,
  ``__repr__``), removal (``remove`` + section preservation +
  ``IndexError`` on out-of-range), and parse-existing fixture
  round-trips (mixed inward/outward/inward-outward, missing-Type
  default, unknown-Type tolerance, parse-mutate-read).

### Added — shape data / user-defined properties (R8-3)

- **`vsdx.shape_data.ShapeData`** — dict-like proxy over the shape's
  ``<Section N="Property">``. Accessed via **`Shape.data`**. Supports
  ``shape.data["Cost"]`` typed-value lookup, iteration over property
  names, ``in`` / ``len`` / ``del`` operators, and ``.get(name, default)``
  / ``.get_field(name)`` graceful-miss variants.
- **`vsdx.shape_data.ShapeDataField`** — per-property proxy exposing
  `.name`, `.label`, `.type`, `.value`, `.raw_value`, `.format`,
  `.prompt`, `.sort_key`, `.invisible` accessors. `.value` coerces
  per the Visio ``<Cell N="Type">`` code — String/FixedList/VariableList
  to `str`, Number/Currency to `float`, Boolean to `bool` (tolerating
  TRUE/FALSE tokens on read, emitting 0/1 on write), Date/Duration
  passed through as `str`.
- **`ShapeData.add_field(name, value, *, label=None, type=0, format=None,
  prompt=None, sort_key=None, invisible=False)`** — appends a new
  ``<Row>`` with cells emitted in Visio-canonical order. Materialises
  the ``<Section N="Property">`` on first call. Rejects duplicate /
  empty names. Label defaults to *name* when omitted.
- **`ShapeData.remove_field(name)`** — deletes a property row;
  preserves the Section element even when the last row is removed
  for round-trip byte-identity on re-add.
- **Type-code constants** — `PROPERTY_TYPE_STRING` (0),
  `PROPERTY_TYPE_FIXED_LIST` (1), `PROPERTY_TYPE_NUMBER` (2),
  `PROPERTY_TYPE_BOOLEAN` (3), `PROPERTY_TYPE_VARIABLE_LIST` (4),
  `PROPERTY_TYPE_DATE` (5), `PROPERTY_TYPE_DURATION` (6),
  `PROPERTY_TYPE_CURRENCY` (7).
- **Zero new `CT_*` classes** — reuses the existing `CT_Section` /
  `CT_Row` / `CT_Cell` trio with value-level dispatch on
  ``section.@N == "Property"`` and ``row.@N`` for the field name.
  Matches the R4-12 geometry pattern.

### Tests

- **36 shape-data unit tests** (`tests/unit/test_shape_data.py`):
  Mapping surface (get / iter / contains / len / del / get / get_field),
  ``add_field`` authoring (duplicate / empty-name rejection, label
  default, format / prompt / sort_key / invisible propagation, Type
  cell emission), typed-coercion round-trips for every Visio type
  code (String, FixedList, Number, Boolean with 1/0 + TRUE/FALSE
  tolerance, VariableList, Date, Duration, Currency, plus missing-
  Value and missing-Type defaults), mutation (`__setitem__` /
  ``remove_field`` / ``del`` / metadata setters), and parse-existing
  fixture round-trips.
### Added — data graphics (R8-2, read + preserve + shape-side mutate)

- **`vsdx.data_graphics.DataGraphic`** — proxy over one
  `<Section N="DataGraphic">` child of `<VisioDocument>`. Exposes
  `id` (document-scoped `@IX`), `name` / `name_universal`,
  `default_position`, `default_style`, `hide_shape_data_fields`, and
  an iterable `items` collection of :class:`DataGraphicItem` rows in
  `@IX` order.
- **`vsdx.data_graphics.DataGraphicItem`** — proxy over a single
  `<Row IX="n" T="kind">` inside a DataGraphic section. Surfaces
  `kind` (``TextCallout`` / ``IconSet`` / ``ColorByValue`` /
  ``DataBar``), `column` (bound ShapeData field formula), and a
  `cells` dict for per-kind cells the proxy doesn't specialise
  (``LowValue`` / ``HighValue`` / ``BarStyle`` / ``IconSet`` …).
  `element` exposes the underlying `<Row>` for formula / unit
  access.
- **`vsdx.data_graphics.DataGraphics`** — document-scoped collection.
  `document.data_graphics` iterates every DataGraphic section on the
  document root, supports indexing + `len`, and offers `get(id)` /
  `get_by_name(name)` lookups. Ignores non-DataGraphic sibling
  sections.
- **`Shape.data_graphic`** — resolves
  `<Cell N="DataGraphic" V="<id>">` against the owning document's
  `data_graphics`. Returns `None` when the cell is absent, empty, or
  points at an unknown id (defensive guard). Setter accepts
  `DataGraphic | None`; assigning `None` removes the cell.
- **`CT_VisioDocument.section_lst`** — new `ZeroOrMore("vsdx:Section")`
  descriptor so document-root sections round-trip through xmlchemy.
- **`vsdx.DataGraphic` / `vsdx.DataGraphicItem` / `vsdx.DataGraphics`** —
  public re-exports on the top-level package namespace.
- **Scope** — 0.2.0 is read-only + shape-side association.
  `document.add_data_graphic(...)` full authoring is **deferred to
  0.3.0** pending schema-parity verification against an authored-in-
  Visio-desktop fixture.

### Tests — data graphics

- **24 new unit tests** (`tests/unit/test_data_graphics.py`): empty
  collection, document-order iteration, id + name lookup,
  non-DataGraphic-section filtering, item `@IX` sort, per-kind cell
  dict, shape ↔ graphic association (link, clear, orphan-id guard,
  TypeError on non-DataGraphic assignment), parse → serialise round
  trip on both the section and the shape cell, and public-export
  re-surfacing.

### Added — custom geometry (R4-12, scoping §4.3 / §4.4)

- **`vsdx.geometry.Geometry`** and **`vsdx.geometry.Geometries`** —
  proxies over one and many ``<Section N="Geometry" IX="N">`` sections
  on a ``<Shape>``. Shapes may carry several geometry sections for
  compound paths (fill + outline + cut-paths); ``Geometries`` iterates
  them in ``@IX`` order.
- **`Shape.geometry`** / **`Shape.geometries`** / **`Shape.add_geometry`** —
  accessors for the shape's primary path, full collection, and new-path
  factory respectively.
- **Row-type proxies** — `MoveTo`, `LineTo`, `ArcTo`,
  `EllipticalArcTo`, `NURBSTo`, `PolylineTo`, `SplineStart`,
  `SplineKnot`, `InfiniteLine`, `Ellipse`, `RelMoveTo`, `RelLineTo`,
  `RelCubBezTo`, `RelQuadBezTo`, `RelEllipticalArcTo`. Each is a
  thin wrapper over the underlying ``<Row T="…">`` element exposing
  typed cell accessors (``.x`` / ``.y`` / ``.a`` / ``.b`` / ``.c`` /
  ``.d`` / ``.e``) and :meth:`GeometryRow.set_formula` /
  :meth:`GeometryRow.get_formula` escape hatches for ``Cell/@F``
  overrides. `ArcTo.bow` is an alias for `ArcTo.a` matching the
  Visio docs' terminology.
- **`UnknownGeometryRow`** — fallback proxy for row types this
  module hasn't specialised; preserves the ``@T`` discriminator
  verbatim so parse-modify-save never drops rows.
- **Builder API** — ``geometry.move_to(x, y)``, ``.line_to(x, y)``,
  ``.arc_to(x, y, bow)``, ``.elliptical_arc_to(x, y, a, b, c, d)``,
  ``.nurbs_to(x, y, a, b, c, d, e=None)``, ``.spline_start``,
  ``.spline_knot``, ``.polyline_to``, ``.infinite_line``,
  ``.ellipse``, and the matching ``.rel_*`` variants. Each method
  returns the newly appended row proxy for chaining.
- **`Geometry.rows`** — ``list[GeometryRow]`` read accessor ordered
  by ``@IX``.
- **Section-level flag cells** — `Geometry.no_fill` / `.no_line` /
  `.no_show` / `.no_snap` / `.no_quick_drag` round-trip the direct
  ``<Cell>`` flag children every Visio Geometry section carries.
- **`Geometry.remove_row(row)`** / **`Geometries.remove(geometry)`** —
  path-level and section-level mutation. Unlike `Layers.remove`, no
  ``@IX`` renumbering happens — Visio orders geometry rows by
  document order, not by index, so gaps are tolerated and untouched
  rows preserve byte-identity.

### Tests

- **26 geometry unit tests** (`tests/unit/test_geometry.py`): builder
  API (square, arc, elliptical arc, NURBS, spline, polyline, relative
  variants), row-type dispatch (all 13 known types + unknown-type
  fallback), flag-cell round-trip, coordinate / formula setters,
  fixture-shaped parse, build → serialise → re-parse round-trip, and
  row / section removal.

## [0.2.0] — 2026-05-09

Implements `audits/2026-05-09-vsdx-0.2-scoping.md`. Seven scoping-doc
deliverables — layers, user-authored groups, background pages, the
stencil / template variants, and opaque round-trip of macro-enabled
variants. Custom geometry and the ShapeSheet formula evaluator remain
deferred to 0.3.0.

### Added — layers (scoping §4.1)

- **`vsdx.layers.Layer`** and **`vsdx.layers.Layers`** — proxies over
  the `<Section N="Layer">` on a page's `<PageSheet>`. Each `Layer`
  exposes `name` / `name_univ` / `visible` / `print` / `locked` /
  `active` / `snap` / `glue` / `color` accessors and an `index`
  property reflecting the row's `@IX`.
- **`Page.layers`** — :class:`Layers` collection on every page.
- **`Layers.add(name, *, visible=True, print=True, color="Themed")`** —
  monotonic `@IX` assignment; defaults match Visio desktop's new-layer
  dialog.
- **`Layers.remove(layer)`** — renumbers surviving layers and rewrites
  every shape's `LayerMember` cell to drop-and-decrement (matches
  Visio desktop; see scoping-doc open-question #3).
- **`Layers.get(name)`** / **`Layers.shapes_on(layer)`** — lookup and
  reverse-membership helpers.
- **`Shape.layers`** / **`Shape.set_layers(layers)`** — shape-scoped
  membership via the `<Cell N="LayerMember" V="0,2">` cell. Round-trip
  preserves caller-supplied ordering verbatim (scoping §2.5 #3).
- **`vsdx.oxml.simpletypes.ST_LayerMember`** — new simple type. Regex
  `^\d+(,\d+)*$`, 4 KiB cap, empty-string accepted.

### Added — user-authored groups (scoping §4.2)

- **`vsdx.shapes.group.GroupShape`** — `TextShape` subclass dispatched
  for `<Shape Type="Group">`. Carries `member_shapes` (a live list
  of proxy-dispatched children) plus `__iter__` / `__len__`.
- **`ShapeTree.group(shapes)`** — aggregates shapes into a new
  `GroupShape`. Computes bounding box, allocates a fresh page-scoped
  `@ID`, sets the group's PinX / PinY / Width / Height, reparents
  each member under the nested `<Shapes>`, and rewrites member
  PinX / PinY to group-local coordinates.
- **`GroupShape.ungroup()`** — inverse operation; hoists members back
  to page coordinates and removes the wrapper element.
- **`ShapeTree._proxy_for`** extended to dispatch on `@Type="Group"`
  regardless of `@Master`.

### Added — background pages (scoping §5)

- **`Page.is_background`** (bool) — read/write property mapping
  `<Page @Background="1">`.
- **`Page.background_page`** (Page | None) — resolves / writes the
  `<Page @BackPage="NameU">` reference by target `@NameU` string, not
  rel-id (per dave-howard/vsdx 0.6.1 confirmation). Setter refuses
  self-reference and non-background targets.
- **`Pages.add_background_page(name=None, ...)`** — convenience
  factory; auto-names `VBackground-N` when `name` is omitted.
- **`Pages.foreground`** / **`Pages.backgrounds`** — filter views over
  the page collection.
- **`Pages.remove(page)`** — removes a page and auto-clears dangling
  `@BackPage` references on foreground siblings (scoping-doc
  open-question #2 recommendation (b)).
- **`vsdx.oxml.page.CT_Page`** — `@Background` and `@BackPage` retyped
  to `XsdString` (0.1.0 speculated `XsdUnsignedInt` for `@BackPage`,
  which was wrong). New `@Background` attribute descriptor.

### Added — content-type variants + macro passthrough (scoping §3, §6)

- **`vsdx.Stencil(source=None)`** — factory returning a `VisioDocument`
  wrapped around a stencil package. Discriminates on root CT; raises
  `ValueError` when opened against a non-stencil.
- **`vsdx.Template(source=None)`** — factory returning a `VisioDocument`
  wrapped around a template package. Template and drawing share the
  same XML vocabulary; only the root CT differs.
- **`vsdx.VisioPackageOpener.open(source)`** — content-type-aware
  opener that delegates to `VisioPackage.open` and returns a
  `VisioDocument` regardless of package kind.
- **`VisioPackage.new(kind="drawing"|"stencil"|"template")`** —
  extended factory. Stencil builds substitute `StencilPart` at the
  root and omit the `PagesPart`.
- **`VisioPackage.kind`** property + **`VisioPackage.is_macro_enabled`** /
  **`VisioPackage.vba_project_part`** helpers.
- **`VisioDocumentPart.new_template`** — template-variant constructor
  (same XML as `new`, different content-type override).
- **`vsdx.parts.vba.VbaProjectPart`** — opaque binary passthrough for
  `/visio/vbaProject.bin`. 16 MiB size cap enforced at construction.
  Bytes never parsed or executed.
- **`vsdx.constants`** — new `CT_VSDX_MACRO_STENCIL_MAIN`,
  `CT_VSDX_MACRO_TEMPLATE_MAIN`, `CT_VBA_PROJECT`, `RT_VBA_PROJECT`,
  `VSDX_KIND_DRAWING` / `VSDX_KIND_STENCIL` / `VSDX_KIND_TEMPLATE`.
- **`VISIO_PART_TYPE_MAP`** extended with all four macro-enabled root
  content-types plus `CT_VBA_PROJECT` for the shared OPC loader
  dispatch.

### Changed

- `vsdx.__version__` → `"0.2.0.dev0"`.
- `CT_Page.back_page` descriptor widened from `XsdUnsignedInt` to
  `XsdString`.

### Tests

- **17 layer unit tests** (`tests/unit/test_layers.py`).
- **13 group unit tests** (`tests/unit/test_group.py`).
- **16 background-page unit tests** (`tests/unit/test_background_page.py`).
- **18 kind-variant unit tests** (`tests/unit/test_kind_variants.py`).
- **7 `ST_LayerMember` simple-type tests** added to
  `tests/unit/test_simpletypes.py`.

Total: 71 new unit tests; suite passes at 521 tests (up from 450 in
0.1.0). Conformance harness (5 pre-existing environment failures
unrelated to 0.2.0) unchanged; new fixtures per scoping-doc §8 land
in a separate gating step.

### Security — new 0.2.0 attack surface

- `vbaProject.bin` blobs rejected above 16 MiB at read time. No VBA
  parsing, no execution — bytes are an opaque passthrough. See
  `SECURITY.md`.

### Not yet in this release

- **Tier-4 fixtures** — the nine `.office.vsd*` fixtures in §8 of the
  scoping doc are gated on user production in Visio desktop.
- **`.vsdm → .vsdx` macro-strip on save-as** — smoke tests cover the
  per-part detection; the save-as code path becomes active once a
  `.vsdm` fixture lands.
- **Conformance harness for `.vssx` / `.vstx` / `.vsdm`** — blocked on
  fixture production.
- **Custom geometry** / **ShapeSheet formula evaluator** / **theme
  selection** — 0.3.0.

## [0.1.0]

### Added — shared-drawingml theme adoption

- **`vsdx.theme.Theme`** — high-level proxy over the
  `/visio/theme/theme1.xml` DrawingML theme part. Surfaces the theme
  `name`, `color_scheme_name`, and `font_scheme_name` attributes plus
  query / mutate helpers for the twelve colour-scheme slots
  (`dk1`–`lt2`, `accent1`–`accent6`, `hlink`, `folHlink`) and
  `major`/`minor` Latin typefaces.
- **`vsdx.document.VisioDocument.theme`** — returns the `Theme` proxy
  when the package carries a theme part, else `None`.
- **`vsdx.parts.theme.ThemePart`** — typed facade around the byte
  blob: `theme_element`, `name`, `color_scheme()`, `font_scheme()`
  helpers backed by `python-ooxml-shared-drawingml`'s hardened
  parser. Unmodified reads still round-trip byte-identically; the
  part re-serialises through lxml only after a mutation.
- **Runtime dep** — added
  `python-ooxml-shared-drawingml @ git+.../master` to
  `pyproject.toml`. Theme `CT_OfficeStyleSheet` / `CT_ColorScheme`
  / `CT_FontScheme` `CT_*` classes are not yet exported by the
  shared package; a follow-up track will switch `ThemePart` to
  `XmlPart` once they land.

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
