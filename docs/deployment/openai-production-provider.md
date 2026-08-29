# Deploying the direct OpenAI provider

Do not enable this provider until the deployment owner has completed the approvals listed in
the model-data privacy contract. Create one restricted OpenAI project and credential reference
per customer environment. Configure an immutable route catalog and attestation catalog through
the deployment composition root; do not read credentials or routes from public requests, and
do not place secrets in repository environment examples.

Approve an exact dated chat snapshot with function calling and strict structured output.
Approve an exact embedding model plus a deployment-owned revision and dimension matching the
offline publication profile. OpenAI may not offer a dated immutable embedding snapshot, so the
revision is a deployment/evaluation identity rather than provider proof. Re-embedding,
retrieval evaluation, and atomic publication are required for any approved identity change.

Credential rotation occurs behind the mandatory credential-provider protocol and requires no
public contract change. Restrict project/service-account permissions, configure rate and spend
limits, monitor only non-sensitive availability signals, and own key rotation and incident
response. Do not log request bodies, responses, credentials, project identifiers, model
identifiers, vectors, or provider errors.

No live OpenAI API verification was performed by Step 29. Synthetic protocol compatibility
does not establish Zero Data Retention, privacy, contractual approval, Arabic/English HR
quality, model safety, retrieval quality, or production readiness.
