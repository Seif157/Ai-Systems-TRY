"""Minimal process-lifecycle JSON logging without exception or request data."""

import json
import sys
from typing import Literal


def emit_lifecycle_event(
    event: str,
    component: str,
    outcome: Literal["started", "ready", "stopping", "stopped", "failed"],
    severity: Literal["info", "error"],
    deployment_version: str,
) -> None:
    value = {
        "event": event,
        "component": component,
        "outcome": outcome,
        "severity": severity,
        "deployment_version": deployment_version,
    }
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=True), file=sys.stderr)
