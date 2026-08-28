"""Safe Laravel ERP provider errors."""


class LaravelErpReadUnavailable(RuntimeError):
    """Stable internal boundary for every unavailable or invalid ERP read."""

    def __init__(self) -> None:
        super().__init__("Laravel ERP read provider unavailable")
