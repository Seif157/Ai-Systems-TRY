"""Production manifest for the first HR Core read capability."""

from erp_ai.capabilities import CapabilityManifest, DataClassification, ToolDescriptor

HR_CORE_MANIFEST = CapabilityManifest(
    capability_code="hr_core",
    version="1.0.0",
    required_modules=("hr_core",),
    tools=(
        ToolDescriptor(
            tool_name="get_my_employee_profile",
            version="1.0.0",
            operation="read",
            required_permissions_all=("hr.profile.read_self",),
            required_roles_any=(),
            allowed_purposes=("employee_self_service",),
            data_classification=DataClassification.RESTRICTED,
            audit_action="hr.profile.read_self",
            requires_employee_context=True,
        ),
    ),
)
