"""Fixed internal HTTP transport failures without sensitive details."""


class IngressAuthenticationDenied(Exception):
    """The opaque ERP assertion was not accepted."""


class IngressAuthenticationUnavailable(Exception):
    """The mandatory authentication dependency is unavailable."""
