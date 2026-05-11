"""``DataRecordset`` + ``DataBinding`` proxies — Visio external-data binding.

A *data recordset* is a Visio-owned copy of the rows pulled from an
external data source (ODBC / OLEDB / Excel / SharePoint list). Visio
persists the ADO connection string, the command(s) that populated the
rowset, the column definitions, and the imported rows into a dedicated
XML part at ``/visio/datarecordsets/datarecordset%d.xml``. Each shape
that consumes a row binds to it via a ``<DataBinding>`` on the shape
element, citing the recordset id + row id.

Schema (per MS Learn *DataRecordset* / *DataColumn* / *DataRow* pages):

- **Part** — one ``/visio/datarecordsets/datarecordsetN.xml`` file per
  recordset. Content-type
  ``application/vnd.ms-visio.dataRecordSets+xml``.
- **Root** — ``<DataRecordset ID="n" Name="..." NameU="..."
  ADOConnection="...">`` in the Visio core namespace. Carries zero or
  more ``<Command Name="..." Text="..."/>`` children and exactly one
  ``<DataColumns>`` and one ``<DataRowset>`` container.
- **Columns** — ``<DataColumns>`` wraps one ``<DataColumn Name="..."
  Type="..." Format="..."/>`` per column. ``Type`` is one of
  ``number``/``string``/``date``/``bool``/``currency``/``custom``.
- **Rows** — ``<DataRowset>`` wraps one ``<DataRow ID="n">`` per row,
  each containing one ``<DataRowValue Column="Name" V="..."/>`` per
  non-null column value.
- **Shape binding** — a shape opts into a recordset row by adding a
  ``<DataBinding Recordset="n" Row="m"/>`` child to the ``<Shape>``
  element. One shape may bind to multiple recordsets / rows.

Scope (0.2.0-dev — R10-7):

- **Read** — parse + expose recordsets, columns, rows, bindings.
- **Preserve** — on-disk XML parts round-trip byte-faithful through
  the verbatim-blob path.
- **Security** — the ADO connection string is preserved verbatim on
  disk but never included in ``repr()`` / exception messages / log
  emissions. Callers that explicitly read :attr:`DataRecordset.
  ado_connection_string` get the raw value; everywhere else the
  value is redacted.

Authoring (``document.add_data_recordset(...)`` / ``shape.add_data_
binding(...)``) is **deferred** to a later release.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, cast

from lxml import etree

from vsdx.constants import CT_VSDX_DATARECORDSETS, NS_VSDX_CORE

_logger = logging.getLogger(__name__)


#: Tokens in an ADO / OLEDB / ODBC connection string whose *values* are
#: credentials or user-identifying handles. Matched case-insensitively
#: on the token name; the value (everything until the next ``;`` or end
#: of string) is replaced with ``<REDACTED>``.
#:
#: ``User ID`` is the OLEDB spelling (with internal space), ``UID`` the
#: ODBC spelling; ``Password`` / ``PWD`` likewise. Other credential-
#: adjacent tokens (``AccessToken``, ``Trusted_Connection``) are left
#: alone — Trusted_Connection carries no secret, and AccessToken is rare
#: enough in Visio-authored strings that we err on the side of schema
#: fidelity. If demand surfaces, extend this tuple.
_CREDENTIAL_TOKENS = ("Password", "PWD", "User ID", "UID")

_CREDENTIAL_RE = re.compile(
    r"(?i)(?P<key>" + "|".join(re.escape(t) for t in _CREDENTIAL_TOKENS) + r")"
    r"\s*=\s*[^;]*",
)


def _redact_connection_string(conn: str) -> str:
    """Return *conn* with every credential token's value replaced.

    Matches case-insensitively on the token name, preserves everything
    the user didn't configure (server, database, provider), and emits
    ``<key>=<REDACTED>`` for each sensitive token. Idempotent.
    """
    def _replace(match: re.Match[str]) -> str:
        return f"{match.group('key')}=<REDACTED>"

    return _CREDENTIAL_RE.sub(_replace, conn)


def _connection_has_credentials(conn: Optional[str]) -> bool:
    """Return True when *conn* contains any credential token."""
    if not conn:
        return False
    return _CREDENTIAL_RE.search(conn) is not None

if TYPE_CHECKING:
    from ooxml_opc import Part

    from vsdx.document import VisioDocument
    from vsdx.shapes.base import Shape


__all__ = [
    "DataBinding",
    "DataColumn",
    "DataRecordset",
    "DataRecordsets",
    "DataRow",
]


# Short alias — Visio's default namespace is the core URI.
_NS = NS_VSDX_CORE


def _qn(local: str) -> str:
    """Return the Clark-notation form of *local* in the Visio core NS."""
    return f"{{{_NS}}}{local}"


# ---------------------------------------------------------------------------
# DataColumn — one ``<DataColumn>`` inside ``<DataColumns>``.
# ---------------------------------------------------------------------------


class DataColumn:
    """One column definition on a :class:`DataRecordset`.

    Wraps a single ``<DataColumn>`` element. Read-only in 0.2.0.

    .. versionadded:: 0.2.0
    """

    def __init__(self, element: etree._Element, recordset: "DataRecordset") -> None:
        self._element = element
        self._recordset = recordset

    @property
    def name(self) -> str:
        """The column's programmatic name (``@Name``).

        Maps 1:1 to the ``Column`` attribute on ``<DataRowValue>``
        entries, and to the ShapeData field name on any shape that
        binds to a row from this recordset.
        """
        return self._element.get("Name") or ""

    @property
    def type(self) -> str:
        """The column's Visio type token (``@Type``).

        One of ``"number"`` / ``"string"`` / ``"date"`` / ``"bool"`` /
        ``"currency"`` / ``"custom"``. Returns ``"string"`` (the Visio
        default) when the attribute is absent.
        """
        return self._element.get("Type") or "string"

    @property
    def format(self) -> Optional[str]:
        """The column's display-format string (``@Format``), or ``None``.

        Format is Visio's locale-invariant picker (e.g. ``"0.##"`` for
        numbers, ``"yyyy-MM-dd"`` for dates). Preserved verbatim.
        """
        return self._element.get("Format")

    @property
    def label(self) -> Optional[str]:
        """The column's user-visible label (``@Label``), or ``None``."""
        return self._element.get("Label")

    @property
    def element(self) -> etree._Element:
        """The underlying ``<DataColumn>`` element (escape hatch)."""
        return self._element

    def __repr__(self) -> str:
        return f"<DataColumn name={self.name!r} type={self.type!r}>"


# ---------------------------------------------------------------------------
# DataRow — one ``<DataRow>`` inside ``<DataRowset>``.
# ---------------------------------------------------------------------------


def _coerce_value(raw: Optional[str], column_type: str) -> Any:
    """Coerce a row-value ``@V`` string according to its column type.

    Mirrors :meth:`~vsdx.shape_data.ShapeDataField.value` — numeric
    and currency columns return ``float``, bool returns ``bool``, and
    everything else (string / date / custom) returns the raw string.
    Returns ``None`` when *raw* is empty.
    """
    if raw is None or raw == "":
        return None
    t = column_type.lower()
    if t in ("number", "currency"):
        try:
            return float(raw)
        except ValueError:
            return raw
    if t == "bool":
        token = raw.strip().lower()
        return token in ("1", "true", "yes", "-1")
    # string, date, custom — pass through verbatim
    return raw


class DataRow:
    """One row inside a :class:`DataRecordset`.

    Wraps a ``<DataRow>`` element. Exposes the row's numeric id and a
    dict of column-name → coerced value. Read-only in 0.2.0.

    .. versionadded:: 0.2.0
    """

    def __init__(self, element: etree._Element, recordset: "DataRecordset") -> None:
        self._element = element
        self._recordset = recordset

    @property
    def row_id(self) -> int:
        """The row's recordset-scoped id (``@ID``).

        Integer-valued. Referenced by :class:`DataBinding.row` on
        shapes that cite this row. Returns ``0`` if the attribute is
        absent or non-integer (defensive).
        """
        raw = self._element.get("ID")
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    @property
    def values(self) -> Dict[str, Any]:
        """Column-name → coerced-value mapping for this row.

        Iterates every ``<DataRowValue>`` child, resolves its
        ``@Column`` attribute against the recordset's column
        definitions to discover the type, and coerces the ``@V``
        attribute accordingly. Columns absent from the row stay absent
        from the dict (Visio encodes "no value" by omitting the
        ``<DataRowValue>`` entry).
        """
        out: Dict[str, Any] = {}
        type_by_name = {c.name: c.type for c in self._recordset.columns}
        for value_el in self._element.findall(_qn("DataRowValue")):
            col = value_el.get("Column")
            if col is None:
                continue
            raw = value_el.get("V")
            col_type = type_by_name.get(col, "string")
            out[col] = _coerce_value(raw, col_type)
        return out

    @property
    def element(self) -> etree._Element:
        """The underlying ``<DataRow>`` element (escape hatch)."""
        return self._element

    def __repr__(self) -> str:
        # No column values in the repr — they may encode sensitive
        # cross-joined data that the recordset's connection string
        # also warns us not to log.
        return f"<DataRow row_id={self.row_id} columns={len(self.values)}>"


# ---------------------------------------------------------------------------
# DataRecordset — one ``/visio/datarecordsets/datarecordsetN.xml`` root.
# ---------------------------------------------------------------------------


class DataRecordset:
    """A single Visio data recordset.

    Wraps the root ``<DataRecordset>`` element of a
    ``/visio/datarecordsets/datarecordset%d.xml`` part. Callers obtain
    instances via :attr:`vsdx.document.VisioDocument.data_recordsets`.

    .. versionadded:: 0.2.0
    """

    def __init__(
        self,
        element: etree._Element,
        part: "Optional[Part]" = None,
        collection: "Optional[DataRecordsets]" = None,
    ) -> None:
        self._element = element
        self._part = part
        self._collection = collection
        # One-shot latch so the "you just pulled a credentialed connection
        # string out of a DataRecordset" log emission fires at most once
        # per proxy instance. Keeps log volume sane under batch workloads.
        self._credentials_access_warned = False

    # -- identity -------------------------------------------------------

    @property
    def id(self) -> int:
        """The recordset's document-scoped id (``@ID``).

        Referenced by :class:`DataBinding.recordset` on shapes that
        bind to rows from this recordset. Returns ``0`` on an absent
        or non-integer attribute (defensive — Visio always writes one).
        """
        raw = self._element.get("ID")
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    @property
    def name(self) -> Optional[str]:
        """The recordset's display name (``@Name`` or ``@NameU``)."""
        return self._element.get("Name") or self._element.get("NameU")

    @property
    def name_universal(self) -> Optional[str]:
        """The locale-invariant ``@NameU`` attribute."""
        return self._element.get("NameU")

    @property
    def description(self) -> Optional[str]:
        """Free-form ``@Description`` attribute, or ``None``."""
        return self._element.get("Description")

    # -- connection + commands ------------------------------------------

    @property
    def ado_connection_string(self) -> Optional[str]:
        """The ADO / OLEDB / ODBC connection string, preserved verbatim.

        **Sensitive** — this string typically contains credentials
        (username, password, server, database). It is returned verbatim
        so callers that need to reconnect to the source can do so, but
        it is **never** included in this proxy's :meth:`__repr__`, in
        any exception message raised from this module, or in any log
        emission. Callers that surface it to UIs should apply their own
        redaction — :attr:`redacted_connection_string` does this for you.

        Read from the root's ``@ADOConnection`` attribute.

        Emits a one-shot ``DeprecationWarning``-style log message on the
        first access per :class:`DataRecordset` instance when the stored
        connection string contains credential tokens
        (``Password``/``PWD``/``User ID``/``UID``). The message never
        echoes the raw string — it only names the owning part. Use
        :attr:`redacted_connection_string` for logging or UI surfacing.
        """
        raw = self._element.get("ADOConnection")
        if (
            not self._credentials_access_warned
            and _connection_has_credentials(raw)
        ):
            self._credentials_access_warned = True
            part_name = (
                self._part.partname if self._part is not None else "<synthetic>"
            )
            _logger.warning(
                "DataRecordset.ado_connection_string accessed on %s: the "
                "returned value contains credential tokens. Prefer "
                "DataRecordset.redacted_connection_string for logging or "
                "UI surfacing. This warning emits once per instance.",
                part_name,
            )
        return raw

    @property
    def redacted_connection_string(self) -> Optional[str]:
        """The ADO connection string with credential values redacted.

        Returns ``None`` when the recordset carries no ``@ADOConnection``
        attribute. Otherwise returns the raw string with every
        credential token's value replaced by ``<REDACTED>`` — the token
        name is preserved so the shape of the connection string stays
        recognisable in logs.

        The matched tokens are, case-insensitively, ``Password``,
        ``PWD``, ``User ID``, and ``UID``. Other fields (``Server``,
        ``Database``, ``Provider``, ``Initial Catalog``) are left
        untouched — they are routinely required for triaging connection
        failures and do not carry secrets on their own.

        Safe for ``logger.info("rs=%r", recordset.redacted_connection_string)``
        on user-uploaded drawings.
        """
        raw = self._element.get("ADOConnection")
        if raw is None:
            return None
        return _redact_connection_string(raw)

    @property
    def commands(self) -> List[str]:
        """List of query / command strings used to populate the rowset.

        Reads every ``<Command>`` child, returning each element's
        ``@Text`` attribute (or its text content if no attribute).
        Order matches document order. Commands may be SQL ``SELECT``
        statements, Excel range references, or SharePoint view ids;
        treated as opaque strings by this proxy.
        """
        out: List[str] = []
        for cmd in self._element.findall(_qn("Command")):
            text = cmd.get("Text")
            if text is None:
                text = cmd.text
            if text is None:
                continue
            out.append(text)
        return out

    # -- columns --------------------------------------------------------

    @property
    def columns(self) -> List[DataColumn]:
        """List of :class:`DataColumn` definitions, in document order."""
        container = self._element.find(_qn("DataColumns"))
        if container is None:
            return []
        return [
            DataColumn(el, self) for el in container.findall(_qn("DataColumn"))
        ]

    def get_column(self, name: str) -> Optional[DataColumn]:
        """Return the :class:`DataColumn` named *name*, or ``None``."""
        for column in self.columns:
            if column.name == name:
                return column
        return None

    # -- rows -----------------------------------------------------------

    @property
    def rows(self) -> List[DataRow]:
        """List of :class:`DataRow` entries, in document order."""
        container = self._element.find(_qn("DataRowset"))
        if container is None:
            return []
        return [DataRow(el, self) for el in container.findall(_qn("DataRow"))]

    def get_row(self, row_id: int) -> Optional[DataRow]:
        """Return the :class:`DataRow` with ``@ID == row_id``, or ``None``."""
        for row in self.rows:
            if row.row_id == row_id:
                return row
        return None

    # -- escape hatch ---------------------------------------------------

    @property
    def element(self) -> etree._Element:
        """The underlying ``<DataRecordset>`` element."""
        return self._element

    @property
    def part(self) -> "Optional[Part]":
        """The owning OPC :class:`~ooxml_opc.Part`, or ``None``.

        ``None`` for recordsets synthesised directly from XML bytes
        (e.g. in unit-test fixtures that bypass the package layer).
        """
        return self._part

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        """Summary repr that redacts the connection string.

        Structure matches the docstring contract: ``DataRecordset(
        name='...', columns=N, rows=M)``. The connection string and
        per-row values are **deliberately** omitted — they often carry
        credentials or PII from the bound external system.
        """
        return (
            f"DataRecordset(name={self.name!r}, "
            f"columns={len(self.columns)}, "
            f"rows={len(self.rows)})"
        )


# ---------------------------------------------------------------------------
# DataRecordsets — the document-scoped collection.
# ---------------------------------------------------------------------------


def _iter_recordset_parts(document: "VisioDocument") -> Iterator["Part"]:
    """Yield every :class:`~ooxml_opc.Part` carrying a data-recordset."""
    package = document.package
    for part in package.iter_parts():
        if part.content_type == CT_VSDX_DATARECORDSETS:
            yield part


def _parse_recordset_part(part: "Part") -> Optional[etree._Element]:
    """Parse *part*'s XML blob with the hardened Visio parser.

    Returns ``None`` if the blob is empty or the root tag is not
    ``<DataRecordset>`` (defensive — malformed parts are skipped
    rather than crashing iteration).

    Security: raises no exception that carries part content. A
    parse error is swallowed and returns ``None`` so credential-
    bearing bytes never reach a traceback.
    """
    try:
        from vsdx.oxml import parse_xml

        blob = part.blob
        if not blob:
            return None
        root = cast(etree._Element, parse_xml(blob))
        if etree.QName(root.tag).localname != "DataRecordset":
            return None
        return root
    except Exception:  # pragma: no cover — defensive
        # Deliberately swallow the exception class + args: the parser's
        # error messages may echo the part content verbatim, and the
        # part holds the connection string.
        return None


class DataRecordsets:
    """Document-scoped data-recordset collection.

    Lazy iteration over every ``application/vnd.ms-visio.dataRecordSets
    +xml`` part in the package. An empty list when the package carries
    no recordsets (the overwhelmingly common case for author-from-
    scratch Visio documents).

    .. versionadded:: 0.2.0
    """

    def __init__(self, document: "VisioDocument") -> None:
        self._document = document

    def _build(self) -> List[DataRecordset]:
        out: List[DataRecordset] = []
        for part in _iter_recordset_parts(self._document):
            root = _parse_recordset_part(part)
            if root is None:
                continue
            out.append(DataRecordset(root, part=part, collection=self))
        # Sort by @ID so Visio's declared order (not walk order) wins.
        out.sort(key=lambda r: r.id)
        return out

    def __iter__(self) -> Iterator[DataRecordset]:
        return iter(self._build())

    def __len__(self) -> int:
        return len(self._build())

    def __getitem__(self, idx: int) -> DataRecordset:
        return self._build()[idx]

    def get(self, recordset_id: int) -> Optional[DataRecordset]:
        """Return the recordset with ``@ID == recordset_id`` or ``None``."""
        for rs in self:
            if rs.id == recordset_id:
                return rs
        return None

    def get_by_name(self, name: str) -> Optional[DataRecordset]:
        """Return the recordset whose display name matches *name*.

        Compares against ``@Name`` first, then ``@NameU``. Returns
        ``None`` if nothing matches.
        """
        for rs in self:
            if rs.name == name or rs.name_universal == name:
                return rs
        return None


# ---------------------------------------------------------------------------
# DataBinding — one ``<DataBinding>`` on a ``<Shape>``.
# ---------------------------------------------------------------------------


class DataBinding:
    """One shape→row binding.

    Wraps a single ``<DataBinding Recordset="n" Row="m"/>`` child of
    a ``<Shape>``. Provides typed access to the linked
    :class:`DataRecordset` + :class:`DataRow`, and a read-only
    column-name → value dict for the linked row.

    Read-only in 0.2.0.

    .. versionadded:: 0.2.0
    """

    def __init__(
        self,
        element: etree._Element,
        shape: "Shape",
        document: "VisioDocument",
    ) -> None:
        self._element = element
        self._shape = shape
        self._document = document

    # -- raw attributes -------------------------------------------------

    @property
    def recordset_id(self) -> int:
        """The bound recordset's id (``@Recordset``), or ``0``."""
        raw = self._element.get("Recordset")
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    @property
    def row_id(self) -> int:
        """The bound row's id (``@Row``), or ``0``."""
        raw = self._element.get("Row")
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    # -- typed resolution ----------------------------------------------

    @property
    def recordset(self) -> Optional[DataRecordset]:
        """The resolved :class:`DataRecordset`, or ``None`` if orphaned.

        Defensive against hand-edited packages — returns ``None`` when
        the referenced id has no matching recordset in the document.
        """
        return self._document.data_recordsets.get(self.recordset_id)

    @property
    def row(self) -> Optional[DataRow]:
        """The resolved :class:`DataRow`, or ``None`` if orphaned."""
        rs = self.recordset
        if rs is None:
            return None
        return rs.get_row(self.row_id)

    @property
    def column_values(self) -> Dict[str, Any]:
        """Read-only column-name → value dict for the bound row.

        Empty when either the recordset or the row cannot be resolved.
        Values are coerced per the recordset's column types (see
        :attr:`DataRow.values`).
        """
        row = self.row
        if row is None:
            return {}
        return row.values

    # -- escape hatch ---------------------------------------------------

    @property
    def element(self) -> etree._Element:
        """The underlying ``<DataBinding>`` element."""
        return self._element

    def __repr__(self) -> str:
        return (
            f"DataBinding(recordset_id={self.recordset_id}, "
            f"row_id={self.row_id})"
        )


# ---------------------------------------------------------------------------
# Shape-side resolution helpers.
# ---------------------------------------------------------------------------


def _shape_data_bindings(
    shape: "Shape", document: "VisioDocument"
) -> List[DataBinding]:
    """Return every ``<DataBinding>`` on *shape* as proxy objects.

    Walks the shape's direct children for ``{vsdx:}DataBinding``
    elements. Returns an empty list when the shape has none (the
    common case).

    Called from :attr:`vsdx.shapes.base.Shape.data_bindings` — kept
    adjacent to :class:`DataBinding` so the resolution logic lives
    with the schema knowledge.
    """
    out: List[DataBinding] = []
    for child in shape._element.findall(_qn("DataBinding")):
        out.append(DataBinding(child, shape, document))
    return out
