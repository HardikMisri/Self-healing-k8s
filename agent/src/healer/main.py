"""FastAPI app: Alertmanager webhook + read-only incident API + Prometheus metrics."""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from prometheus_client import make_asgi_app

from .config import Settings
from .models import AlertmanagerPayload

log = logging.getLogger("healer")


def build_orchestrator(settings: Settings):
    from .brain import build_brain
    from .context import ContextBuilder
    from .executor import Executor
    from .guardrails import Guardrails
    from .incidents import IncidentStore
    from .kube import KubeClient, load_kube_config
    from .observability import LokiClient, PrometheusClient
    from .orchestrator import Orchestrator
    from .verifier import Verifier

    load_kube_config()
    kube = KubeClient()
    prom, loki = PrometheusClient(settings.prometheus_url), LokiClient(settings.loki_url)
    return Orchestrator(
        settings, kube, ContextBuilder(kube, prom, loki, settings), build_brain(settings),
        Guardrails(settings), Executor(kube, settings.dry_run), Verifier(kube, prom, settings),
        IncidentStore(settings.incident_dir),
    )


def create_app(settings: Settings | None = None, orchestrator=None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        log.info("starting: dry_run=%s namespaces=%s provider=%s", settings.dry_run,
                 sorted(settings.namespaces), settings.llm_provider)
        if orchestrator is None:
            orch()
        yield

    app = FastAPI(title="Self-Healing Kubernetes Agent", version="0.1.0", lifespan=lifespan)
    app.state.orch = orchestrator

    def orch():
        if app.state.orch is None:  # lazy: lets the app import without a cluster (tests, docs)
            app.state.orch = build_orchestrator(settings)
        return app.state.orch

    def auth(authorization: str | None = Header(default=None)) -> None:
        if settings.webhook_token and not hmac.compare_digest(
            authorization or "", f"Bearer {settings.webhook_token}"
        ):
            raise HTTPException(status_code=401, detail="invalid token")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "dry_run": settings.dry_run}

    @app.post("/alerts", dependencies=[Depends(auth)], status_code=202)
    def alerts(payload: AlertmanagerPayload):
        accepted = 0
        for a in payload.alerts:
            if a.status == "firing":
                orch().submit(a)
                accepted += 1
        return {"accepted": accepted}

    @app.get("/incidents")
    def incidents():
        return [i.model_dump(exclude={"timeline"}) for i in orch().store.list()]

    @app.get("/incidents/{incident_id}")
    def incident(incident_id: str):
        inc = orch().store.get(incident_id)
        if inc is None:
            raise HTTPException(404, "not found")
        return inc

    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()
