# src/dndmusic/_ssl_compat.py
"""Workaround for a malformed certificate in the Windows certificate store.

Python's ``load_default_certs()`` on Windows collects every certificate in the
store into a single DER blob and hands it to OpenSSL in one call.  If any one
entry is malformed, OpenSSL rejects the whole batch and raises
``ssl.SSLError: [ASN1: NOT_ENOUGH_DATA]``.  Because aiohttp builds a default SSL
context at *import* time, this kills ``import disnake`` outright.

This patch loads the certificates one at a time, skipping only the broken ones,
so a single bad entry stops being fatal.  Corporate and self-signed roots in the
store keep working — that is why this is preferred over dropping straight to the
certifi bundle, which is used only if the store yields nothing at all.

Disable with ``DND_SKIP_SSL_WORKAROUND=1`` if you need the stock behaviour.
"""

from __future__ import annotations

import os
import ssl
import sys
from typing import List, Tuple

_installed = False

#: Populated by the patched loader so startup can report what happened.
report: List[str] = []


def _load_store_one_by_one(context: ssl.SSLContext, storename: str, purpose) -> bytearray:
    """Replacement for ``SSLContext._load_windows_store_certs``."""
    collected = bytearray()
    try:
        entries: List[Tuple[bytes, str, object]] = list(ssl.enum_certificates(storename))
    except PermissionError:
        return collected
    except Exception as exc:
        report.append(f"{storename}: could not enumerate ({exc})")
        return collected

    loaded = skipped = 0
    for der, encoding, trust in entries:
        if encoding != "x509_asn":
            continue
        # Same trust filter the stdlib applies.
        if trust is not True and getattr(purpose, "oid", None) not in (trust or ()):
            continue
        try:
            context.load_verify_locations(cadata=der)
            collected.extend(der)
            loaded += 1
        except ssl.SSLError:
            skipped += 1

    if skipped:
        report.append(f"{storename}: loaded {loaded} certs, skipped {skipped} malformed")
    return collected


def _fallback_to_certifi(context: ssl.SSLContext) -> bool:
    try:
        import certifi
    except ImportError:
        return False
    try:
        context.load_verify_locations(cafile=certifi.where())
    except Exception:
        return False
    report.append("fell back to the certifi CA bundle")
    return True


def install() -> bool:
    """Patch ``ssl`` if needed.  Must run before aiohttp/disnake is imported."""
    global _installed
    if _installed:
        return True
    if sys.platform != "win32":
        return False
    if os.getenv("DND_SKIP_SSL_WORKAROUND"):
        return False
    if not hasattr(ssl.SSLContext, "_load_windows_store_certs"):
        # Newer CPython no longer uses this private hook.
        return False

    # Only patch if the stock path is actually broken, so a healthy machine
    # keeps the fast single-call behaviour.
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        probe.load_default_certs()
        return False
    except ssl.SSLError as exc:
        report.append(f"Windows cert store is damaged: {exc}")

    def patched(self, storename, purpose):  # noqa: ANN001 - matches stdlib signature
        certs = _load_store_one_by_one(self, storename, purpose)
        if not certs and storename == "ROOT":
            _fallback_to_certifi(self)
        return certs

    ssl.SSLContext._load_windows_store_certs = patched
    _installed = True
    return True
