"""Safe ERP trust-boundary exceptions."""


class ErpTrustResolutionDenied(Exception):
    """The opaque reference was not accepted by ERP."""


class ErpTrustUnavailable(Exception):
    """The mandatory ERP trust service is unavailable."""


class SnapshotVerificationUnavailable(Exception):
    """The mandatory snapshot verifier is unavailable."""
