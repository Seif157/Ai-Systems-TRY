from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_runtime_manifest_has_restricted_platform_boundary() -> None:
    deployment = (ROOT / "deploy/kubernetes/base/deployment.yaml").read_text(encoding="utf-8")
    required = (
        "replicas: 2",
        "automountServiceAccountToken: false",
        "runAsNonRoot: true",
        "runAsUser: 10001",
        "allowPrivilegeEscalation: false",
        "readOnlyRootFilesystem: true",
        'drop: ["ALL"]',
        "type: RuntimeDefault",
        "enableServiceLinks: false",
        "maxUnavailable: 0",
        "startupProbe:",
        "readinessProbe:",
        "livenessProbe:",
        "ephemeral-storage:",
        "@sha256:",
    )
    assert all(item in deployment for item in required)
    assert "latest" not in deployment and "hostPath" not in deployment


def test_no_ingress_secret_or_broad_egress_is_committed() -> None:
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "deploy/kubernetes").rglob("*.yaml")
    )
    assert "kind: Ingress" not in rendered
    assert "kind: Secret" not in rendered
    assert "0.0.0.0/0" not in rendered
    assert "privileged: true" not in rendered
    assert "hostNetwork: true" not in rendered


def test_migration_job_is_one_target_nonretrying_and_separate() -> None:
    job = (ROOT / "deploy/kubernetes/migration-jobs/job-template.yaml").read_text(encoding="utf-8")
    assert "backoffLimit: 0" in job
    assert "restartPolicy: Never" in job
    assert "erp-ai-migration" in job
    assert "replace-exact-administrative-entrypoint" in job
    assert "/run/secrets/erp-ai-admin" in job
    assert "/etc/erp-ai" in job
    assert "erp-ai-runtime-secrets" not in job


def test_container_installs_pinned_libpq_offline() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "apk verify /tmp/apks/*.apk" in dockerfile
    assert "apk add --no-network --no-cache --repositories-file /dev/null" in dockerfile


def test_container_oci_identity_has_no_repository_placeholders() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG OCI_REVISION=" in dockerfile
    assert "https://github.com/Seif157/Ai-Systems-TRY" in dockerfile
    assert "replace-owner" not in dockerfile
    assert "replace-at-build" not in dockerfile
