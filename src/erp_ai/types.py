"""Neutral reusable value types shared across ERP AI contracts."""

import re
from typing import Annotated

from pydantic import StringConstraints

SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


CanonicalSemVer = Annotated[
    str,
    StringConstraints(strict=True, pattern=SEMVER_PATTERN),
]
