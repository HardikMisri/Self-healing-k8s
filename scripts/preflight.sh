#!/usr/bin/env bash
# Verifies the host can run the lab. Exits non-zero on hard failures, warns on soft ones.
set -u
fail=0
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=1; }

echo "Checking tools"
for t in docker kind kubectl helm; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t found"; else bad "$t not installed"; fi
done
command -v python3 >/dev/null 2>&1 && ok "python3 found ($(python3 --version 2>&1))" || warn "python3 missing (only needed for 'make test')"

echo "Checking Docker"
if docker info >/dev/null 2>&1; then
  ok "docker daemon reachable"
  mem=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  gb=$(( mem / 1024 / 1024 / 1024 ))
  if [ "$gb" -ge 6 ]; then ok "docker memory ${gb}GB"; else warn "docker has only ${gb}GB RAM; give it >= 6GB (Docker Desktop > Settings > Resources) or Prometheus will OOM"; fi
else
  bad "docker daemon not running (start Docker Desktop / dockerd)"
fi

if [ -r /proc/sys/fs/inotify/max_user_instances ]; then
  inst=$(cat /proc/sys/fs/inotify/max_user_instances)
  if [ "$inst" -lt 512 ]; then
    warn "inotify max_user_instances=$inst (<512): pods may fail with 'too many open files'. Fix: sudo sysctl fs.inotify.max_user_instances=512 fs.inotify.max_user_watches=524288"
  else ok "inotify limits ok"; fi
fi

echo "Checking ports used by 'make ui-*'"
for p in 3000 9090 8080; do
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then warn "port $p already in use"; fi
done

echo "Checking LLM configuration"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then ok "ANTHROPIC_API_KEY set (LLM mode)"; else warn "ANTHROPIC_API_KEY not set -> agent runs in deterministic rules-only mode (still fully functional)"; fi

[ "$fail" -eq 0 ] && echo "Preflight passed." || { echo "Preflight failed."; exit 1; }
