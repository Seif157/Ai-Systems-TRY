"""Safe production runtime composition failures."""


class RuntimeCompositionError(RuntimeError):
    """A local dependency graph is invalid."""


class RuntimeLifecycleError(RuntimeError):
    """A runtime resource could not be safely opened or closed."""
