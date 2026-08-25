"""Generic structured ERP read failures without connection or row details."""


class ErpReadError(RuntimeError):
    pass


class ErpReadUnavailable(ErpReadError):
    pass


class ErpReadContractError(ErpReadError):
    pass


class InvalidErpCursor(ErpReadError):
    pass
