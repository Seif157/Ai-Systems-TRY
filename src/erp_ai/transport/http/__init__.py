"""Secure internal ERP-to-AI HTTP transport."""

from .app import create_internal_http_app
from .config import InternalHttpTransportConfig
from .errors import IngressAuthenticationDenied, IngressAuthenticationUnavailable
from .models import TrustedIngressAuthenticationRequest
from .parsing import canonical_public_chat_bytes, canonical_public_chat_digest
from .protocols import RequestIdFactory, TransportLifecycle, TrustedIngressAuthenticator

__all__ = [
    "IngressAuthenticationDenied",
    "IngressAuthenticationUnavailable",
    "InternalHttpTransportConfig",
    "RequestIdFactory",
    "TransportLifecycle",
    "TrustedIngressAuthenticationRequest",
    "TrustedIngressAuthenticator",
    "canonical_public_chat_bytes",
    "canonical_public_chat_digest",
    "create_internal_http_app",
]
