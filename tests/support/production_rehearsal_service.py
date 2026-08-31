"""Synthetic-only TLS services for the installed production-container rehearsal."""

import asyncio
import json
import os
import signal
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

STATE = Path(os.environ["SYNTHETIC_STATE_PATH"])
ROUTES = json.loads(Path(os.environ["SYNTHETIC_ROUTES_PATH"]).read_text(encoding="utf-8"))
LARAVEL_DIGEST = os.environ["SYNTHETIC_LARAVEL_DIGEST"]
CITATION_ID = os.environ["SYNTHETIC_CITATION_ID"]
_state_lock = asyncio.Lock()


async def _record(event: str) -> None:
    async with _state_lock:
        with STATE.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"event": event}, separators=(",", ":")) + "\n")


async def _request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, object]]:
    header = await reader.readuntil(b"\r\n\r\n")
    lines = header.decode("ascii").split("\r\n")
    method, path, _ = lines[0].split(" ")
    length = next(
        (
            int(line.split(":", 1)[1])
            for line in lines[1:]
            if line.lower().startswith("content-length:")
        ),
        0,
    )
    raw = await reader.readexactly(length) if length else b"{}"
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError
    return method, path, value


async def _respond(writer: asyncio.StreamWriter, value: object, status: int = 200) -> None:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    writer.write(
        f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
        + body
    )
    await writer.drain()


async def _erp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        _, path, body = await _request(reader)
        request_id = str(body["request_id"])
        if path.endswith("/resolve"):
            route = ROUTES[str(body["resolver_reference"])]
            now = datetime.now(UTC)
            purpose = "general" if route == "general" else "employee_self_service"
            value = {
                "contract_version": 1,
                "request_id": request_id,
                "trusted_request_context": {
                    "context_version": 1,
                    "request_id": request_id,
                    "customer_environment_id": "synthetic-customer",
                    "user_id": "synthetic-user",
                    "employee_id": "20000000-0000-4000-8000-000000000001",
                    "roles": ["manager"],
                    "permission_codes": ["hr.profile.read_self", "hr.knowledge.read"],
                    "legal_entity_ids": ["30000000-0000-4000-8000-000000000001"],
                    "enabled_modules": ["hr_core"],
                    "locale": "en",
                    "timezone": "UTC",
                    "purpose": purpose,
                    "issued_at": (now - timedelta(seconds=1)).isoformat(),
                    "authorization_snapshot_id": f"snapshot-{route}",
                },
                "trusted_route_intent": {
                    "intent_contract_version": 1,
                    "intent_code": route,
                    "issued_at": (now - timedelta(seconds=1)).isoformat(),
                    "expires_at": (now + timedelta(seconds=30)).isoformat(),
                    "request_id": request_id,
                    "customer_environment_id": "synthetic-customer",
                    "user_id": "synthetic-user",
                    "authorization_snapshot_id": f"snapshot-{route}",
                },
            }
            await _record(f"erp.resolve.{route}")
        else:
            value = {**body, "status": "current"}
            await _record("erp.snapshot")
        await _respond(writer, value)
    finally:
        writer.close()
        await writer.wait_closed()


async def _laravel(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        method, _, body = await _request(reader)
        if method == "GET":
            value: object = {
                "service_identity": "laravel_erp_read_api",
                "contract_version": "1.0.0",
                "contract_digest": LARAVEL_DIGEST,
                "read_only": True,
            }
            await _record("laravel.contract")
        else:
            binding = body
            value = {
                **binding,
                "outcome": "found",
                "profile": {
                    "employee_id": binding["employee_id"],
                    "legal_entity_id": binding["legal_entity_ids"][0],
                    "employee_number": "SYN-1",
                    "display_name": "Synthetic Person",
                    "work_email": "synthetic@example.invalid",
                    "job_title": None,
                    "department_name": None,
                    "branch_name": None,
                    "legal_entity_name": None,
                    "employment_status": "active",
                    "hire_date": "2025-01-01",
                    "manager_display_name": None,
                    "freshness_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                },
            }
            await _record("laravel.profile")
        await _respond(writer, value)
    finally:
        writer.close()
        await writer.wait_closed()


def _final(answer_basis: str, call_id: str | None = None) -> dict[str, object]:
    citations = [CITATION_ID] if answer_basis == "knowledge" else []
    evidence = [call_id] if call_id else []
    text = json.dumps(
        {
            "response_type": "final_answer",
            "answer": "Synthetic verified answer.",
            "answer_basis": answer_basis,
            "evidence_call_ids": evidence,
            "citation_ids": citations,
        },
        separators=(",", ":"),
    )
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


async def _openai(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        _, path, body = await _request(reader)
        model = str(body["model"])
        if path == "/v1/embeddings":
            dimensions = int(body["dimensions"])
            vector = [1.0] + [0.0] * (dimensions - 1)
            value = {
                "model": model,
                "data": [{"object": "embedding", "index": 0, "embedding": vector}],
            }
            await _record("openai.embedding")
        else:
            tool_choice = body.get("tool_choice")
            inputs = body.get("input", [])
            if isinstance(tool_choice, dict):
                name = str(tool_choice["name"])
                arguments = (
                    "{}" if name == "get_my_employee_profile" else '{"query":"synthetic handbook"}'
                )
                value = {
                    "model": model,
                    "status": "completed",
                    "background": False,
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": f"call-{name}",
                            "name": name,
                            "arguments": arguments,
                            "status": "completed",
                        }
                    ],
                }
                await _record(f"openai.forced.{name}")
            else:
                calls = [item for item in inputs if item.get("type") == "function_call"]
                if calls:
                    call = calls[-1]
                    basis = "knowledge" if call["name"] == "search_hr_knowledge" else "erp_data"
                    output = _final(basis, str(call["call_id"]))
                    await _record(f"openai.final.{basis}")
                else:
                    output = _final("general")
                    await _record("openai.final.general")
                value = {
                    "model": model,
                    "status": "completed",
                    "background": False,
                    "output": [output],
                }
        await _respond(writer, value)
    finally:
        writer.close()
        await writer.wait_closed()


def _context(*, client_auth: bool) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(os.environ["SYNTHETIC_SERVER_CERT"], os.environ["SYNTHETIC_SERVER_KEY"])
    if client_auth:
        context.load_verify_locations(os.environ["SYNTHETIC_CA_CERT"])
        context.verify_mode = ssl.CERT_REQUIRED
    return context


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        loop.add_signal_handler(getattr(signal, name), stop.set)
    servers = (
        await asyncio.start_server(_openai, "0.0.0.0", 443, ssl=_context(client_auth=False)),
        await asyncio.start_server(_erp, "0.0.0.0", 8443, ssl=_context(client_auth=True)),
        await asyncio.start_server(_laravel, "0.0.0.0", 8444, ssl=_context(client_auth=True)),
    )
    await _record("services.ready")
    await stop.wait()
    for server in reversed(servers):
        server.close()
        await server.wait_closed()
    await _record("services.closed")


asyncio.run(main())
