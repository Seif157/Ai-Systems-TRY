"""Safe immutable runtime handles and state."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from fastapi import FastAPI


class RuntimeState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    CLOSED = "closed"
    FAILED = "failed"


class _LifecycleState(Protocol):
    @property
    def state(self) -> RuntimeState: ...


@dataclass(frozen=True, slots=True)
class ComposedRuntime:
    """Minimum operational result; sensitive dependencies stay private."""

    application: FastAPI = field(repr=False)
    _lifecycle: _LifecycleState = field(repr=False)

    @property
    def state(self) -> RuntimeState:
        return self._lifecycle.state

    def __repr__(self) -> str:
        return f"ComposedRuntime(state={self.state.value!r})"
