"""Generic PostgreSQL audit-storage failures."""


class AuditStorageUnavailable(RuntimeError):
    """The durable audit boundary could not complete safely."""


class AuditStorageConflict(AuditStorageUnavailable):
    """A logical audit slot was reused with different content."""


class AuditMigrationError(RuntimeError):
    """Administrative audit migration or verification failed."""
