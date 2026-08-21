"""Stable public-safe error contracts for read tool execution."""

from enum import Enum


class ToolErrorCode(str, Enum):
    """Error codes safe to expose without authorization detail."""

    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    READ_ONLY_VIOLATION = "READ_ONLY_VIOLATION"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    INVALID_TOOL_OUTPUT = "INVALID_TOOL_OUTPUT"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"


SAFE_ERROR_MESSAGES: dict[ToolErrorCode, str] = {
    ToolErrorCode.TOOL_UNAVAILABLE: "The requested tool is unavailable.",
    ToolErrorCode.INVALID_TOOL_ARGUMENTS: "The tool arguments are invalid.",
    ToolErrorCode.READ_ONLY_VIOLATION: "Command tools are unavailable in read-only mode.",
    ToolErrorCode.TOOL_EXECUTION_FAILED: "The tool could not complete successfully.",
    ToolErrorCode.INVALID_TOOL_OUTPUT: "The tool returned an invalid result.",
    ToolErrorCode.AUDIT_UNAVAILABLE: "The tool result could not be safely recorded.",
}
