# Bundled master XML fragments

This directory holds per-master XML fragments harvested from the
``*-master.office.vsdx`` fixtures listed in
``/tmp/vsdx-fixture-requests.md``. Each file here is a ``<Master>`` +
``<MasterContents>`` pair extracted verbatim from a real Visio-authored
``.vsdx`` file, so the authoring path can splice in a built-in master
(Rectangle, Ellipse, Triangle, Dynamic Connector) without opening the
source ``.vsdx`` at runtime.

Expected filenames:

- ``rectangle.xml``
- ``ellipse.xml``
- ``triangle.xml``
- ``dynamic-connector.xml``

Files are produced (by the build/maintenance pipeline) from the
corresponding ``*-master.office.vsdx`` fixtures once those fixtures are
available in the reference corpus. Until then the runtime loader in
``vsdx.templates`` raises ``TemplateNotAvailable`` pointing at the
fixture request file.
