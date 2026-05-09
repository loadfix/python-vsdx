"""VBA project part — opaque passthrough for macro-enabled Visio variants.

The ``/visio/vbaProject.bin`` binary is a compressed VBA project
stream produced by the VBA IDE. ``.vsdm`` / ``.vssm`` / ``.vstm`` all
carry it; ``.vsdx`` / ``.vssx`` / ``.vstx`` never do.

python-vsdx's 0.2.0 stance is **opaque passthrough** (scoping doc
§6.2). We never parse the VBA stream, never execute it, never modify
it. The bytes are read on open and written verbatim on save.

Security (see ``SECURITY.md`` and scoping doc §9.4):

- Hard size cap at 16 MiB — larger files raise :class:`VsdxError`.
  Matches the docx/pptx caps.
- Converting ``.vsdm`` → ``.vsdx`` (the save-as-non-macro path) strips
  the part and updates ``[Content_Types].xml``. That behaviour lives
  on :class:`~vsdx.package.VisioPackage`, not here.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc import Part
from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VBA_PROJECT

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


__all__ = ["VBA_PROJECT_SIZE_CAP", "VbaProjectPart"]


#: Upper bound (in bytes) on the VBA-project binary accepted on open.
#: Chosen to match docx/pptx's analogous cap. Real-world Visio
#: vbaProject.bin payloads are typically < 100 KiB — anything
#: approaching the cap is almost certainly hostile.
VBA_PROJECT_SIZE_CAP = 16 * 1024 * 1024  # 16 MiB


class VbaProjectPart(Part):
    """The ``/visio/vbaProject.bin`` binary part.

    Content-type ``application/vnd.ms-office.vbaProject``. The part
    stores its bytes in the base class's ``_blob`` slot and re-emits
    them verbatim on save; no lxml parsing takes place.

    .. versionadded:: 0.2.0
    """

    def __init__(
        self,
        partname: PackURI,
        content_type: str,
        package: OpcPackage,
        blob: "bytes | None" = None,
    ) -> None:
        if blob is not None and len(blob) > VBA_PROJECT_SIZE_CAP:
            raise ValueError(
                "VBA project exceeds %d-byte size cap (got %d)"
                % (VBA_PROJECT_SIZE_CAP, len(blob))
            )
        super().__init__(partname, content_type, package, blob)

    @classmethod
    def new_empty(cls, package: OpcPackage) -> VbaProjectPart:
        """Mint a zero-byte VBA-project placeholder.

        Useful for tests — a real VBA project is produced by the VBA
        IDE, not by python-vsdx. Authoring a macro-enabled file
        typically goes through round-trip of an existing ``.vsdm``,
        not from-scratch creation.

        .. versionadded:: 0.2.0
        """
        return cls(
            PackURI("/visio/vbaProject.bin"),
            CT_VBA_PROJECT,
            package,
            b"",
        )
