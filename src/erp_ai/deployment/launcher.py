"""Single-worker hardened ASGI server launcher."""

import asyncio
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI

from .composition import compose_deployed_runtime
from .config import ProductionDeploymentConfig, load_production_config
from .factory import ConfiguredProductionDependencyFactory
from .logging import emit_lifecycle_event
from .secrets import FileSecretProvider


def run_server(
    config: ProductionDeploymentConfig, application_factory: Callable[[], FastAPI]
) -> None:
    """Run one explicitly constructed application with proxy and access logging disabled."""

    copied = ProductionDeploymentConfig.model_validate(
        config.model_dump(mode="python"), strict=True
    )
    settings = copied.server
    server = uvicorn.Server(
        uvicorn.Config(
            app=application_factory,
            factory=True,
            host=settings.bind_address,
            port=settings.port,
            workers=1,
            loop="asyncio",
            lifespan="on",
            access_log=False,
            proxy_headers=False,
            server_header=False,
            date_header=False,
            log_config=None,
            limit_concurrency=settings.concurrency_limit,
            backlog=settings.backlog,
            timeout_keep_alive=settings.keep_alive_seconds,
            timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
        )
    )
    emit_lifecycle_event("runtime.start", "erp_ai", "started", "info", copied.deployment_version)
    try:
        asyncio.run(server.serve())
        if not server.started:
            emit_lifecycle_event(
                "runtime.failure", "erp_ai", "failed", "error", copied.deployment_version
            )
            raise SystemExit(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except SystemExit:
        raise
    except Exception:
        emit_lifecycle_event(
            "runtime.failure", "erp_ai", "failed", "error", copied.deployment_version
        )
        raise SystemExit(1) from None


def main() -> None:
    """Load mounted values and construct the complete production application graph."""

    try:
        config = load_production_config()
        runtime = compose_deployed_runtime(
            config, FileSecretProvider(), ConfiguredProductionDependencyFactory()
        )
        run_server(config, lambda: runtime.application)
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except BaseException:
        raise SystemExit(1) from None
