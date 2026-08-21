"""Entitlement-aware capability contracts and filtering."""

from erp_ai.capabilities.access import (
    AccessDenial,
    CapabilityAccessDecision,
    ModelCapability,
    ModelToolDescriptor,
    evaluate_capability_access,
)
from erp_ai.capabilities.models import CapabilityManifest, DataClassification, ToolDescriptor
from erp_ai.capabilities.registry import CapabilityRegistry

__all__ = [
    "AccessDenial",
    "CapabilityAccessDecision",
    "CapabilityManifest",
    "CapabilityRegistry",
    "DataClassification",
    "ModelCapability",
    "ModelToolDescriptor",
    "ToolDescriptor",
    "evaluate_capability_access",
]
