# Catalog metadata example

```toml
path = "customer_policy/controlled-policy.md"
raw_sha256 = "<sha256-of-approved-bytes>"
document_id = "<controlled-uuid>"
document_version = "1.0.0"
namespace = "hr"
source_type = "customer_policy"
customer_environment_id = "<trusted-customer-id>"
modules = ["hr_core", "leave"]
permissions = ["hr.knowledge.read"]
allowed_purposes = ["employee_self_service"]
legal_entities = ["<trusted-legal-entity-id>"]
classification = "internal"
effective_from = 2027-01-01T00:00:00Z
approval_reference = "<controlled-reference>"
approved_at = 2026-12-01T00:00:00Z
```

This is a structural example, not an approved source or proof of authorization.
