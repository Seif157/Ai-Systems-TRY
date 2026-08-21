"""Production manifest for the first Leave read capability."""

from erp_ai.capabilities import CapabilityManifest, DataClassification, ToolDescriptor

LEAVE_MANIFEST = CapabilityManifest(
    capability_code="leave",
    version="1.0.0",
    required_modules=("hr_core", "leave"),
    tools=(
        ToolDescriptor(
            tool_name="get_my_leave_balances",
            version="1.0.0",
            operation="read",
            required_permissions_all=("leave.balance.read_self",),
            required_roles_any=(),
            allowed_purposes=("employee_self_service",),
            data_classification=DataClassification.RESTRICTED,
            audit_action="leave.balance.read_self",
            requires_employee_context=True,
        ),
    ),
)
