# AI Access and RAG Contract

## 1. Separation of responsibilities

The HR AI capability has two data paths:

| Need | Path |
|---|---|
| Policies, manuals, procedures, FAQs | RAG over approved knowledge documents |
| Live employee, leave, attendance, payslip, training, or request data | Permission-aware ERP query tool/API |
| Create or change an ERP record | Validated ERP command with authorization, confirmation, idempotency, and audit |

Transactional rows are not embedded into the RAG index. Database schema documentation may be used by developers and evaluation tooling, but is not an employee-facing knowledge corpus.

## 2. Capability and entitlement resolution

Before the model receives tools:

1. Authenticate the user.
2. Resolve the database/customer environment from trusted server configuration.
3. Resolve enabled modules from `erp_module_installations`.
4. Resolve user-to-employee context from `user_employee_links`.
5. Resolve roles, reporting hierarchy, legal entity, and purpose.
6. Register only tools allowed by the intersection of module entitlement and user authorization.

Disabled tools are not sent to the model. The server also rejects any manually forged call to a disabled or unauthorized tool.

## 3. Database access

- AI has no unrestricted table access and no production text-to-SQL tool.
- Read tools call Laravel query services or security-barrier views/functions with typed parameters.
- Write tools call domain commands; they never issue arbitrary INSERT/UPDATE/DELETE statements.
- Database credentials are customer-specific, least-privileged, rotated, and unavailable to prompts.
- Highly Restricted columns are omitted by default and returned only by purpose-specific tools.

## 4. Initial HR Core + Leave tools

| Tool | Minimum authorization | Data returned |
|---|---|---|
| `get_my_employee_profile` | Authenticated linked employee | Safe profile subset; no national ID/passport/religion/bank data |
| `get_my_leave_balances` | Employee | Leave type, available/accrued/used/pending, fiscal year, freshness |
| `list_my_leave_requests` | Employee | Own requests and status history |
| `get_my_leave_request` | Employee | One owned request, approval/status timeline |
| `preview_leave_request` | Employee | Policy/calendar calculation without writing |
| `create_leave_request` | Employee + explicit confirmation | Validated idempotent request command |
| `cancel_my_leave_request` | Employee + state/policy permission + confirmation | Idempotent cancellation command |
| `list_team_leave_requests` | Manager | Direct/authorized hierarchy only |
| `review_leave_request` | Authorized manager/HR + confirmation | Approval-domain command, not a direct row update |
| `search_hr_policy` | Entitled HR user | RAG excerpts and citations filtered by role/legal entity/effective date |

Payroll, performance, medical, recruitment, and succession tools are excluded from the first release.

## 5. Tool contracts

Every tool declares:

- Versioned name and schema.
- Required module.
- Required role and purpose.
- Allowed employee/legal-entity scope.
- Typed input with size/range constraints.
- Stable output schema.
- Data classification.
- Freshness fields.
- Expected errors without sensitive detail.
- Audit action name.
- Whether confirmation, approval, or idempotency is required.

The authenticated employee ID and customer database are injected server-side. The model cannot supply or override them for “my” tools.

## 6. Write-command safety

Every write tool must:

1. Re-check module entitlement and authorization.
2. Validate business state and row version.
3. Preview the intended change.
4. Obtain explicit confirmation for material changes.
5. Use a unique idempotency key recorded in `hr_command_executions`.
6. Commit the business row, workflow history, ledger entry, and audit event in one transaction where applicable.
7. Return a stable reference, never a fabricated success message.

High-impact actions such as salary, bank-account, termination, promotion, payslip, or performance changes require an approval workflow and should not be enabled in the initial AI release.

## 7. RAG corpus

Approved document types include:

- Employee handbooks.
- Leave, attendance, remote-work, and workplace policies.
- HR service procedures.
- Module user manuals.
- Approved legal/regulatory guidance with source ownership.

Prohibited by default:

- Employee rows and exports.
- Payslips and salary records.
- Medical certificates.
- IDs, passports, bank information, CVs, appraisals, and succession records.
- Raw emails, chats, tickets, or unreviewed uploads.

## 8. RAG metadata

Every indexed chunk requires:

```json
{
  "customer_database_id": "server-injected-environment-id",
  "module_code": "hr",
  "subdomain": "leave",
  "document_id": "uuid",
  "document_version": 3,
  "legal_entity_ids": ["uuid"],
  "country_codes": ["EG"],
  "allowed_roles": ["employee", "manager", "hr"],
  "language": "en",
  "effective_from": "2026-01-01",
  "effective_to": null,
  "classification": "internal",
  "source_checksum": "sha256"
}
```

Metadata filters are applied before retrieval. The model cannot widen them. Superseded documents are excluded unless the user asks an authorized historical question.

## 9. Retrieval quality

- Use hybrid keyword and vector retrieval.
- Apply customer/module/legal-entity/role/effective-date filters before retrieval.
- Rerank the authorized candidate set.
- Return source citations and policy version/effective date.
- If no authoritative source is found, say so rather than inventing a policy.
- Maintain Arabic and English evaluation sets; test mixed-language queries and localized names.

## 10. Logging and privacy

- Tool name, actor, target, outcome, latency, correlation ID, and safe error code are logged.
- Prompts, retrieved text, tool inputs, and tool outputs are redacted according to classification.
- Highly Restricted values never appear in ordinary traces.
- Debug access is purpose-limited and audited.
- Logs follow a defined retention period and customer-isolated storage.

## 11. Mandatory evaluation suites

### Authorization

- Employee cannot read another employee’s record.
- Manager scope follows the approved hierarchy only.
- HR role cannot access payroll unless Payroll is enabled and permitted.
- Disabled modules expose neither tools nor data.
- Cross-customer database and vector-index access always fails.

### Retrieval

- Correct policy version and legal entity are selected.
- Superseded or future policies are excluded.
- Arabic/English equivalents retrieve the same governing policy.
- Malicious instructions inside documents do not change tool authorization.

### Tool behavior

- Correct tool and typed arguments are selected.
- Missing information produces a question, not a guessed write.
- Duplicate idempotency key produces one business action.
- Cancelled confirmation produces no write.
- Tool/database failure is not reported as success.

### Data leakage

- No Restricted/Highly Restricted values in prompts, traces, citations, error messages, or unauthorized responses.
- Synthetic canary records belonging to another customer or role are never returned.

Release criterion: zero authorization or cross-customer leaks; all material actions are auditable and idempotent.

