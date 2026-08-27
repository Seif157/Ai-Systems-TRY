# Deploying the production composition root

Step 26 intentionally provides no Uvicorn process, environment reader, file loader, certificate
loader, secret-manager adapter, migration runner, or production provider. A future platform
launcher must obtain secrets outside the core, create certificate-verifying `SSLContext` objects,
create runtime-only PostgreSQL writer routes, approve concrete providers, and inject every member
of `ExternalRuntimeBundle` explicitly.

The launcher must give each runtime exclusive ownership of its provider lifecycle and independently
owned external resources. It must provision and migrate Step 23 databases administratively before
startup; migration authority must never be placed in a runtime bundle. Startup verification is a
release gate, not a migration mechanism or continuous reachability monitor.

Step 27 through Step 29 remain responsible for real structured ERP, knowledge, and approved model
providers. Later deployment work must add secret rotation, launcher/process management, network
policy, TLS client-certificate provisioning, monitoring, and operational readiness without adding
public configuration authority.

The production wheel depends on pure `psycopg` and requires a compatible system `libpq` at
deployment. `psycopg-binary==3.3.4` is confined to the development/Windows verification group; a
Windows verification using that binary wrapper does not prove the production pure-libpq path.
Release verification must also install the wheel on Linux with system libpq and without
`psycopg-binary`.
