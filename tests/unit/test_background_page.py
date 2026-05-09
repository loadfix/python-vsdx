"""Unit tests for 0.2.0 background-page semantics.

``Page.is_background``, ``Page.background_page``, ``Pages.add_background_page``,
and the ``Pages.foreground`` / ``Pages.backgrounds`` filter views.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import pytest

import vsdx


class DescribePageBackgroundAttribute:
    def it_defaults_to_not_background(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        assert page.is_background is False

    def it_marks_a_page_as_background(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="BG-1")
        page.is_background = True
        assert page.is_background is True
        # The underlying attribute should be "1", matching Visio desktop.
        assert page._element.get("Background") == "1"

    def it_clears_the_background_flag(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="BG-1")
        page.is_background = True
        page.is_background = False
        assert page.is_background is False
        assert page._element.get("Background") is None


class DescribeAddBackgroundPage:
    def it_creates_a_background_page(self) -> None:
        doc = vsdx.Visio()
        bg = doc.pages.add_background_page()
        assert bg.is_background is True

    def it_auto_names_with_vbackground_prefix(self) -> None:
        doc = vsdx.Visio()
        bg = doc.pages.add_background_page()
        assert bg._element.get("NameU", "").startswith("VBackground-")

    def it_accepts_an_explicit_name(self) -> None:
        doc = vsdx.Visio()
        bg = doc.pages.add_background_page(name="Letterhead")
        assert bg._element.get("NameU") == "Letterhead"

    def it_makes_the_page_iterable_alongside_foreground(self) -> None:
        doc = vsdx.Visio()
        fg = doc.pages.add_page(name="Page-1")
        bg = doc.pages.add_background_page(name="BG")
        assert list(doc.pages) == [fg, bg]


class DescribePagesFilterViews:
    def it_partitions_pages_into_foreground_and_backgrounds(self) -> None:
        doc = vsdx.Visio()
        fg1 = doc.pages.add_page(name="Page-1")
        fg2 = doc.pages.add_page(name="Page-2")
        bg = doc.pages.add_background_page(name="BG-A")
        assert doc.pages.foreground == [fg1, fg2]
        assert doc.pages.backgrounds == [bg]


class DescribeBackPageResolution:
    def it_returns_none_when_no_background_is_set(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        assert page.background_page is None

    def it_resolves_the_backpage_reference(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        bg = doc.pages.add_background_page(name="BG-1")
        page.background_page = bg
        assert page.background_page is bg

    def it_writes_the_target_nameu_not_a_rel_id(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        bg = doc.pages.add_background_page(name="BG-Named")
        page.background_page = bg
        # The @BackPage value is the target's NameU — not a rel-id.
        assert page._element.get("BackPage") == "BG-Named"

    def it_clears_backpage_when_assigned_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        bg = doc.pages.add_background_page(name="BG-1")
        page.background_page = bg
        page.background_page = None
        assert page._element.get("BackPage") is None


class DescribeBackgroundReferenceInvariants:
    def it_refuses_to_make_a_page_its_own_background(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        page.is_background = True
        with pytest.raises(ValueError):
            page.background_page = page

    def it_refuses_to_assign_a_foreground_page_as_background(self) -> None:
        doc = vsdx.Visio()
        fg1 = doc.pages.add_page(name="Page-1")
        fg2 = doc.pages.add_page(name="Page-2")
        # Not a background page → setter must refuse.
        with pytest.raises(ValueError):
            fg1.background_page = fg2

    def it_returns_none_if_backpage_target_is_missing(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        # Set @BackPage directly to a NameU that doesn't exist.
        page._element.set("BackPage", "NoSuchPage")
        assert page.background_page is None


class DescribeDanglingBackPageCleanup:
    def it_clears_dangling_backpage_on_background_removal(self) -> None:
        doc = vsdx.Visio()
        fg = doc.pages.add_page(name="Page-1")
        bg = doc.pages.add_background_page(name="BG-1")
        fg.background_page = bg
        assert fg._element.get("BackPage") == "BG-1"
        doc.pages.remove(bg)
        # Dangling reference should be cleared automatically.
        assert fg._element.get("BackPage") is None
