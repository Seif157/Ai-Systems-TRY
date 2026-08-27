"""Production ERP trust-boundary adapters."""

from .config import (
    ErpAssertionVerificationKey,
    ErpAssertionVerifierConfig,
    ErpTrustHttpConfig,
)
from .errors import (
    ErpTrustResolutionDenied,
    ErpTrustUnavailable,
    SnapshotVerificationUnavailable,
)
from .http_client import ErpTrustHttpClient
from .resolver import ErpTrustedRequestResolver
from .snapshot import ErpAuthorizationSnapshotVerifier
from .verifier import ErpSignedAssertionAuthenticator

__all__ = [
    "ErpAssertionVerificationKey",
    "ErpAssertionVerifierConfig",
    "ErpAuthorizationSnapshotVerifier",
    "ErpSignedAssertionAuthenticator",
    "ErpTrustHttpClient",
    "ErpTrustHttpConfig",
    "ErpTrustResolutionDenied",
    "ErpTrustUnavailable",
    "ErpTrustedRequestResolver",
    "SnapshotVerificationUnavailable",
]
