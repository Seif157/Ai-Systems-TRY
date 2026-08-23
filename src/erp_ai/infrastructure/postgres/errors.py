"""Generic PostgreSQL adapter failures that never carry driver or connection details."""


class KnowledgeStorageError(RuntimeError):
    pass


class KnowledgeStorageUnavailable(KnowledgeStorageError):
    pass


class KnowledgeDatabaseIdentityError(KnowledgeStorageError):
    pass


class KnowledgeMigrationError(KnowledgeStorageError):
    pass
