#!/bin/bash
set -u

# Schutzschwelle: 122 GB belegter RAM (dezimal). Am 19.09.2026 kurzzeitig auf 126
# angehoben - das verlagerte das Problem nur: statt eines sauberen Stopps brach dann
# cuBLAS mit CUBLAS_STATUS_INTERNAL_ERROR ab. Wieder auf 122, der Speicher wird
# stattdessen ueber KV_CACHE_MEM begrenzt (siehe ki-start).
LIMIT_BYTES=$((122 * 1000 * 1000 * 1000))
LOG_TAG="llm-memory-guard"

mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_available_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
used_bytes=$(( (mem_total_kb - mem_available_kb) * 1024 ))

if (( used_bytes < LIMIT_BYTES )); then
    exit 0
fi

exec 9>/run/llm-memory-guard.lock
flock -n 9 || exit 0

used_gb=$(awk -v b="$used_bytes" 'BEGIN {printf "%.2f", b/1000000000}')
printf '%s RAM-Schwelle erreicht: %s GB belegt (Grenze 122 GB); stoppe LLM-Server\n' "$(date -Is)" "$used_gb" | systemd-cat -t "$LOG_TAG" -p warning

# Containerisierte Modellserver stoppen.
if command -v docker >/dev/null 2>&1; then
    docker ps --format '{{.ID}} {{.Image}} {{.Names}}' \
      | awk 'BEGIN{IGNORECASE=1} /vllm|ollama|llama|text-generation|sglang/ {print $1}' \
      | while read -r cid; do
          [ -n "$cid" ] && docker stop --time 30 "$cid" >/dev/null 2>&1 || true
        done
fi

# Native Modellserver stoppen, aber nicht den Watchdog selbst.
for pid in $(pgrep -f '(^|/)(vllm|ollama|llama-server|text-generation-launcher|sglang)( |$)' 2>/dev/null || true); do
    [ "$pid" = "$$" ] && continue
    kill -TERM "$pid" 2>/dev/null || true
done

sleep 5
for pid in $(pgrep -f '(^|/)(vllm|ollama|llama-server|text-generation-launcher|sglang)( |$)' 2>/dev/null || true); do
    [ "$pid" = "$$" ] && continue
    kill -KILL "$pid" 2>/dev/null || true
done

printf '%s LLM-Server wurden wegen hoher Speichernutzung gestoppt\n' "$(date -Is)" | systemd-cat -t "$LOG_TAG" -p warning
