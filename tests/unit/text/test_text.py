"""Behavioural tests for :class:`TextFrame` / :class:`Paragraph` / :class:`Run`."""

from __future__ import annotations

from vsdx import Visio
from vsdx.text import Paragraph, Run, TextFrame


def _shape():
    doc = Visio()
    page = doc.pages.add_page()
    return page.shapes.add_shape("Rectangle")


class DescribeTextFrame:
    def it_starts_empty(self):
        s = _shape()
        assert s.text_frame.text == ""

    def it_round_trips_a_simple_string(self):
        s = _shape()
        s.text_frame.text = "hello"
        assert s.text_frame.text == "hello"
        # and via the shape shortcut
        assert s.text == "hello"

    def it_exposes_a_single_paragraph_by_default(self):
        s = _shape()
        s.text = "paragraph body"
        paras = s.text_frame.paragraphs
        assert len(paras) == 1
        assert isinstance(paras[0], Paragraph)
        assert paras[0].text == "paragraph body"

    def it_clears_back_to_empty(self):
        s = _shape()
        s.text = "stuff"
        s.text_frame.clear()
        assert s.text == ""


class DescribeParagraph:
    def it_reads_and_writes_text(self):
        s = _shape()
        p = s.text_frame.paragraphs[0]
        p.text = "updated"
        assert s.text == "updated"

    def it_returns_one_run(self):
        s = _shape()
        s.text = "x"
        runs = s.text_frame.paragraphs[0].runs
        assert len(runs) == 1
        assert isinstance(runs[0], Run)


class DescribeRun:
    def it_reads_and_writes_text(self):
        s = _shape()
        s.text = "alpha"
        r = s.text_frame.paragraphs[0].runs[0]
        r.text = "beta"
        assert s.text == "beta"
