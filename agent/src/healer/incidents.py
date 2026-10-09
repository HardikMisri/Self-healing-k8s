"""Incident store (memory + JSON/Markdown files) and report rendering."""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path

from .models import Context, Incident

log = logging.getLogger(__name__)


def render_markdown(i: Incident, ctx: Context | None) -> str:
    d = i.decision
    lines = [
        f"# Incident {i.id}: {i.alert_name} on {i.target}",
        "",
        f"- **Time:** {i.created_at}",
        f"- **Outcome:** {i.outcome}{' (dry-run)' if i.dry_run else ''}",
        f"- **Action taken:** {i.executed_action or 'none'}",
    ]
    if d:
        lines += [
            f"- **Root cause ({d.source}, confidence {d.confidence:.2f}):** {d.root_cause}",
            f"- **Chosen remediation:** `{d.action}`" + (f" -> {d.replicas} replicas" if d.replicas else ""),
            f"- **Reasoning:** {d.reasoning}",
        ]
    if i.guardrail_note:
        lines.append(f"- **Guardrail:** {i.guardrail_note}")
    lines += ["", "## Summary", "", i.summary or "(none)", "", "## Timeline", ""]
    lines += [f"- `{e.ts}` {e.message}" for e in i.timeline]
    if ctx:
        lines += ["", "## Evidence", "", f"- Metrics: `{ctx.metrics}`"]
        lines += [f"- Pod `{p.name}`: restarts={p.restarts}, waiting={p.waiting_reason}, "
                  f"last_terminated={p.last_terminated_reason} (exit {p.last_exit_code})" for p in ctx.pods]
        if ctx.events:
            lines += ["", "### Recent warning events", ""] + [f"- {e}" for e in ctx.events[-8:]]
    return "\n".join(lines) + "\n"


class IncidentStore:
    def __init__(self, directory: str, keep: int = 200):
        self.dir = Path(directory)
        self.keep = keep
        self._items: "OrderedDict[str, Incident]" = OrderedDict()
        self._lock = threading.Lock()
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("incident dir %s not writable (%s); keeping incidents in memory only", directory, e)

    def save(self, incident: Incident, ctx: Context | None) -> None:
        with self._lock:
            self._items[incident.id] = incident
            while len(self._items) > self.keep:
                self._items.popitem(last=False)
        try:
            (self.dir / f"{incident.id}.json").write_text(incident.model_dump_json(indent=2))
            (self.dir / f"{incident.id}.md").write_text(render_markdown(incident, ctx))
        except OSError as e:
            log.warning("could not persist incident %s: %s", incident.id, e)

    def list(self) -> list[Incident]:
        with self._lock:
            return list(reversed(self._items.values()))

    def get(self, incident_id: str) -> Incident | None:
        with self._lock:
            return self._items.get(incident_id)
