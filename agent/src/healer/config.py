"""Runtime configuration. Every setting can be overridden with a HEALER_* env var."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEALER_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # --- safety ---
    dry_run: bool = True  # SAFE DEFAULT: decide + log, but do not touch the cluster
    allowed_namespaces: str = "demo"  # comma separated
    require_opt_in_label: bool = True
    opt_in_label: str = "self-healing"  # deployment must carry <label>=enabled
    cooldown_seconds: int = 300
    max_actions_per_hour: int = 3
    max_replicas: int = 5
    min_confidence: float = 0.5
    webhook_token: str | None = None  # if set, /alerts requires "Authorization: Bearer <token>"

    # --- decision ---
    llm_provider: str = "anthropic"  # "anthropic" | "rules"
    model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    recent_change_window_seconds: int = 900
    cpu_alert_threshold: float = 0.85

    # --- verification ---
    verify_timeout_seconds: int = 240
    verify_interval_seconds: int = 5
    verify_stable_checks: int = 3

    # --- data sources ---
    prometheus_url: str = "http://kps-prometheus.monitoring.svc:9090"
    loki_url: str = "http://loki.monitoring.svc:3100"
    log_tail_lines: int = 60
    max_log_chars: int = 6000

    # --- output ---
    incident_dir: str = "/data/incidents"
    max_workers: int = 4

    @property
    def namespaces(self) -> set[str]:
        return {n.strip() for n in self.allowed_namespaces.split(",") if n.strip()}
