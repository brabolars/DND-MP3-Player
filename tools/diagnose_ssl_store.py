#!/usr/bin/env python3
# tools/diagnose_ssl_store.py
"""Diagnose `ssl.SSLError: [ASN1: NOT_ENOUGH_DATA]` on startup.

Two very different faults produce the same error:

  A) A few malformed certificates in the Windows store.  Python loads the store
     as one DER blob, so one bad entry breaks every TLS-using import.
     Fix: delete the offending certificates.

  B) A broken OpenSSL installation — usually a Python built against one OpenSSL
     version running against another (common in conda envs after an `openssl`
     upgrade, or when a stray libcrypto DLL is earlier on PATH).  Then *every*
     certificate appears bad, because the parser is at fault, not the data.
     Fix: rebuild the environment.  Deleting certificates would be a disaster.

This script distinguishes them.  It only reads; it changes nothing.

    python tools/diagnose_ssl_store.py
"""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

STORES = ("ROOT", "CA", "MY")


# ── helpers ──────────────────────────────────────────────────────────────────

def der_is_structurally_complete(der: bytes) -> bool:
    """Check the outer ASN.1 SEQUENCE length against the actual byte count.

    If these agree the certificate is not truncated, whatever OpenSSL claims.
    """
    if len(der) < 2 or der[0] != 0x30:
        return False
    length_byte = der[1]
    if length_byte < 0x80:
        return len(der) == 2 + length_byte
    count = length_byte & 0x7F
    if len(der) < 2 + count:
        return False
    declared = int.from_bytes(der[2 : 2 + count], "big")
    return len(der) == 2 + count + declared


def describe(der: bytes) -> str:
    try:
        from cryptography import x509

        cert = x509.load_der_x509_certificate(der)
        return f"subject={cert.subject.rfc4514_string()} serial={cert.serial_number:x}"
    except ImportError:
        return f"{len(der)} bytes (pip install cryptography for names)"
    except Exception as exc:
        return f"<unparseable by cryptography: {type(exc).__name__}> {len(der)} bytes"


def can_load(der_or_pem, *, cafile=None) -> tuple[bool, str]:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        if cafile:
            context.load_verify_locations(cafile=cafile)
        else:
            context.load_verify_locations(cadata=der_or_pem)
        return True, f"{len(context.get_ca_certs())} cert(s)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ── sections ─────────────────────────────────────────────────────────────────

def report_openssl() -> bool:
    """Return True if a build/runtime OpenSSL mismatch is detected."""
    print("── OpenSSL ─────────────────────────────────────────────")
    print(f"Python   : {sys.version.split()[0]}  ({sys.executable})")
    print(f"Runtime  : {ssl.OPENSSL_VERSION}")

    api = getattr(ssl, "_OPENSSL_API_VERSION", None)
    runtime = ssl.OPENSSL_VERSION_INFO
    mismatch = False
    if api:
        print(f"Compiled : {'.'.join(str(n) for n in api[:3])}  (build-time headers)")
        if api[:2] != runtime[:2]:
            print("  !! MISMATCH: this interpreter was built against a different")
            print("     OpenSSL major/minor than the one it has loaded.")
            mismatch = True
    if sys.version_info < (3, 10) and runtime[:2] >= (3, 0):
        print(f"  !! Python {sys.version_info.major}.{sys.version_info.minor} with OpenSSL "
              f"{runtime[0]}.{runtime[1]} is an unsupported pairing.")
        mismatch = True

    for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll", "libcrypto-1_1-x64.dll"):
        hits = []
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            try:
                candidate = Path(entry) / name
                if candidate.is_file():
                    hits.append(str(candidate))
            except OSError:
                continue
        if len(hits) > 1:
            print(f"  !! {name} found in {len(hits)} PATH locations — DLL shadowing:")
            for hit in hits[:5]:
                print(f"       {hit}")
            mismatch = True
    print()
    return mismatch


def test_known_good_certificate() -> bool | None:
    """Load a certificate that is definitely valid.  Returns True if OpenSSL works."""
    print("── Parser sanity check (known-good certificate) ─────────")
    try:
        import certifi
    except ImportError:
        print("certifi not installed — skipping.  `pip install certifi` to enable.")
        print()
        return None

    bundle = Path(certifi.where())
    ok_file, detail = can_load(None, cafile=str(bundle))
    print(f"certifi bundle as PEM file : {'OK' if ok_file else 'FAILED'} — {detail}")

    text = bundle.read_text()
    begin = text.index("-----BEGIN CERTIFICATE-----")          # skip the file's comment header
    end = text.index("-----END CERTIFICATE-----") + len("-----END CERTIFICATE-----")
    der = ssl.PEM_cert_to_DER_cert(text[begin:end] + "\n")
    ok_der, detail = can_load(der)
    print(f"same certificate as DER    : {'OK' if ok_der else 'FAILED'} — {detail}")

    print()
    if not ok_der:
        print("OpenSSL cannot parse a certificate that is known to be valid.")
        print("=> The problem is your OpenSSL/Python install, NOT your cert store.")
        print()
    return ok_der


def scan_stores() -> tuple[int, int, int]:
    if not hasattr(ssl, "enum_certificates"):
        print("Not on Windows — no certificate store to scan.")
        return 0, 0, 0

    print("── Windows certificate store ───────────────────────────")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        context.load_default_certs()
        print("load_default_certs() SUCCEEDED — the store is usable here.\n")
    except ssl.SSLError as exc:
        print(f"load_default_certs() FAILED: {exc}\n")

    total = rejected = truncated = 0
    for store in STORES:
        try:
            entries = list(ssl.enum_certificates(store))
        except Exception as exc:
            print(f"[{store}] cannot enumerate: {exc}")
            continue

        store_bad = store_truncated = 0
        details = []
        for der, encoding, _trust in entries:
            if encoding != "x509_asn":
                continue
            total += 1
            ok, err = can_load(der)
            if ok:
                continue
            store_bad += 1
            rejected += 1
            if der_is_structurally_complete(der):
                details.append(f"    rejected but STRUCTURALLY COMPLETE: {describe(der)}")
            else:
                store_truncated += 1
                truncated += 1
                details.append(f"    TRUNCATED (genuinely damaged): {describe(der)}")

        print(f"[{store}] {len(entries)} entries — {len(entries) - store_bad} ok, "
              f"{store_bad} rejected, of which {store_truncated} truncated")
        for line in details[:10]:
            print(line)
        if len(details) > 10:
            print(f"    ... and {len(details) - 10} more")
    print()
    return total, rejected, truncated


def verdict(mismatch: bool, parser_ok, total: int, rejected: int, truncated: int) -> None:
    print("── Verdict ─────────────────────────────────────────────")

    if parser_ok is False or (total and rejected == total and truncated == 0):
        print("Your OpenSSL install is broken — it rejects valid certificates.")
        print()
        print("DO NOT delete any certificates.  Nothing is wrong with them.")
        print()
        print("Rebuild the environment on a supported Python:")
        print("    conda create -n dnd-music python=3.12 -y")
        print("    conda activate dnd-music")
        print("    pip install -r requirements.txt")
        print()
        print("A clean python.org 3.12 + venv is even better if you plan to")
        print("build the .exe, since it matches what GitHub Actions uses.")
        if mismatch:
            print()
            print("(The OpenSSL section above shows the mismatch causing this.)")
        return

    if truncated:
        print(f"{truncated} genuinely damaged certificate(s) found; "
              f"{rejected - truncated} other rejection(s).")
        print("Remove the truncated ones via certlm.msc (Local Machine) or")
        print("certmgr.msc (Current User), matching the subject/serial above.")
        return

    if rejected:
        print(f"{rejected} of {total} certificates were rejected but look structurally")
        print("intact.  Treat this as an OpenSSL problem before touching the store.")
        return

    print("No certificate problems found — the failure lies elsewhere.")


def main() -> int:
    mismatch = report_openssl()
    parser_ok = test_known_good_certificate()
    total, rejected, truncated = scan_stores()
    verdict(mismatch, parser_ok, total, rejected, truncated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
