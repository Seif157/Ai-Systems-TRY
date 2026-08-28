# Laravel ERP read integration deployment

Provision one exact internal DNS origin, a private CA trust chain, an approved client identity,
and bounded connection settings outside application code. Never accept these from public or
model input. Start resources in this order: audit databases, ERP trust client, Laravel read
client contract verification, then the approved model-provider lifecycle. Roll back and close in
reverse order on failure.

Before deployment, the ERP owner must implement and test every requirement in
`docs/contracts/laravel-erp-read-api.md`, including database-per-customer routing, current snapshot
revalidation, legal-entity and record visibility, cursor security, predefined read queries, and
indistinguishable detail denial. Run a joint mTLS interoperability suite using deployed Laravel
and statically provisioned synthetic customer databases.

Local synthetic HTTPS tests prove only the Python adapter's behavior against the frozen contract.
Step 27 makes no real ERP call and provides no evidence that Laravel exists or satisfies its
security obligations.
