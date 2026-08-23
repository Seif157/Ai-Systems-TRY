from erp_ai.capabilities import DataClassification
from erp_ai.capabilities.hr_knowledge import HR_KNOWLEDGE_MANIFEST


def test_hr_knowledge_manifest_is_exact_and_read_only() -> None:
    assert HR_KNOWLEDGE_MANIFEST.capability_code == "hr_knowledge"
    assert HR_KNOWLEDGE_MANIFEST.version == "1.0.0"
    assert HR_KNOWLEDGE_MANIFEST.required_modules == ("hr_core",)
    assert len(HR_KNOWLEDGE_MANIFEST.tools) == 1
    tool = HR_KNOWLEDGE_MANIFEST.tools[0]
    assert tool.tool_name == "search_hr_knowledge"
    assert tool.version == "1.0.0"
    assert tool.operation == "read"
    assert tool.required_permissions_all == ("hr.knowledge.read",)
    assert tool.required_roles_any == ()
    assert tool.allowed_purposes == ("employee_self_service",)
    assert tool.data_classification is DataClassification.RESTRICTED
    assert tool.audit_action == "hr.knowledge.search"
    assert tool.requires_employee_context is False
