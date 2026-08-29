# Model data privacy contract

Production ERP model and embedding traffic requires a deployment-owned OpenAI project with
an unexpired, exact organization/project privacy attestation. Only
`zero_data_retention` is accepted. Training and data-sharing opt-in must be strictly false;
the endpoint allowlist must be exactly Responses and Embeddings. Restricted traffic is
allowed only when both route and attestation approve its server-owned purpose and
classification. User text is always treated as at least `restricted`. Tool metadata may
raise the maximum classification. `highly_restricted` is denied by default.
The complete attestation is revalidated against a once-captured trusted time before every
credential resolution; validity at construction or startup is never sufficient for a later request.

The attestation is a deployment assertion, not cryptographic evidence of OpenAI dashboard,
contract, legal, retention, or account state. Production remains disabled until the owner
confirms the contract and privacy review, correct organization/project, approved ZDR status,
disabled training/data-sharing opt-ins, classifications and purposes, exact models, prompt
caching behavior, restricted service-account permissions, spend/rate limits, and incident
and credential-rotation ownership.

OpenAI states that API data is not used for training by default unless the customer opts in;
standard abuse-monitoring logs may be retained for up to 30 days, and approved Zero Data
Retention projects alter that behavior for eligible endpoints. `store=false` prevents
Responses application-state storage subject to documented limitations. Prompt caching can
have separately documented application-state behavior and this implementation does not claim
to disable automatic caching. See the current official
[API data controls documentation](https://developers.openai.com/api/docs/guides/your-data)
and [enterprise privacy statement](https://openai.com/enterprise-privacy/).

Regex redaction is not an authorization or privacy boundary. Minimization uses explicit
field projection. Prompts, results, knowledge, vectors, provider/project/model identity,
credentials, response identifiers, usage, and exception details remain outside public and
audit contracts.
