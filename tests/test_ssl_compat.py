# tests/test_ssl_compat.py
"""The Windows certificate-store workaround.

The bad certificate is simulated by truncating a real one, so these run on any
platform — including the Windows machines the workaround actually exists for.
"""

import pathlib
import ssl
import sys

import pytest

from dndmusic import _ssl_compat

#: Fallbacks if certifi isn't installed (it comes in via requests).
UNIX_CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem")


def _certificate_bundle() -> pathlib.Path:
    try:
        import certifi

        return pathlib.Path(certifi.where())
    except ImportError:
        for candidate in UNIX_CA_BUNDLES:
            path = pathlib.Path(candidate)
            if path.exists():
                return path
    pytest.skip("no CA bundle available — pip install certifi")


def _real_der() -> bytes:
    """One genuine, complete DER certificate to build fixtures from."""
    text = _certificate_bundle().read_text(encoding="utf-8")
    begin = text.index("-----BEGIN CERTIFICATE-----")
    end = text.index("-----END CERTIFICATE-----") + len("-----END CERTIFICATE-----")
    return ssl.PEM_cert_to_DER_cert(text[begin:end] + "\n")


def test_one_bad_cert_poisons_the_whole_blob():
    """The stdlib behaviour this module exists to work around."""
    good = _real_der()
    blob = bytes(bytearray(good) + bytearray(good[: len(good) // 2]))
    with pytest.raises(ssl.SSLError):
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=blob)


def test_loader_keeps_good_and_skips_malformed(monkeypatch):
    good = _real_der()
    truncated = good[: len(good) // 2]
    monkeypatch.setattr(
        ssl,
        "enum_certificates",
        lambda _store: [
            (good, "x509_asn", True),
            (truncated, "x509_asn", True),
            (b"junk", "pkcs_7_asn", True),
        ],
        raising=False,
    )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    collected = _ssl_compat._load_store_one_by_one(context, "ROOT", ssl.Purpose.SERVER_AUTH)

    assert bytes(collected) == good
    assert len(context.get_ca_certs()) == 1


def test_trust_filter_excludes_untrusted_purposes(monkeypatch):
    monkeypatch.setattr(
        ssl, "enum_certificates", lambda _store: [(_real_der(), "x509_asn", set())], raising=False
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert not _ssl_compat._load_store_one_by_one(context, "ROOT", ssl.Purpose.SERVER_AUTH)


def test_enumeration_failure_is_swallowed(monkeypatch):
    """A locked-down store must not take the app down with it."""
    def boom(_store):
        raise PermissionError("access denied")

    monkeypatch.setattr(ssl, "enum_certificates", boom, raising=False)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert not _ssl_compat._load_store_one_by_one(context, "ROOT", ssl.Purpose.SERVER_AUTH)


def test_install_returns_a_bool_and_never_raises():
    result = _ssl_compat.install()
    assert isinstance(result, bool)
    if sys.platform != "win32":
        assert result is False, "the workaround must be inert off Windows"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only code path")
def test_healthy_windows_store_is_left_alone():
    """On Windows, patching happens only when the stock path actually fails.

    If this fails, `python tools/diagnose_ssl_store.py` will say why.
    """
    if _ssl_compat._installed:
        pytest.skip("already patched earlier in this session")

    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_default_certs()
    except ssl.SSLError:
        assert _ssl_compat.install() is True  # damaged store -> patch applied
    else:
        assert _ssl_compat.install() is False  # healthy store -> untouched
