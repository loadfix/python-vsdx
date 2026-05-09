# Bundled master XML fragments

This directory holds per-master XML fragments harvested from the
``*-master.office.vsdx`` source fixtures in the reference corpus
(``~/code/ooxml-reference-corpus/fixtures/vsdx/``). Each master
contributes **two** files:

- ``<slug>.master.xml`` — the ``<Master>`` entry lifted from the
  source fixture's ``visio/masters/masters.xml`` (pretty-printed,
  single-element document with the Visio ``2012/main`` default
  namespace).
- ``<slug>.masterContents.xml`` — the full ``<MasterContents>`` part
  lifted from the source fixture's ``visio/masters/masterN.xml``
  (likewise pretty-printed).

The authoring code-path splices the two files together when
instantiating a built-in master, so it never has to open the source
``.vsdx`` at runtime.

## Bundled masters (0.1.0)

| NameU (API key)   | Slug                  | Source fixture                            |
| ----------------- | --------------------- | ----------------------------------------- |
| Rectangle         | ``rectangle``         | ``rectangle-master.office.vsdx``          |
| Ellipse           | ``ellipse``           | ``ellipse-master.office.vsdx``            |
| Triangle          | ``triangle``          | ``triangle-master.office.vsdx``           |
| Dynamic Connector | ``dynamic-connector`` | ``dynamic-connector-master.office.vsdx``  |

Note: the Visio fixture stores the Dynamic Connector master with
``NameU="Dynamic connector"`` (lowercase ``c``). The API key in
``vsdx.templates.master_fragment_path`` uses the title-cased form
(``"Dynamic Connector"``) to match the user-facing spelling; the
underlying fragment preserves the source ``NameU`` verbatim.

## Extraction recipe

```python
from lxml import etree
import zipfile

NS = "http://schemas.microsoft.com/office/visio/2012/main"

with zipfile.ZipFile(source_vsdx) as zf:
    masters_bytes = zf.read("visio/masters/masters.xml")
    contents_bytes = zf.read(f"visio/masters/{target_part}")

master_elem = next(
    m for m in etree.fromstring(masters_bytes).findall(f"{{{NS}}}Master")
    if m.get("NameU") == nameu
)

master_xml = etree.tostring(
    master_elem, pretty_print=True, xml_declaration=True,
    encoding="UTF-8", standalone=True,
)
contents_xml = etree.tostring(
    etree.fromstring(contents_bytes), pretty_print=True,
    xml_declaration=True, encoding="UTF-8", standalone=True,
)
```

## Pending

No additional masters are pending for 0.1.0 — Rectangle, Ellipse,
Triangle, and Dynamic Connector are the complete set of built-in
masters the authoring floor needs. Expansions (e.g. stencil imports,
extended basic shapes) are a 0.2.0+ concern and will land alongside
their source fixtures.
