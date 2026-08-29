"""Fail-closed customer routing and deployment-attestation enforcement."""

from dataclasses import dataclass, field

from erp_ai.application import TrustedClock
from erp_ai.capabilities import DataClassification
from erp_ai.context.models import Identifier

from .config import (
    OpenAIProductionConfig,
    OpenAIProjectPrivacyAttestation,
    OpenAIProjectRoute,
)
from .errors import OpenAIPrivacyDenied


@dataclass(frozen=True, slots=True, init=False)
class ApprovedOpenAIRoute:
    route: OpenAIProjectRoute = field(repr=False)
    attestation: OpenAIProjectPrivacyAttestation = field(repr=False)

    def __init__(
        self, route: OpenAIProjectRoute, attestation: OpenAIProjectPrivacyAttestation
    ) -> None:
        object.__setattr__(
            self,
            "route",
            OpenAIProjectRoute.model_validate(route.model_dump(mode="python"), strict=True),
        )
        object.__setattr__(
            self,
            "attestation",
            OpenAIProjectPrivacyAttestation.model_validate(
                attestation.model_dump(mode="python"), strict=True
            ),
        )


class OpenAIProjectRouter:
    """Immutable per-runtime route map with no default or cross-customer fallback."""

    __slots__ = ("_attestations", "_clock", "_routes")

    def __init__(self, config: OpenAIProductionConfig, clock: TrustedClock) -> None:
        if not isinstance(clock, TrustedClock):
            raise TypeError("trusted clock is required")
        copied = OpenAIProductionConfig.model_validate(
            config.model_dump(mode="python"), strict=True
        )
        self._routes = {route.customer_environment_id: route for route in copied.routes}
        self._attestations = {item.policy_id: item for item in copied.attestations}
        self._clock = clock

    def authorize(
        self,
        customer_environment_id: Identifier,
        classification: DataClassification,
        purpose: str,
        endpoint: str,
    ) -> ApprovedOpenAIRoute:
        """Authorize before credentials or network access, capturing time exactly once."""

        now = self._clock.now()
        try:
            route = OpenAIProjectRoute.model_validate(
                self._routes[customer_environment_id].model_dump(mode="python"), strict=True
            )
            attestation = OpenAIProjectPrivacyAttestation.model_validate(
                self._attestations[route.privacy_attestation_id].model_dump(mode="python"),
                strict=True,
            )
            lifetime_seconds = (attestation.expires_at - attestation.approved_at).total_seconds()
            if (
                classification is DataClassification.HIGHLY_RESTRICTED
                or classification not in route.allowed_data_classifications
                or classification not in attestation.allowed_data_classifications
                or purpose not in route.allowed_purposes
                or purpose not in attestation.allowed_purposes
                or endpoint not in attestation.allowed_endpoints
                or attestation.organization_id != route.organization_id
                or attestation.project_id != route.project_id
                or attestation.approved_at > now
                or attestation.expires_at <= now
                or lifetime_seconds <= 0
                or lifetime_seconds > route.maximum_attestation_lifetime_seconds
                or now.tzinfo is None
                or now.utcoffset() is None
            ):
                raise OpenAIPrivacyDenied
        except OpenAIPrivacyDenied:
            raise
        except Exception:
            raise OpenAIPrivacyDenied from None
        return ApprovedOpenAIRoute(route, attestation)
