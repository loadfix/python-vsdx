"""Integration tests for password-protected .vsdx read/write.

Exercises the real :mod:`ooxml_crypto` integration end-to-end. Covers the
BytesIO round-trip, file-path round-trip, wrong-password rejection,
missing-password rejection, and the invariant that the supplied password
is never echoed in exception messages.

Tests skip when the optional ``python-ooxml-crypto`` dependency is not
installed — mirrors the pattern used by the ``python-pptx`` equivalent
suite (:mod:`tests.test_password` in python-pptx).
"""

from __future__ import annotations

import importlib.util
import io
import os

import pytest

import vsdx
from vsdx.document import EncryptedPackageError, VisioDocument

# -- skip when python-ooxml-crypto is absent (optional dep per FEATURES.md) --
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ooxml_crypto") is None,
    reason="python-ooxml-crypto is not installed (optional test dependency)",
)


class DescribePasswordRoundTrip:
    """Save-with-password + open-with-password returns the same content."""

    def it_round_trips_a_password_protected_vsdx_through_a_stream(self) -> None:
        doc = vsdx.Visio()
        doc.pages.add_page()

        encrypted = io.BytesIO()
        doc.save(encrypted, password="s3cret-pw")

        # -- encrypted bytes begin with the OLE2 CFB magic --
        assert encrypted.getvalue()[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

        encrypted.seek(0)
        doc2 = VisioDocument.open(encrypted, password="s3cret-pw")
        # -- the reopened document has the same page count --
        assert len(doc2.pages) == len(doc.pages)

    def it_round_trips_through_a_file_path(self, tmp_path: object) -> None:
        doc = vsdx.Visio()
        doc.pages.add_page()
        doc.pages.add_page()
        out_path = os.path.join(str(tmp_path), "encrypted.vsdx")

        doc.save(out_path, password="longenoughpw")
        doc2 = VisioDocument.open(out_path, password="longenoughpw")

        assert os.path.getsize(out_path) > 0
        # -- raw bytes are an encrypted CFB container, not a zip --
        with open(out_path, "rb") as fh:
            head = fh.read(8)
        assert head == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        assert len(doc2.pages) == len(doc.pages)

    def it_passes_a_unicode_password_through_unchanged(self) -> None:
        """Non-ASCII password survives save + open.

        ``ooxml_crypto`` is responsible for the UTF-16-LE encoding per
        MS-OFFCRYPTO; the vsdx wrapper must not mutate or normalise the
        string before handing it over.
        """
        doc = vsdx.Visio()
        doc.pages.add_page()

        password = "pässwörd-テスト-éü"
        buf = io.BytesIO()
        doc.save(buf, password=password)

        buf.seek(0)
        doc2 = VisioDocument.open(buf, password=password)
        assert len(doc2.pages) == len(doc.pages)


class DescribeOpenPasswordProtectedVsdx:
    """Error paths when opening an encrypted vsdx."""

    def it_raises_when_no_password_is_supplied(
        self, encrypted_vsdx_stream: io.BytesIO
    ) -> None:
        with pytest.raises(EncryptedPackageError, match="password-protected"):
            VisioDocument.open(encrypted_vsdx_stream)

    def it_raises_on_a_wrong_password(
        self, encrypted_vsdx_stream: io.BytesIO
    ) -> None:
        with pytest.raises(EncryptedPackageError, match="does not match"):
            VisioDocument.open(encrypted_vsdx_stream, password="WRONG-PW")

    def it_never_echoes_the_supplied_password_in_an_exception(
        self, encrypted_vsdx_stream: io.BytesIO
    ) -> None:
        """Security invariant — neither the stored nor the supplied
        password may appear in the error message, even on a mismatch."""
        wrong = "my-secret-guess-99"
        try:
            VisioDocument.open(encrypted_vsdx_stream, password=wrong)
        except EncryptedPackageError as exc:
            message = str(exc)
            assert wrong not in message
            # -- the stored password fixture below --
            assert "correct-pw" not in message
        else:
            pytest.fail("expected EncryptedPackageError")

    def it_never_echoes_the_password_when_encrypt_fails(self) -> None:
        """Weak passwords surface via the ooxml_crypto hierarchy — the
        vsdx wrapper must re-raise without including the password."""
        doc = vsdx.Visio()
        doc.pages.add_page()

        short = "abc"  # below the 8-char floor
        buf = io.BytesIO()
        try:
            doc.save(buf, password=short)
        except EncryptedPackageError as exc:
            assert short not in str(exc)
        else:
            pytest.fail("expected EncryptedPackageError for weak password")

    # -- fixtures -------------------------------------------------------

    @pytest.fixture
    def encrypted_vsdx_stream(self) -> io.BytesIO:
        doc = vsdx.Visio()
        doc.pages.add_page()
        buf = io.BytesIO()
        doc.save(buf, password="correct-pw")
        buf.seek(0)
        return buf
