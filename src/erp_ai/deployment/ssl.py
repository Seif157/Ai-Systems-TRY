"""Strict deployment-owned TLS context construction."""

import ssl
from pathlib import Path


def create_verified_ssl_context(ca_file: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(ca_file))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def load_client_identity(
    context: ssl.SSLContext, certificate_file: Path, private_key_file: Path
) -> None:
    if not isinstance(context, ssl.SSLContext):
        raise TypeError("TLS context is required")
    try:
        context.load_cert_chain(str(certificate_file), str(private_key_file))
    except Exception:
        raise ValueError("TLS identity is unavailable") from None
