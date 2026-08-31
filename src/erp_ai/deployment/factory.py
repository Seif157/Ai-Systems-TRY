"""Concrete deployment-owned construction of the complete production provider graph."""

import asyncio
import json
import ssl
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator

from erp_ai.application import TrustedRouteCatalog, TrustedRouteEntry
from erp_ai.capabilities import CapabilityRegistry
from erp_ai.capabilities.hr_core import HR_CORE_MANIFEST
from erp_ai.capabilities.hr_knowledge import HR_KNOWLEDGE_MANIFEST, SearchHrKnowledgeHandler
from erp_ai.capabilities.leave import LEAVE_MANIFEST
from erp_ai.infrastructure.erp_trust import ErpTrustHttpConfig
from erp_ai.infrastructure.laravel_erp import LaravelErpReadConfig, LaravelErpReadProviderBundle
from erp_ai.infrastructure.openai import (
    OpenAICredentialProvider,
    OpenAIProductionConfig,
    OpenAIProjectPrivacyAttestation,
    OpenAIProjectRoute,
    build_openai_production_bundle,
)
from erp_ai.infrastructure.postgres import (
    PostgresKnowledgeContractVerifier,
    PostgresSemanticKnowledgeRetrievalProvider,
    ProductionKnowledgeConfig,
    ProductionKnowledgeDatabaseRouter,
    SemanticRetrievalPolicy,
)
from erp_ai.infrastructure.postgres.production_rag import BoundKnowledgeTransactionVerifier
from erp_ai.infrastructure.postgres_audit import RuntimeAuditDatabaseConfig
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest
from erp_ai.knowledge.embeddings import EmbeddingProfile
from erp_ai.orchestration import AgentLimits
from erp_ai.runtime import ExternalRuntimeBundle, ProviderLifecycleLease, ProviderRuntimeLifecycle
from erp_ai.tools import ReadToolHandler
from erp_ai.transport.http import InternalHttpTransportConfig

from .config import MAXIMUM_CONFIG_DEPTH, ProductionDeploymentConfig, SecretReference, _depth
from .secrets import FileSecretProvider
from .ssl import create_verified_ssl_context, load_client_identity

if TYPE_CHECKING:
    from erp_ai.infrastructure.erp_trust import ErpAssertionVerifierConfig


class _RuntimeOpenAIProductionConfig(OpenAIProductionConfig):
    """Preserve strict JSON semantics when the mounted catalog freezes nested lists."""

    @field_validator("routes", "attestations", mode="before")
    @classmethod
    def freeze_runtime_collections(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, list):
            return value
        nested_model = (
            OpenAIProjectRoute if info.field_name == "routes" else OpenAIProjectPrivacyAttestation
        )
        return tuple(
            nested_model.model_validate_json(
                json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                strict=True,
            )
            for item in value
        )


class ProductionRuntimeCatalog(BaseModel):
    """Strict server-mounted non-public construction catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    transport_config: InternalHttpTransportConfig
    audit_config: dict[str, Any] = Field(repr=False)
    knowledge_config: dict[str, Any] = Field(repr=False)
    openai_config: _RuntimeOpenAIProductionConfig = Field(repr=False)
    embedding_profiles: tuple[EmbeddingProfile, ...] = Field(min_length=1, repr=False)
    retrieval_policies: tuple[SemanticRetrievalPolicy, ...] = Field(min_length=1, repr=False)
    trusted_routes: tuple[TrustedRouteEntry, ...] = Field(min_length=1, repr=False)
    agent_limits: AgentLimits
    maximum_intent_lifetime_seconds: int = Field(strict=True, ge=1, le=300)


class ErpTrustDeploymentCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    assertion_config: dict[str, Any] = Field(repr=False)
    http_config: ErpTrustHttpConfig = Field(repr=False)
    ca_reference: SecretReference = Field(repr=False)
    certificate_reference: SecretReference = Field(repr=False)
    private_key_reference: SecretReference = Field(repr=False)


def _validated_json(model: type[BaseModel], raw: bytes) -> BaseModel:
    """Validate bounded duplicate-free JSON using Pydantic's strict JSON semantics."""

    value = _strict_value(raw)
    if _depth(value) > MAXIMUM_CONFIG_DEPTH:
        raise ValueError("production runtime catalog is unavailable")
    return model.model_validate_json(raw, strict=True)


def _assertion_config(value: object) -> "ErpAssertionVerifierConfig":
    """Decode the one JSON-inexpressible secret-bytes field at composition time."""

    from erp_ai.infrastructure.erp_trust import ErpAssertionVerifierConfig
    from erp_ai.infrastructure.erp_trust.config import decode_public_key

    if isinstance(value, ErpAssertionVerifierConfig):
        return ErpAssertionVerifierConfig.model_validate(value, strict=True)
    if not isinstance(value, dict):
        raise ValueError("ERP assertion configuration is unavailable")
    decoded = dict(value)
    keys = []
    for item in decoded.get("keys", ()):
        if not isinstance(item, dict) or not isinstance(item.get("public_key"), str):
            raise ValueError("ERP assertion configuration is unavailable")
        key = dict(item)
        key["public_key"] = decode_public_key(key["public_key"])
        for field in ("activates_at", "retires_at"):
            if not isinstance(key.get(field), str):
                raise ValueError("ERP assertion configuration is unavailable")
            key[field] = datetime.fromisoformat(key[field])
        keys.append(key)
    decoded["keys"] = keys
    for field in ("maximum_lifetime", "maximum_clock_skew"):
        seconds = decoded.get(field)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("ERP assertion configuration is unavailable")
        decoded[field] = timedelta(seconds=seconds)
    return ErpAssertionVerifierConfig.model_validate(decoded, strict=True)


class LaravelDeploymentCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    http_config: LaravelErpReadConfig = Field(repr=False)
    ca_reference: SecretReference = Field(repr=False)
    certificate_reference: SecretReference = Field(repr=False)
    private_key_reference: SecretReference = Field(repr=False)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SecureRequestIdFactory:
    def create(self) -> str:
        return str(uuid4())


class FileOpenAICredentialProvider:
    __slots__ = ("_routes", "_secrets")

    def __init__(
        self,
        config: ProductionDeploymentConfig,
        catalog: OpenAIProductionConfig,
        secrets: FileSecretProvider,
    ) -> None:
        configured = {route.customer_environment_id: route for route in config.customer_routes}
        self._routes: dict[tuple[str, str, str], str] = {}
        for route in catalog.routes:
            deployment = configured.get(route.customer_environment_id)
            if deployment is None or deployment.openai_project_route_id != route.project_id:
                raise ValueError("OpenAI credential route is unavailable")
            self._routes[(route.credential_reference, route.organization_id, route.project_id)] = (
                deployment.openai_credential_reference
            )
        self._secrets = secrets

    async def resolve(
        self, credential_reference: str, organization_id: str, project_id: str
    ) -> SecretStr:
        try:
            reference = self._routes[(credential_reference, organization_id, project_id)]
        except KeyError:
            raise ValueError("OpenAI credential is unavailable") from None
        return self._secrets.read_text(reference)


class AggregateProviderLifecycle:
    __slots__ = ("_lock", "_resources", "_state")

    def __init__(self, resources: tuple[ProviderRuntimeLifecycle, ...]) -> None:
        if not resources or not all(
            isinstance(item, ProviderRuntimeLifecycle) for item in resources
        ):
            raise TypeError("provider lifecycle resources are required")
        self._resources = resources
        self._state = "created"
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        async with self._lock:
            if self._state != "created":
                raise RuntimeError("provider startup is unavailable")
            opened: list[ProviderRuntimeLifecycle] = []
            try:
                for resource in self._resources:
                    await resource.open()
                    opened.append(resource)
            except BaseException:
                for resource in reversed(opened):
                    with suppress(BaseException):
                        await resource.close()
                self._state = "failed"
                raise
            self._state = "ready"

    async def close(self) -> None:
        async with self._lock:
            if self._state == "closed":
                return
            cancellation: asyncio.CancelledError | None = None
            errors: list[BaseException] = []
            for resource in reversed(self._resources):
                try:
                    await resource.close()
                except asyncio.CancelledError as error:
                    cancellation = cancellation or error
                except BaseException as error:
                    errors.append(error)
            self._state = "closed" if not errors and cancellation is None else "failed"
            if cancellation is not None:
                raise cancellation
            if errors:
                raise RuntimeError("provider shutdown failed") from None


class CustomerKnowledgeProvider:
    __slots__ = ("_providers",)

    def __init__(self, providers: dict[str, PostgresSemanticKnowledgeRetrievalProvider]) -> None:
        self._providers = dict(providers)

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        try:
            provider = self._providers[request.customer_environment_id]
        except KeyError:
            raise ValueError("knowledge route is unavailable") from None
        return await provider.retrieve(request)


def _strict_value(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )
    return value


def _strict_catalog(raw: bytes) -> ProductionRuntimeCatalog:
    return cast(ProductionRuntimeCatalog, _validated_json(ProductionRuntimeCatalog, raw))


class ConfiguredProductionDependencyFactory:
    """Concrete factory used directly by the packaged launcher."""

    __slots__ = ()

    def build(
        self, config: ProductionDeploymentConfig, secrets: FileSecretProvider
    ) -> ExternalRuntimeBundle:
        catalog = _strict_catalog(secrets.read_bytes(config.runtime_catalog_reference))
        erp_raw = secrets.read_bytes(config.erp_trust_config_reference)
        laravel_raw = secrets.read_bytes(config.laravel_config_reference)
        erp_catalog = cast(
            ErpTrustDeploymentCatalog,
            _validated_json(ErpTrustDeploymentCatalog, erp_raw),
        )
        laravel_catalog = cast(
            LaravelDeploymentCatalog,
            _validated_json(LaravelDeploymentCatalog, laravel_raw),
        )
        audit_raw = dict(catalog.audit_config)
        control = dict(audit_raw["control"])
        control["writer_dsn"] = secrets.read_text(
            config.audit_control_dsn_reference
        ).get_secret_value()
        audit_raw["control"] = control
        audit_customers = {
            str(item["customer_environment_id"]): dict(item) for item in audit_raw["customers"]
        }
        knowledge_raw = dict(catalog.knowledge_config)
        knowledge_routes = {
            str(item["customer_environment_id"]): dict(item) for item in knowledge_raw["routes"]
        }
        configured_customers = {item.customer_environment_id for item in config.customer_routes}
        openai_customers = {item.customer_environment_id for item in catalog.openai_config.routes}
        if not (
            configured_customers
            == set(audit_customers)
            == set(knowledge_routes)
            == openai_customers
        ):
            raise ValueError("production customer routes are incomplete")
        for deployment in config.customer_routes:
            audit_customers[deployment.customer_environment_id]["writer_dsn"] = secrets.read_text(
                deployment.audit_runtime_dsn_reference
            ).get_secret_value()
            knowledge_routes[deployment.customer_environment_id]["runtime_dsn"] = secrets.read_text(
                deployment.knowledge_runtime_dsn_reference
            ).get_secret_value()
            knowledge_routes[deployment.customer_environment_id]["expected_generation_id"] = UUID(
                str(knowledge_routes[deployment.customer_environment_id]["expected_generation_id"])
            )
        audit_raw["customers"] = tuple(audit_customers.values())
        knowledge_raw["routes"] = tuple(knowledge_routes.values())
        audit = RuntimeAuditDatabaseConfig.model_validate_json(
            json.dumps(audit_raw, separators=(",", ":"), allow_nan=False), strict=True
        )
        knowledge = ProductionKnowledgeConfig.model_validate(knowledge_raw, strict=True)
        assertion = _assertion_config(erp_catalog.assertion_config)
        erp_trust = ErpTrustHttpConfig.model_validate(erp_catalog.http_config, strict=True)
        erp_ssl = create_verified_ssl_context(secrets.materialized_path(erp_catalog.ca_reference))
        load_client_identity(
            erp_ssl,
            secrets.materialized_path(erp_catalog.certificate_reference),
            secrets.materialized_path(erp_catalog.private_key_reference),
        )
        laravel_ssl = create_verified_ssl_context(
            secrets.materialized_path(laravel_catalog.ca_reference)
        )
        load_client_identity(
            laravel_ssl,
            secrets.materialized_path(laravel_catalog.certificate_reference),
            secrets.materialized_path(laravel_catalog.private_key_reference),
        )
        clock = SystemClock()
        credentials: OpenAICredentialProvider = FileOpenAICredentialProvider(
            config, catalog.openai_config, secrets
        )
        openai = build_openai_production_bundle(
            config=catalog.openai_config,
            credential_provider=credentials,
            clock=clock,
            ssl_context=ssl.create_default_context(),
        )
        profiles = {item.profile_sha256: item for item in catalog.embedding_profiles}
        policies = {item.embedding_profile_sha256: item for item in catalog.retrieval_policies}
        route_profiles = {item.embedding_profile_sha256 for item in knowledge.routes}
        if route_profiles != set(profiles) or route_profiles != set(policies):
            raise ValueError("production embedding routes are incomplete")
        router = ProductionKnowledgeDatabaseRouter(knowledge, PostgresKnowledgeContractVerifier())
        providers: dict[str, PostgresSemanticKnowledgeRetrievalProvider] = {}
        for route in knowledge.routes:
            profile = profiles[route.embedding_profile_sha256]
            providers[route.customer_environment_id] = PostgresSemanticKnowledgeRetrievalProvider(
                router,
                route.customer_environment_id,
                profile,
                openai.embedding_provider(route.customer_environment_id, "employee_self_service"),
                policies[route.embedding_profile_sha256],
                (
                    route.statement_timeout_ms,
                    route.lock_timeout_ms,
                    route.idle_transaction_timeout_ms,
                ),
                BoundKnowledgeTransactionVerifier(route),
            )
        downstream = AggregateProviderLifecycle((router, openai.lifecycle))
        laravel = LaravelErpReadProviderBundle(laravel_catalog.http_config, laravel_ssl, downstream)
        knowledge_handler = SearchHrKnowledgeHandler(CustomerKnowledgeProvider(providers))
        registry = CapabilityRegistry((HR_CORE_MANIFEST, LEAVE_MANIFEST, HR_KNOWLEDGE_MANIFEST))
        return ExternalRuntimeBundle(
            transport_config=catalog.transport_config,
            assertion_config=assertion,
            erp_trust_config=erp_trust,
            erp_ssl_context=erp_ssl,
            audit_config=audit,
            route_catalog=TrustedRouteCatalog(catalog.trusted_routes),
            registry=registry,
            handlers=(*laravel.handlers, cast(ReadToolHandler, knowledge_handler)),
            model_provider=openai.model_provider,
            provider_lifecycle_lease=ProviderLifecycleLease(laravel.lifecycle),
            agent_limits=catalog.agent_limits,
            maximum_intent_lifetime=timedelta(seconds=catalog.maximum_intent_lifetime_seconds),
            request_id_factory=SecureRequestIdFactory(),
            clock=clock,
        )
