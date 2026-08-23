"""Production manifest for module-scoped HR knowledge retrieval."""

from erp_ai.capabilities import CapabilityManifest, DataClassification, ToolDescriptor

HR_KNOWLEDGE_MANIFEST = CapabilityManifest(
    capability_code="hr_knowledge",
    version="1.0.0",
    required_modules=("hr_core",),
    tools=(
        ToolDescriptor(
            tool_name="search_hr_knowledge",
            version="1.0.0",
            operation="read",
            required_permissions_all=("hr.knowledge.read",),
            required_roles_any=(),
            allowed_purposes=("employee_self_service",),
            data_classification=DataClassification.RESTRICTED,
            audit_action="hr.knowledge.search",
            requires_employee_context=False,
        ),
    ),
)
