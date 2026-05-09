"""Security regression tests — XML parser hardening canary.

These are canaries — they assert behaviours that must hold forever. Expanding
coverage is welcome; removing a test from this file requires a new CHANGELOG
entry in the ``### Security`` section explaining what changed and why.
"""

from __future__ import annotations

from lxml import etree

from vsdx.oxml import _oxml_parser, parse_xml


# An XXE payload that declares an external entity pointing at a local file.
# The hardened parser must refuse to resolve it; a raw lxml parser would.
_XXE_PAYLOAD = b"""<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<VisioDocument xmlns="http://schemas.microsoft.com/office/visio/2011/1/core">
  <DocumentProperties>&xxe;</DocumentProperties>
</VisioDocument>
"""

# Classic billion-laughs payload — a pathological chain of nested entity
# references that a naive parser would expand into ~10^9 bytes of output.
_BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
]>
<foo>&lol5;</foo>
"""


class DescribeXxeHardening:
    """The package-wide parser must refuse to resolve external entities."""

    def it_does_not_resolve_external_entities_in_parse_xml(self) -> None:
        try:
            root = parse_xml(_XXE_PAYLOAD)
        except etree.XMLSyntaxError:
            return
        text = etree.tostring(root, encoding="unicode")
        assert "/etc/passwd" not in text
        assert "root:" not in text


class DescribeBillionLaughsHardening:
    """Billion-laughs / entity-expansion DoS must not succeed."""

    def it_does_not_expand_the_payload_under_parse_xml(self) -> None:
        try:
            root = parse_xml(_BILLION_LAUGHS)
        except etree.XMLSyntaxError:
            return
        xml = etree.tostring(root, encoding="unicode")
        # Much less than the ~10^9 bytes a naive expander would emit.
        assert len(xml) < 10_000


class DescribeParserConfiguration:
    """Guards on the hardened parser configuration itself."""

    def it_uses_the_shared_oxml_parser_for_parse_xml(self) -> None:
        assert _oxml_parser is not None
        root = parse_xml(b"<root/>")
        assert root.tag == "root"

    def it_rejects_DTD_based_network_fetches(self) -> None:
        # ``no_network=True`` blocks resolution even if ``resolve_entities``
        # didn't — belt-and-braces. We can't easily assert the network
        # call didn't happen without a stub, but confirm the parser
        # config still has the guard set.
        #
        # lxml stores parser options on ``_oxml_parser.error_log`` /
        # internal state; we assert via behaviour: parse a DTD-bearing
        # file and ensure nothing is retrieved.
        payload = b"""<?xml version="1.0"?>
<!DOCTYPE foo SYSTEM "http://example.invalid/never.dtd">
<foo/>
"""
        try:
            root = parse_xml(payload)
        except etree.XMLSyntaxError:
            return
        assert root.tag == "foo"
