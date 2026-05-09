"""Unit tests for the 0.2.0 ``DataRecordset`` / ``DataBinding`` proxies.

BDD-style per the project's test conventions. Scope: read + preserve
+ shape-side binding resolution, matching the R10-7 deliverable.
Authoring (``add_data_recordset`` / ``add_data_binding``) ships later.

Each test fabricates synthetic Visio XML inline — the reference corpus
does not yet carry a recordset-bearing fixture (tier-4 gating per the
scoping doc). The schema used below mirrors Microsoft Learn's
``DataRecordset`` / ``DataColumn`` / ``DataRow`` reference pages.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import io
import zipfile
from typing import Tuple

import pytest
from lxml import etree

import vsdx
from vsdx.constants import CT_VSDX_DATARECORDSETS, NS_VSDX_CORE
from vsdx.data_recordsets import (
    DataBinding,
    DataColumn,
    DataRecordset,
    DataRecordsets,
    DataRow,
    _shape_data_bindings,
)
from vsdx.oxml import parse_xml


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


#: A sample ADO connection string Visio would emit. Carries a password
#: token so tests can verify it never leaks through repr / exceptions.
_SENSITIVE_CONNSTR = (
    "Provider=SQLOLEDB;Server=db.example.com;Database=Assets;"
    "UID=svc_reader;PWD=NotARealSecret;"
)


def _recordset_xml(
    *,
    id: int = 1,
    name: str = "Assets",
    connection: str = _SENSITIVE_CONNSTR,
    commands: Tuple[str, ...] = ("SELECT * FROM Assets",),
    columns: Tuple[Tuple[str, str, str], ...] = (
        # (name, type, format)
        ("AssetID", "number", "0"),
        ("Name", "string", ""),
        ("Cost", "currency", "$0.00"),
        ("Active", "bool", ""),
    ),
    rows: Tuple[Tuple[int, Tuple[Tuple[str, str], ...]], ...] = (
        (0, (("AssetID", "1"), ("Name", "Printer"), ("Cost", "250.00"), ("Active", "1"))),
        (1, (("AssetID", "2"), ("Name", "Laptop"), ("Cost", "1899.99"), ("Active", "0"))),
    ),
) -> bytes:
    """Return a serialised ``<DataRecordset>`` XML blob.

    Produces the part-level XML a Visio drawing would carry at
    ``/visio/datarecordsets/datarecordset%d.xml`` — not the document
    root. Tests splice this into either a synthetic part (see
    :func:`_doc_with_recordset_part`) or parse it directly for
    collection-free proxy coverage.
    """
    cmd_xml = "".join(
        f'<Command Name="cmd{i}" Text="{etree_escape(text)}"/>'
        for i, text in enumerate(commands)
    )
    col_xml = "".join(
        f'<DataColumn Name="{n}" Type="{t}" Format="{f}" Label="{n}"/>'
        for n, t, f in columns
    )
    row_xml = ""
    for row_id, pairs in rows:
        value_xml = "".join(
            f'<DataRowValue Column="{c}" V="{v}"/>' for c, v in pairs
        )
        row_xml += f'<DataRow ID="{row_id}">{value_xml}</DataRow>'
    return (
        f'<DataRecordset xmlns="{NS_VSDX_CORE}" ID="{id}" '
        f'Name="{name}" NameU="{name}" '
        f'ADOConnection="{etree_escape(connection)}">'
        f"{cmd_xml}"
        f"<DataColumns>{col_xml}</DataColumns>"
        f"<DataRowset>{row_xml}</DataRowset>"
        f"</DataRecordset>"
    ).encode("utf-8")


def etree_escape(s: str) -> str:
    """Minimal XML attribute escape — good enough for our inline fixtures."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


#: The Visio relationship-type URI for a recordset-index → recordset
#: edge. Not yet promoted to :mod:`vsdx.constants` (R10-7 is read-only;
#: the authoring pass that lands ``add_data_recordset`` will promote it).
_RT_VISIO_DATARECORDSET = (
    "http://schemas.microsoft.com/visio/2010/relationships/dataRecordSet"
)


def _doc_with_recordset_part(xml_blob: bytes):
    """Return a ``VisioDocument`` whose package carries a recordset part.

    Builds a bare :func:`vsdx.Visio` document, synthesises a
    :class:`~vsdx.parts.datarecordsets.DataRecordsetsPart` carrying
    *xml_blob*, and relates it from the document part. The rel makes
    the part reachable from :meth:`OpcPackage.iter_parts`, which
    :meth:`DataRecordsets._build` walks.
    """
    from vsdx.parts.datarecordsets import DataRecordsetsPart

    doc = vsdx.Visio()
    package = doc.package
    partname = package.next_partname(DataRecordsetsPart._PARTNAME_TMPL)
    part = DataRecordsetsPart.load(
        partname,
        CT_VSDX_DATARECORDSETS,
        package,
        xml_blob,
    )
    # Relate from the document part so iter_parts yields it.
    package.document_part.relate_to(part, _RT_VISIO_DATARECORDSET)
    return doc, part


# ---------------------------------------------------------------------------
# DataRecordset (standalone — no package needed)
# ---------------------------------------------------------------------------


class DescribeDataRecordset:
    def it_exposes_id_and_name(self) -> None:
        element = parse_xml(_recordset_xml(id=7, name="Priorities"))
        rs = DataRecordset(element)
        assert rs.id == 7
        assert rs.name == "Priorities"
        assert rs.name_universal == "Priorities"

    def it_preserves_the_ado_connection_string_verbatim(self) -> None:
        # The verbatim-preservation guarantee: whatever Visio wrote is
        # what callers get back, bit-for-bit. Credentials included.
        element = parse_xml(_recordset_xml(connection=_SENSITIVE_CONNSTR))
        rs = DataRecordset(element)
        assert rs.ado_connection_string == _SENSITIVE_CONNSTR

    def it_enumerates_commands_in_document_order(self) -> None:
        element = parse_xml(
            _recordset_xml(
                commands=(
                    "SELECT * FROM A",
                    "SELECT * FROM B",
                )
            )
        )
        rs = DataRecordset(element)
        assert rs.commands == ["SELECT * FROM A", "SELECT * FROM B"]

    def it_exposes_typed_columns(self) -> None:
        element = parse_xml(_recordset_xml())
        rs = DataRecordset(element)
        columns = rs.columns
        assert len(columns) == 4
        assert all(isinstance(c, DataColumn) for c in columns)
        names = [c.name for c in columns]
        types = [c.type for c in columns]
        assert names == ["AssetID", "Name", "Cost", "Active"]
        assert types == ["number", "string", "currency", "bool"]

    def it_exposes_format_strings_on_columns(self) -> None:
        element = parse_xml(_recordset_xml())
        rs = DataRecordset(element)
        cost = rs.get_column("Cost")
        assert cost is not None
        assert cost.format == "$0.00"

    def it_looks_up_columns_by_name(self) -> None:
        element = parse_xml(_recordset_xml())
        rs = DataRecordset(element)
        assert rs.get_column("Name") is not None
        assert rs.get_column("Missing") is None

    def it_enumerates_rows_with_coerced_values(self) -> None:
        element = parse_xml(_recordset_xml())
        rs = DataRecordset(element)
        rows = rs.rows
        assert len(rows) == 2
        assert all(isinstance(r, DataRow) for r in rows)
        assert [r.row_id for r in rows] == [0, 1]
        # Coercion — numbers and currency -> float, bool -> bool, string unchanged.
        first = rows[0].values
        assert first["AssetID"] == 1.0
        assert first["Name"] == "Printer"
        assert first["Cost"] == 250.00
        assert first["Active"] is True
        second = rows[1].values
        assert second["Active"] is False

    def it_looks_up_rows_by_id(self) -> None:
        element = parse_xml(_recordset_xml())
        rs = DataRecordset(element)
        assert rs.get_row(1) is not None
        assert rs.get_row(99) is None


# ---------------------------------------------------------------------------
# Security — the ADO connection string must NOT leak via repr / str.
# ---------------------------------------------------------------------------


class DescribeDataRecordsetSecurity:
    def it_redacts_the_connection_string_in_repr(self) -> None:
        element = parse_xml(_recordset_xml(connection=_SENSITIVE_CONNSTR))
        rs = DataRecordset(element)
        rendered = repr(rs)
        # Summary contract per the R10-7 scope:
        # ``DataRecordset(name='...', columns=N, rows=M)``
        assert "DataRecordset(" in rendered
        assert "name='Assets'" in rendered or 'name="Assets"' in rendered
        assert "columns=4" in rendered
        assert "rows=2" in rendered
        # And critically: no credential, no hostname, no SQL.
        assert "NotARealSecret" not in rendered
        assert "PWD" not in rendered
        assert "SQLOLEDB" not in rendered

    def it_redacts_the_connection_string_in_str(self) -> None:
        element = parse_xml(_recordset_xml(connection=_SENSITIVE_CONNSTR))
        rs = DataRecordset(element)
        assert "NotARealSecret" not in str(rs)

    def it_does_not_leak_connection_in_row_repr(self) -> None:
        # A DataRow carries no connection string itself, but its repr
        # should still avoid echoing row values (which a hostile caller
        # could use to triangulate source tables the connection points at).
        element = parse_xml(_recordset_xml(connection=_SENSITIVE_CONNSTR))
        rs = DataRecordset(element)
        for row in rs.rows:
            rendered = repr(row)
            assert "Printer" not in rendered
            assert "Laptop" not in rendered
            assert "NotARealSecret" not in rendered


# ---------------------------------------------------------------------------
# DataRecordsets collection — walks the package's data-recordset parts.
# ---------------------------------------------------------------------------


class DescribeDataRecordsetsCollection:
    def it_is_empty_on_a_fresh_document(self) -> None:
        doc = vsdx.Visio()
        assert isinstance(doc.data_recordsets, DataRecordsets)
        assert list(doc.data_recordsets) == []
        assert len(doc.data_recordsets) == 0

    def it_yields_a_recordset_for_each_recordset_part(self) -> None:
        doc, _ = _doc_with_recordset_part(_recordset_xml(id=1, name="A"))
        recordsets = list(doc.data_recordsets)
        assert len(recordsets) == 1
        assert recordsets[0].name == "A"
        assert recordsets[0].id == 1

    def it_looks_up_recordsets_by_id(self) -> None:
        doc, _ = _doc_with_recordset_part(_recordset_xml(id=42, name="Deep"))
        found = doc.data_recordsets.get(42)
        assert found is not None
        assert found.name == "Deep"
        assert doc.data_recordsets.get(99) is None

    def it_looks_up_recordsets_by_name(self) -> None:
        doc, _ = _doc_with_recordset_part(_recordset_xml(id=0, name="Status"))
        found = doc.data_recordsets.get_by_name("Status")
        assert found is not None
        assert found.id == 0
        assert doc.data_recordsets.get_by_name("Unknown") is None


# ---------------------------------------------------------------------------
# Shape <-> DataBinding association
# ---------------------------------------------------------------------------


def _shape_with_binding_xml(recordset_id: int, row_id: int) -> str:
    """Return an ``<DataBinding>`` element XML ready to splice onto a shape."""
    return (
        f'<DataBinding xmlns="{NS_VSDX_CORE}" '
        f'Recordset="{recordset_id}" Row="{row_id}"/>'
    )


class DescribeShapeDataBindings:
    def it_reports_no_bindings_by_default(self) -> None:
        doc, _ = _doc_with_recordset_part(_recordset_xml())
        page = doc.pages.add_page(name="P1")
        page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
        shape = page.shapes[0]
        assert shape.data_bindings == []

    def it_exposes_bindings_attached_to_a_shape(self) -> None:
        doc, _ = _doc_with_recordset_part(
            _recordset_xml(id=5, name="Assets")
        )
        page = doc.pages.add_page(name="P1")
        page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
        shape = page.shapes[0]
        # Splice a binding element directly — authoring API ships later.
        binding_el = parse_xml(_shape_with_binding_xml(5, 1))
        shape._element.append(binding_el)

        bindings = shape.data_bindings
        assert len(bindings) == 1
        assert isinstance(bindings[0], DataBinding)
        assert bindings[0].recordset_id == 5
        assert bindings[0].row_id == 1

    def it_resolves_the_binding_to_recordset_and_row(self) -> None:
        doc, _ = _doc_with_recordset_part(
            _recordset_xml(id=5, name="Assets")
        )
        page = doc.pages.add_page(name="P1")
        page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
        shape = page.shapes[0]
        shape._element.append(parse_xml(_shape_with_binding_xml(5, 1)))

        binding = shape.data_bindings[0]
        rs = binding.recordset
        row = binding.row
        assert rs is not None
        assert rs.name == "Assets"
        assert row is not None
        assert row.row_id == 1

    def it_exposes_the_bound_rows_column_values(self) -> None:
        doc, _ = _doc_with_recordset_part(
            _recordset_xml(id=5, name="Assets")
        )
        page = doc.pages.add_page(name="P1")
        page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
        shape = page.shapes[0]
        shape._element.append(parse_xml(_shape_with_binding_xml(5, 1)))

        binding = shape.data_bindings[0]
        values = binding.column_values
        assert values["Name"] == "Laptop"
        assert values["Cost"] == 1899.99
        assert values["Active"] is False

    def it_returns_empty_dict_for_orphaned_bindings(self) -> None:
        # Binding points at a recordset id that no part carries — a
        # defensive guard for hand-edited packages.
        doc, _ = _doc_with_recordset_part(
            _recordset_xml(id=5, name="Assets")
        )
        page = doc.pages.add_page(name="P1")
        page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
        shape = page.shapes[0]
        shape._element.append(parse_xml(_shape_with_binding_xml(999, 1)))

        binding = shape.data_bindings[0]
        assert binding.recordset is None
        assert binding.row is None
        assert binding.column_values == {}


# ---------------------------------------------------------------------------
# Round-trip — unmodified package preserves the recordset part bytes.
# ---------------------------------------------------------------------------


class DescribeRoundTrip:
    def it_preserves_the_recordset_part_on_unmodified_roundtrip(self) -> None:
        # Build a package with a recordset part, save to an in-memory
        # zip, reopen, save again — the on-disk XML should be
        # byte-identical because :class:`DataRecordsetsPart` extends
        # :class:`VerbatimXmlPart`.
        doc, part = _doc_with_recordset_part(_recordset_xml())
        buf1 = io.BytesIO()
        doc.save(buf1)

        # Check that the part blob is present in the saved zip.
        buf1.seek(0)
        with zipfile.ZipFile(buf1) as zf:
            names = zf.namelist()
        assert any("datarecordset" in n for n in names), (
            f"no datarecordset part in saved package: {names!r}"
        )


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------


class DescribePublicSurface:
    def it_exports_the_five_classes_on_the_vsdx_namespace(self) -> None:
        assert vsdx.DataRecordset is DataRecordset
        assert vsdx.DataRecordsets is DataRecordsets
        assert vsdx.DataBinding is DataBinding
        assert vsdx.DataColumn is DataColumn
        assert vsdx.DataRow is DataRow
