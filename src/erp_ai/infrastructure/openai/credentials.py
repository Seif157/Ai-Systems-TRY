"""Deployment-owned credential resolution boundary."""

from typing import Protocol, runtime_checkable

from pydantic import SecretStr

from erp_ai.context.models import Identifier


@runtime_checkable
class OpenAICredentialProvider(Protocol):
    async def resolve(
        self,
        credential_reference: Identifier,
        organization_id: Identifier,
        project_id: Identifier,
    ) -> SecretStr: ...
