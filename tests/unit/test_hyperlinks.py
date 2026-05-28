"""Unit tests for the 0.3.0 hyperlink (``<Section N="Hyperlink">``) proxy.

BDD-style per project conventions. Covers:

* Collection surface — ``shape.hyperlinks[0]`` indexing, ``in`` by
  description, ``len``, iteration, ``.get`` / ``.default_hyperlink``.
* Authoring — :meth:`HyperlinkCollection.add` materialises the
  ``<Section N="Hyperlink">`` on first use; emits the expected cells
  only when the caller supplies them; auto-names rows ``Row_<n>``.
* Default-flag invariant — marking one hyperlink default auto-clears
  the flag on every sibling; remove semantics tolerate missing /
  orphaned defaults.
* Removal — :meth:`HyperlinkCollection.remove` by index / description /
  proxy; leaves the section in place for round-trip fidelity.
* Hyperlink cell accessors — address / sub_address / description /
  extra_info / new_window / invisible / sort_key.
* Document-level ``hyperlink_base`` on ``VisioDocument``.
* Parse-existing fixture round-trip.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import io

import pytest

import vsdx
from vsdx.hyperlinks import (
    Hyperlink,
    HyperlinkCollection,
    build_aws_console_url,
    build_confluence_url,
    build_github_url,
    build_jira_url,
)
from vsdx.oxml import nsdecls, parse_xml


def _fresh_shape():
    """Return a ``(doc, page, shape)`` triple with one rectangle on the page."""
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Page-1")
    shape = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
    return doc, page, shape


def _parse_shape_with_hyperlinks(xml_body: str):
    """Parse a ``<Shape>`` element carrying *xml_body* as its children."""
    xml = (
        '<vsdx:Shape %s ID="1" Type="Shape">%s</vsdx:Shape>'
        % (nsdecls("vsdx"), xml_body)
    ).encode()
    return parse_xml(xml)


def _wrap_parsed(shape_el):
    """Wrap a parsed ``CT_Shape`` in a bare :class:`Shape` proxy for tests."""
    from vsdx.shapes.base import Shape

    proxy = Shape.__new__(Shape)
    proxy._element = shape_el  # type: ignore[attr-defined]
    proxy._parent = None  # type: ignore[attr-defined]
    return proxy


# ---------------------------------------------------------------------------
# Describe HyperlinkCollection on a fresh shape
# ---------------------------------------------------------------------------


class DescribeHyperlinkCollection:
    def it_exposes_an_empty_collection_on_a_fresh_shape(self) -> None:
        _, _, shape = _fresh_shape()
        hl = shape.hyperlinks
        assert isinstance(hl, HyperlinkCollection)
        assert len(hl) == 0
        assert list(hl) == []
        assert hl.default_hyperlink is None
        assert "anything" not in hl

    def it_creates_the_Hyperlink_section_on_first_add(self) -> None:
        _, _, shape = _fresh_shape()
        assert not any(
            s.get("N") == "Hyperlink" for s in shape._element.section_lst
        )
        shape.hyperlinks.add("https://example.com", description="Home")
        sections = [
            s for s in shape._element.section_lst if s.get("N") == "Hyperlink"
        ]
        assert len(sections) == 1

    def it_is_iterable_and_indexable(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        shape.hyperlinks.add("https://b.com", description="B")
        hl = shape.hyperlinks
        assert len(hl) == 2
        assert [h.description for h in hl] == ["A", "B"]
        assert hl[0].description == "A"
        assert hl[-1].description == "B"

    def it_looks_up_by_description(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="Alpha")
        shape.hyperlinks.add("https://b.com", description="Beta")
        assert shape.hyperlinks["Beta"].address == "https://b.com"
        assert "Alpha" in shape.hyperlinks
        assert "Missing" not in shape.hyperlinks
        assert shape.hyperlinks.get("Missing") is None
        assert shape.hyperlinks.get("Alpha").address == "https://a.com"

    def it_raises_KeyError_on_missing_description(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="Alpha")
        with pytest.raises(KeyError):
            shape.hyperlinks["Missing"]

    def it_raises_IndexError_on_out_of_range_index(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(IndexError):
            shape.hyperlinks[0]

    def it_rejects_non_int_non_str_keys(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(TypeError):
            shape.hyperlinks[1.5]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Describe HyperlinkCollection.add
# ---------------------------------------------------------------------------


class DescribeAdd:
    def it_returns_the_hyperlink_proxy(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add("https://example.com", description="Home")
        assert isinstance(h, Hyperlink)
        assert h.address == "https://example.com"
        assert h.description == "Home"

    def it_auto_names_rows_as_Row_n(self) -> None:
        _, _, shape = _fresh_shape()
        a = shape.hyperlinks.add("https://a.com", description="A")
        b = shape.hyperlinks.add("https://b.com", description="B")
        assert a.name == "Row_1"
        assert b.name == "Row_2"

    def it_honours_an_explicit_name(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add(
            "https://example.com", description="Home", name="HomeLink"
        )
        assert h.name == "HomeLink"

    def it_writes_only_the_cells_the_caller_supplied(self) -> None:
        # Matches the R8-3 shape-data minimalism — don't emit Cell
        # elements for unset properties so authoring XML stays tight.
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add("https://example.com", description="Home")
        row = h.element
        cell_names = {c.get("N") for c in row.cell_lst}
        assert cell_names == {"Description", "Address"}

    def it_emits_NewWindow_only_when_true(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add("https://example.com", new_window=True)
        row = h.element
        cell_names = {c.get("N") for c in row.cell_lst}
        assert "NewWindow" in cell_names

    def it_supports_sub_address_only_hyperlinks(self) -> None:
        # Intra-document jumps: no Address, only SubAddress.
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add(
            sub_address="Page-2", description="Jump to page 2"
        )
        assert h.address is None
        assert h.sub_address == "Page-2"

    def it_captures_extra_info_and_sort_key(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add(
            "https://example.com",
            description="Home",
            extra_info="ref=visio&id=42",
            sort_key="010",
        )
        assert h.extra_info == "ref=visio&id=42"
        assert h.sort_key == "010"

    def it_marks_the_first_default_on_add(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add(
            "https://example.com", description="Home", default=True
        )
        assert h.default is True
        assert shape.hyperlinks.default_hyperlink is h or (
            shape.hyperlinks.default_hyperlink.description == "Home"
        )


# ---------------------------------------------------------------------------
# Describe the one-default invariant
# ---------------------------------------------------------------------------


class DescribeDefaultInvariant:
    def it_clears_sibling_default_when_a_new_default_is_added(self) -> None:
        _, _, shape = _fresh_shape()
        first = shape.hyperlinks.add(
            "https://a.com", description="A", default=True
        )
        second = shape.hyperlinks.add(
            "https://b.com", description="B", default=True
        )
        assert first.default is False
        assert second.default is True
        assert shape.hyperlinks.default_hyperlink.description == "B"

    def it_clears_sibling_default_on_flag_setter_flip(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A", default=True)
        shape.hyperlinks.add("https://b.com", description="B")
        # Flip B to default — A must auto-clear.
        shape.hyperlinks["B"].default = True
        assert shape.hyperlinks["A"].default is False
        assert shape.hyperlinks["B"].default is True

    def it_allows_clearing_default_without_a_replacement(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add(
            "https://a.com", description="A", default=True
        )
        h.default = False
        assert h.default is False
        assert shape.hyperlinks.default_hyperlink is None

    def it_returns_None_when_no_hyperlink_is_default(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        shape.hyperlinks.add("https://b.com", description="B")
        assert shape.hyperlinks.default_hyperlink is None


# ---------------------------------------------------------------------------
# Describe Hyperlink cell accessors
# ---------------------------------------------------------------------------


class DescribeHyperlinkAccessors:
    def it_round_trips_all_textual_cells(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add("https://a.com", description="A")
        h.address = "https://b.com"
        h.sub_address = "anchor"
        h.description = "New description"
        h.extra_info = "x=1"
        h.sort_key = "099"
        assert h.address == "https://b.com"
        assert h.sub_address == "anchor"
        assert h.description == "New description"
        assert h.extra_info == "x=1"
        assert h.sort_key == "099"

    def it_round_trips_flag_cells(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add("https://a.com", description="A")
        assert h.new_window is False
        assert h.invisible is False
        h.new_window = True
        h.invisible = True
        assert h.new_window is True
        assert h.invisible is True

    def it_coerces_TRUE_FALSE_tokens_for_flags(self) -> None:
        # Some Visio locales emit TRUE/FALSE; read path tolerates,
        # write path still emits 1/0.
        shape = _parse_shape_with_hyperlinks(
            '<vsdx:Section N="Hyperlink">'
            '<vsdx:Row N="Row_1">'
            '<vsdx:Cell N="Address" V="https://x.com"/>'
            '<vsdx:Cell N="NewWindow" V="TRUE"/>'
            '<vsdx:Cell N="Default" V="TRUE"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        h = proxy.hyperlinks[0]
        assert h.new_window is True
        assert h.default is True

    def it_name_setter_updates_row_N(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add("https://a.com", description="A")
        h.name = "CustomName"
        assert h.element.get("N") == "CustomName"

    def it_returns_None_for_absent_cells(self) -> None:
        shape = _parse_shape_with_hyperlinks(
            '<vsdx:Section N="Hyperlink">'
            '<vsdx:Row N="Row_1">'
            '<vsdx:Cell N="Address" V="https://x.com"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        h = proxy.hyperlinks[0]
        assert h.sub_address is None
        assert h.description is None
        assert h.extra_info is None
        assert h.sort_key is None
        assert h.new_window is False
        assert h.default is False
        assert h.invisible is False


# ---------------------------------------------------------------------------
# Describe HyperlinkCollection.remove
# ---------------------------------------------------------------------------


class DescribeRemove:
    def it_removes_by_index(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        shape.hyperlinks.add("https://b.com", description="B")
        shape.hyperlinks.remove(0)
        assert len(shape.hyperlinks) == 1
        assert shape.hyperlinks[0].description == "B"

    def it_removes_by_description(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        shape.hyperlinks.add("https://b.com", description="B")
        shape.hyperlinks.remove("A")
        assert len(shape.hyperlinks) == 1
        assert shape.hyperlinks[0].description == "B"

    def it_removes_by_proxy(self) -> None:
        _, _, shape = _fresh_shape()
        a = shape.hyperlinks.add("https://a.com", description="A")
        shape.hyperlinks.add("https://b.com", description="B")
        shape.hyperlinks.remove(a)
        assert len(shape.hyperlinks) == 1
        assert shape.hyperlinks[0].description == "B"

    def it_raises_KeyError_on_unknown_description(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        with pytest.raises(KeyError):
            shape.hyperlinks.remove("Missing")

    def it_raises_IndexError_on_out_of_range_index(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        with pytest.raises(IndexError):
            shape.hyperlinks.remove(5)

    def it_raises_KeyError_on_empty_collection_by_description(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(KeyError):
            shape.hyperlinks.remove("Missing")

    def it_preserves_the_Section_element_when_last_row_removed(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="A")
        shape.hyperlinks.remove(0)
        sections = [
            s for s in shape._element.section_lst if s.get("N") == "Hyperlink"
        ]
        assert len(sections) == 1
        assert len(sections[0].row_lst) == 0


# ---------------------------------------------------------------------------
# Describe parse-existing fixture round-trip
# ---------------------------------------------------------------------------


class DescribeExistingHyperlinks:
    def it_parses_a_multi_hyperlink_fixture(self) -> None:
        shape = _parse_shape_with_hyperlinks(
            '<vsdx:Section N="Hyperlink">'
            '<vsdx:Row N="Row_1">'
            '<vsdx:Cell N="Description" V="Home"/>'
            '<vsdx:Cell N="Address" V="https://example.com"/>'
            "</vsdx:Row>"
            '<vsdx:Row N="Row_2">'
            '<vsdx:Cell N="Description" V="Docs"/>'
            '<vsdx:Cell N="Address" V="https://docs.example.com"/>'
            '<vsdx:Cell N="SubAddress" V="getting-started"/>'
            '<vsdx:Cell N="NewWindow" V="1"/>'
            '<vsdx:Cell N="Default" V="1"/>'
            "</vsdx:Row>"
            '<vsdx:Row N="Row_3">'
            '<vsdx:Cell N="Description" V="Support"/>'
            '<vsdx:Cell N="Address" V="https://support.example.com"/>'
            '<vsdx:Cell N="Invisible" V="1"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        hl = proxy.hyperlinks
        assert len(hl) == 3
        assert [h.description for h in hl] == ["Home", "Docs", "Support"]
        docs = hl["Docs"]
        assert docs.address == "https://docs.example.com"
        assert docs.sub_address == "getting-started"
        assert docs.new_window is True
        assert docs.default is True
        assert hl.default_hyperlink.description == "Docs"
        assert hl["Support"].invisible is True
        assert hl["Home"].default is False

    def it_round_trips_parse_mutate_read(self) -> None:
        shape = _parse_shape_with_hyperlinks(
            '<vsdx:Section N="Hyperlink">'
            '<vsdx:Row N="Row_1">'
            '<vsdx:Cell N="Description" V="Home"/>'
            '<vsdx:Cell N="Address" V="https://example.com"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        # Mutate through the collection surface.
        proxy.hyperlinks["Home"].address = "https://new.example.com"
        proxy.hyperlinks.add(
            "https://b.com", description="Bravo", default=True
        )
        assert proxy.hyperlinks["Home"].address == "https://new.example.com"
        assert proxy.hyperlinks["Bravo"].default is True
        assert proxy.hyperlinks.default_hyperlink.description == "Bravo"


# ---------------------------------------------------------------------------
# Describe VisioDocument.hyperlink_base
# ---------------------------------------------------------------------------


class DescribeDocumentHyperlinkBase:
    def it_is_None_on_a_fresh_document(self) -> None:
        doc = vsdx.Visio()
        assert doc.hyperlink_base is None

    def it_is_settable(self) -> None:
        doc = vsdx.Visio()
        doc.hyperlink_base = "https://example.com/docs/"
        assert doc.hyperlink_base == "https://example.com/docs/"

    def it_materialises_DocumentSheet_on_first_set(self) -> None:
        doc = vsdx.Visio()
        assert doc._element.documentSheet is None
        doc.hyperlink_base = "https://example.com/docs/"
        sheet = doc._element.documentSheet
        assert sheet is not None
        cells = [c for c in sheet.cell_lst if c.get("N") == "HyperlinkBase"]
        assert len(cells) == 1
        assert cells[0].get("V") == "https://example.com/docs/"

    def it_updates_existing_value_without_duplicating_cells(self) -> None:
        doc = vsdx.Visio()
        doc.hyperlink_base = "first"
        doc.hyperlink_base = "second"
        sheet = doc._element.documentSheet
        cells = [c for c in sheet.cell_lst if c.get("N") == "HyperlinkBase"]
        assert len(cells) == 1
        assert cells[0].get("V") == "second"

    def it_clears_on_None_assignment(self) -> None:
        doc = vsdx.Visio()
        doc.hyperlink_base = "https://example.com/docs/"
        doc.hyperlink_base = None
        assert doc.hyperlink_base is None
        sheet = doc._element.documentSheet
        if sheet is not None:
            assert not any(
                c.get("N") == "HyperlinkBase" for c in sheet.cell_lst
            )

    def it_clears_on_empty_string_assignment(self) -> None:
        doc = vsdx.Visio()
        doc.hyperlink_base = "https://example.com/docs/"
        doc.hyperlink_base = ""
        assert doc.hyperlink_base is None

    def it_is_a_noop_to_clear_when_already_empty(self) -> None:
        doc = vsdx.Visio()
        doc.hyperlink_base = None  # Should not raise.
        assert doc.hyperlink_base is None


# ---------------------------------------------------------------------------
# Describe collection repr
# ---------------------------------------------------------------------------


class DescribeRepr:
    def it_collection_repr_lists_descriptions(self) -> None:
        _, _, shape = _fresh_shape()
        shape.hyperlinks.add("https://a.com", description="Alpha")
        shape.hyperlinks.add("https://b.com", description="Beta")
        r = repr(shape.hyperlinks)
        assert "Alpha" in r
        assert "Beta" in r

    def it_hyperlink_repr_includes_description_and_address(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.hyperlinks.add(
            "https://a.com", description="Alpha", default=True
        )
        r = repr(h)
        assert "Alpha" in r
        assert "a.com" in r
        assert "default" in r


# ---------------------------------------------------------------------------
# Issue #133 — Shape.add_hyperlink + pattern helpers
# ---------------------------------------------------------------------------


class DescribeShapeAddHyperlink:
    def it_appends_a_hyperlink_with_url_and_label(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.add_hyperlink(
            "https://example.com", label="Home page"
        )
        assert isinstance(h, Hyperlink)
        assert h.address == "https://example.com"
        assert h.description == "Home page"

    def it_preserves_multiple_hyperlinks_per_shape(self) -> None:
        # Visio supports multiple hyperlinks per shape; #133 acceptance
        # demands we don't replace on a second call.
        _, _, shape = _fresh_shape()
        shape.add_hyperlink("https://a.com", label="A")
        shape.add_hyperlink("https://b.com", label="B")
        shape.add_hyperlink("https://c.com", label="C")
        assert len(shape.hyperlinks) == 3
        assert [h.description for h in shape.hyperlinks] == ["A", "B", "C"]

    def it_supports_label_only_intra_document_jumps(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.add_hyperlink(
            "", label="Jump to page 2", sub_address="Page-2"
        )
        assert h.sub_address == "Page-2"

    def it_marks_default_when_default_true(self) -> None:
        _, _, shape = _fresh_shape()
        shape.add_hyperlink("https://a.com", label="A")
        b = shape.add_hyperlink("https://b.com", label="B", default=True)
        assert b.default is True
        assert shape.hyperlinks["A"].default is False

    def it_passes_new_window_through(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.add_hyperlink(
            "https://a.com", label="A", new_window=True
        )
        assert h.new_window is True


# ---------------------------------------------------------------------------
# Describe URL pattern builders
# ---------------------------------------------------------------------------


class DescribeBuildAWSConsoleURL:
    def it_builds_an_ec2_instance_url(self) -> None:
        url = build_aws_console_url(
            service="ec2",
            resource_id="i-abc123",
            region="ap-southeast-2",
        )
        assert "ap-southeast-2.console.aws.amazon.com" in url
        assert "ec2/home" in url
        assert "i-abc123" in url

    def it_builds_a_regionless_service_home_when_no_region(self) -> None:
        url = build_aws_console_url(service="ec2", resource_id="i-x")
        assert url.startswith("https://console.aws.amazon.com/")
        assert "i-x" in url

    def it_routes_s3_buckets_to_the_path_template(self) -> None:
        url = build_aws_console_url(service="s3", resource_id="my-bucket")
        # S3 deep-links bake the bucket name into the path.
        assert "/s3/buckets/my-bucket" in url

    def it_falls_back_for_unknown_services(self) -> None:
        url = build_aws_console_url(service="opensearch")
        assert "opensearch/home" in url

    def it_omits_resource_fragment_when_id_missing(self) -> None:
        url = build_aws_console_url(service="ec2")
        # No resource — no Instance fragment in the URL.
        assert "instanceId" not in url

    def it_handles_lambda_function_names(self) -> None:
        url = build_aws_console_url(
            service="lambda",
            resource_id="my-func",
            region="us-east-1",
        )
        assert "us-east-1.console.aws.amazon.com" in url
        assert "my-func" in url


class DescribeBuildGitHubURL:
    def it_builds_a_repo_root_url(self) -> None:
        assert (
            build_github_url(repo="example/order-service")
            == "https://github.com/example/order-service"
        )

    def it_builds_a_file_url_with_default_branch(self) -> None:
        url = build_github_url(
            repo="example/order-service", file="src/main.py"
        )
        assert url == (
            "https://github.com/example/order-service/blob/main/src/main.py"
        )

    def it_builds_a_file_line_url(self) -> None:
        url = build_github_url(
            repo="example/order-service", file="src/main.py", line=42
        )
        assert url.endswith("/src/main.py#L42")

    def it_honours_an_explicit_branch(self) -> None:
        url = build_github_url(
            repo="example/order-service",
            file="src/main.py",
            branch="develop",
        )
        assert "/blob/develop/src/main.py" in url

    def it_strips_a_leading_slash_on_file(self) -> None:
        url = build_github_url(
            repo="example/order-service", file="/src/main.py"
        )
        assert "/blob/main/src/main.py" in url
        assert "/blob/main//src/main.py" not in url


class DescribeBuildConfluenceURL:
    def it_builds_a_display_url(self) -> None:
        url = build_confluence_url(
            base_url="https://acme.atlassian.net/wiki",
            space="ENG",
            page="Order Service",
        )
        assert url == (
            "https://acme.atlassian.net/wiki/display/ENG/Order%20Service"
        )

    def it_url_encodes_special_chars_in_page_title(self) -> None:
        url = build_confluence_url(
            base_url="https://acme.atlassian.net/wiki",
            space="ENG",
            page="A & B / C",
        )
        # Forward slash and ampersand both encoded so they don't
        # split the URL path.
        assert "/display/ENG/" in url
        assert "%26" in url  # & encoded
        assert "%2F" in url  # / encoded

    def it_tolerates_a_trailing_slash_on_base(self) -> None:
        url = build_confluence_url(
            base_url="https://acme.atlassian.net/wiki/",
            space="ENG",
            page="Home",
        )
        assert "//display" not in url


class DescribeBuildJiraURL:
    def it_builds_a_browse_url_from_an_int_issue(self) -> None:
        url = build_jira_url(
            base_url="https://acme.atlassian.net",
            project="ABC",
            issue=123,
        )
        assert url == "https://acme.atlassian.net/browse/ABC-123"

    def it_accepts_a_full_issue_key(self) -> None:
        url = build_jira_url(
            base_url="https://acme.atlassian.net",
            project="ABC",
            issue="ABC-456",
        )
        assert url.endswith("/browse/ABC-456")

    def it_accepts_a_bare_numeric_string(self) -> None:
        url = build_jira_url(
            base_url="https://acme.atlassian.net",
            project="ABC",
            issue="789",
        )
        assert url.endswith("/browse/ABC-789")

    def it_tolerates_a_trailing_slash_on_base(self) -> None:
        url = build_jira_url(
            base_url="https://acme.atlassian.net/",
            project="ABC",
            issue=1,
        )
        assert "//browse" not in url


# ---------------------------------------------------------------------------
# Describe Shape.link_to_* convenience helpers
# ---------------------------------------------------------------------------


class DescribeLinkToAWSConsole:
    def it_attaches_a_default_labelled_aws_console_link(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_aws_console(
            service="ec2",
            resource_id="i-abc",
            region="ap-southeast-2",
        )
        assert h.description == "AWS Console"
        assert "i-abc" in (h.address or "")
        assert "ap-southeast-2" in (h.address or "")

    def it_honours_an_explicit_label(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_aws_console(
            service="s3", resource_id="my-bucket", label="Bucket"
        )
        assert h.description == "Bucket"

    def it_can_be_marked_default(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_aws_console(service="ec2", default=True)
        assert h.default is True


class DescribeLinkToGitHub:
    def it_attaches_a_repo_root_link_labelled_github(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_github(repo="example/order-service")
        assert h.description == "GitHub"
        assert h.address == "https://github.com/example/order-service"

    def it_uses_source_label_when_a_file_is_provided(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_github(
            repo="example/order-service", file="src/main.py", line=42
        )
        assert h.description == "Source"
        assert h.address.endswith("/blob/main/src/main.py#L42")

    def it_honours_an_explicit_label(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_github(
            repo="example/order-service", label="Repository"
        )
        assert h.description == "Repository"


class DescribeLinkToConfluence:
    def it_attaches_a_confluence_page_link_labelled_with_page(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_confluence(
            space="ENG",
            page="Order Service",
            base_url="https://acme.atlassian.net/wiki",
        )
        assert h.description == "Order Service"
        assert "display/ENG/Order%20Service" in (h.address or "")

    def it_honours_an_explicit_label(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_confluence(
            space="ENG",
            page="Order Service",
            base_url="https://acme.atlassian.net/wiki",
            label="Runbook",
        )
        assert h.description == "Runbook"


class DescribeLinkToJira:
    def it_attaches_a_jira_issue_link_labelled_with_key(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_jira(
            project="ABC",
            issue=123,
            base_url="https://acme.atlassian.net",
        )
        assert h.description == "ABC-123"
        assert h.address == "https://acme.atlassian.net/browse/ABC-123"

    def it_honours_an_explicit_label(self) -> None:
        _, _, shape = _fresh_shape()
        h = shape.link_to_jira(
            project="ABC",
            issue=123,
            base_url="https://acme.atlassian.net",
            label="Tracker",
        )
        assert h.description == "Tracker"


# ---------------------------------------------------------------------------
# Describe round-trip — multi-link save/reload preserves every link
# ---------------------------------------------------------------------------


class DescribeMultiLinkRoundTrip:
    def it_preserves_multiple_hyperlinks_through_save_reload(self) -> None:
        # Build the issue's headline pattern: an EC2 shape with three
        # hyperlinks (AWS console, GitHub, Confluence). Save, reload,
        # and assert every hyperlink is intact.
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Architecture")
        ec2 = page.shapes.add_shape(
            vsdx.VS_SHAPE_TYPE.RECTANGLE,
            at=(2, 2),
            label="Order Service",
        )
        ec2.link_to_aws_console(
            service="ec2",
            resource_id="i-abc123",
            region="ap-southeast-2",
        )
        ec2.link_to_github(
            repo="example/order-service", file="src/main.py", line=42
        )
        ec2.link_to_confluence(
            space="ENG",
            page="Order Service",
            base_url="https://acme.atlassian.net/wiki",
        )
        ec2.link_to_jira(
            project="ABC",
            issue=123,
            base_url="https://acme.atlassian.net",
        )

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        rshape = list(reloaded.pages[0].shapes)[0]
        descriptions = [h.description for h in rshape.hyperlinks]
        assert descriptions == ["AWS Console", "Source", "Order Service", "ABC-123"]
        # Spot-check a few addresses survived round-trip.
        assert "i-abc123" in (rshape.hyperlinks[0].address or "")
        assert (
            rshape.hyperlinks["Source"].address
            == "https://github.com/example/order-service/blob/main/src/main.py#L42"
        )
        assert (
            rshape.hyperlinks["ABC-123"].address
            == "https://acme.atlassian.net/browse/ABC-123"
        )

    def it_preserves_default_flag_on_reload(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        shape = page.shapes.add_shape(
            vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1)
        )
        shape.link_to_aws_console(service="ec2", resource_id="i-1")
        shape.link_to_github(repo="x/y", default=True)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        rshape = list(reloaded.pages[0].shapes)[0]
        default = rshape.hyperlinks.default_hyperlink
        assert default is not None
        assert default.description == "GitHub"
