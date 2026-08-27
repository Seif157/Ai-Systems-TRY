from pathlib import Path

from erp_ai.api import PublicChatRequest
from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.orchestration.audit import AgentAuditEvent
from erp_ai.tools.audit import ToolAuditEvent

ROOT = Path(__file__).parents[2]
RUNTIME = ROOT / "src" / "erp_ai" / "runtime"


def test_runtime_has_no_ambient_configuration_or_server_launcher() -> None:
    production = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME.glob("*.py"))
    forbidden = (
        "os.environ",
        "os.getenv",
        "load_dotenv",
        "uvicorn",
        "from tests",
        "import tests",
        "OpenRouterAgentModelProvider",
        "run_audit_migrations",
        "SecretManager",
        "app = FastAPI",
        "WeakSet",
        "WeakKeyDictionary",
        "id(",
        "weakref.finalize",
    )
    assert all(value not in production for value in forbidden)


def test_public_and_audit_contracts_have_no_runtime_authority_fields() -> None:
    forbidden = {
        "model_provider",
        "model_name",
        "route_catalog",
        "handler",
        "writer_dsn",
        "migration_dsn",
        "ssl_context",
        "verification_keys",
        "request_id_factory",
    }
    for model in (PublicChatRequest, ApplicationAuditEvent, AgentAuditEvent, ToolAuditEvent):
        assert forbidden.isdisjoint(model.model_fields)


def test_runtime_package_has_no_module_level_fastapi_application() -> None:
    composition = (RUNTIME / "composition.py").read_text(encoding="utf-8")
    assert "FastAPI(" not in composition
    assert "create_internal_http_app(" in composition


def test_runtime_does_not_import_migration_authority() -> None:
    production = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME.glob("*.py"))
    assert "postgres_audit.migrations" not in production
    assert "run_migrations" not in production
    assert "migration_dsn" not in production
