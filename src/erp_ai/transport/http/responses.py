"""Stable non-reflective HTTP response construction."""

from enum import StrEnum

from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from erp_ai.orchestration import AgentErrorCode, PublicChatFailure, PublicChatSuccess
from erp_ai.orchestration.models import PublicChatResult


class TransportErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"


class TransportFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    safe_error_code: TransportErrorCode
    safe_message: str


_MESSAGES = {
    TransportErrorCode.INVALID_REQUEST: "The request is invalid.",
    TransportErrorCode.AUTHENTICATION_REQUIRED: "ERP authentication is required.",
    TransportErrorCode.REQUEST_TOO_LARGE: "The request is too large.",
    TransportErrorCode.UNSUPPORTED_MEDIA_TYPE: "The request media type is unsupported.",
    TransportErrorCode.SERVICE_UNAVAILABLE: "The service is temporarily unavailable.",
    TransportErrorCode.AUDIT_UNAVAILABLE: "The response could not be safely recorded.",
    TransportErrorCode.INTERNAL_ERROR: "The request could not be completed.",
    TransportErrorCode.NOT_FOUND: "The requested resource was not found.",
    TransportErrorCode.METHOD_NOT_ALLOWED: "The request method is not allowed.",
}


def security_headers(request_id: str) -> dict[str, str]:
    return {
        "X-Request-ID": request_id,
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def failure_response(code: TransportErrorCode, status_code: int, request_id: str) -> JSONResponse:
    headers = security_headers(request_id)
    if status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    body = TransportFailure(safe_error_code=code, safe_message=_MESSAGES[code])
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


def application_response(result: PublicChatResult, request_id: str) -> JSONResponse:
    validated: BaseModel
    if type(result) is PublicChatSuccess:
        validated = PublicChatSuccess.model_validate(result.model_dump(mode="python"), strict=True)
        status = 200
    elif type(result) is PublicChatFailure:
        failure = PublicChatFailure.model_validate(result.model_dump(mode="python"), strict=True)
        validated = failure
        status = {
            AgentErrorCode.AGENT_UNAVAILABLE: 503,
            AgentErrorCode.AUDIT_UNAVAILABLE: 503,
            AgentErrorCode.AGENT_LIMIT_REACHED: 503,
            AgentErrorCode.AGENT_CATALOG_LIMIT: 503,
            AgentErrorCode.INVALID_MODEL_RESPONSE: 500,
        }.get(failure.safe_error_code, 500)
    else:
        raise ValueError("invalid public application result")
    return JSONResponse(
        validated.model_dump(mode="json"), status_code=status, headers=security_headers(request_id)
    )


def empty_response(status_code: int) -> Response:
    return Response(status_code=status_code)
