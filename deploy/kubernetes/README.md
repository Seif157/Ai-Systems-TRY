# Kubernetes production reference

Render with `kubectl kustomize deploy/kubernetes/base`. Replace the deliberately invalid image
reference with the reviewed OCI digest; never deploy by a mutable tag. The base creates no Secret,
Ingress, Role, or RoleBinding. Runtime and migration Secret volumes are provisioned separately and
must never be shared.

The internal gateway must use TLS or mTLS, preserve the exact raw `/v1/chat` framing contract, and
present the signed ERP assertion. The application ignores forwarded headers. Internet exposure is
prohibited. Distributed gateway rate limits must use an authenticated ERP service identity, never
an untrusted header, and its timeout must exceed the reviewed bounded application deadline without
becoming indefinite.

Standard NetworkPolicy cannot authorize the dynamic `api.openai.com` hostname. A deployment
overlay must provide reviewed CNI FQDN or firewall/NAT policy for only DNS, audit PostgreSQL,
knowledge PostgreSQL, ERP trust HTTPS, Laravel HTTPS, and `api.openai.com:443`. Do not weaken the
provider's fixed origin or `trust_env=False` policy. Enforcement must be tested with the selected
policy-enforcing CNI.

Migration Jobs are copied and specialized one target at a time. They have no Service or ingress,
use a distinct ServiceAccount and secret, never retry, and never run in runtime pods.
