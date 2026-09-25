#!/usr/bin/env bash
# SGLang-Challenger 25.09.2026 - ABAB-Messung GOLD1 -> SGL1 -> GOLD2 -> SGL2, danach Restore GoldVllm (PLAN.md §4).
# Voraussetzung: Bring-up bestanden, llm-server gestoppt, kein GPU-Prozess.
# Waehrend der Messung ruhen hermes-gateway (Nutzer) und onedrive-sync.timer; beide kommen am Ende zurueck.
# llm-memory-guard und llm-recovery bleiben unveraendert aktiv (bench-* blockiert die Recovery, siehe PLAN.md §3).
set -uo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"; NR="$(dirname "$HIER")"; M="$NR/measurements"; J="$NR/JOURNAL.md"
L0=; L=~/gx10-sglang-0925/abab; mkdir -p "$L"
DV=/home/justin/gx10-nightrun/draftvocab/draft_vocab_de_65536.npy     # SHA-gleich zu /opt/gx10/draftvocab (C_de)
log(){ echo "$(date +%T) $*" | tee -a "$L/challenger.log"; }
jour(){ echo "- $(date +%T) $*" >> "$J"; }
T0=$(date +%s)

systemctl --user stop hermes-gateway onedrive-sync.timer
jour "ABAB-Start: hermes-gateway gestoppt, onedrive-sync.timer pausiert, Waechter + Recovery aktiv"
zurueck(){ systemctl --user start hermes-gateway onedrive-sync.timer; }
trap zurueck EXIT

ABBRUCH=""
lauf(){  # label skript [args]
  local label="$1" skript="$2"; shift 2
  [ -n "$ABBRUCH" ] && { log "uebersprungen $label"; return 90; }
  log "=== $label ($skript $*)"
  ( while [ ! -e "$L/$label.health.stop" ]; do echo "$(date +%s),$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8001/health)"; sleep 30; done ) > "$M/$label.health.csv" &
  local HP=$!
  bash "$HIER/$skript" "$label" "$@" > "$L/$label.konsole.log" 2>&1; local rc=$?
  touch "$L/$label.health.stop"; wait $HP 2>/dev/null
  jour "Lauf \`$label\` rc=$rc"
  local LL=~/gx10-sglang-0925/$label
  if [ -s "$LL/ereignisse.log" ]; then ABBRUCH="Waechter bei $label: $(head -1 "$LL/ereignisse.log")"
  elif [ "$(journalctl -t llm-memory-guard --since "@$T0" --no-pager -o cat | grep -c Schwelle)" -gt 0 ]; then ABBRUCH="llm-memory-guard"
  elif [ "$(journalctl -k --since "@$T0" --no-pager | grep -c 'NVRM: Xid')" -gt 0 ]; then ABBRUCH="Xid"
  elif [ "$(journalctl -k --since "@$T0" --no-pager | grep -ciE 'oom-kill|Killed process')" -gt 0 ]; then ABBRUCH="Linux-OOM-Kill"
  elif grep -qiE 'CUDA error|out of memory.*CUDA|illegal memory access|EngineDeadError|EngineCore.*(died|failed)|Traceback' "$LL/container.log" 2>/dev/null; then ABBRUCH="CUDA-/Engine-Fehler im Log ($label)"
  elif [ $rc -ne 0 ]; then ABBRUCH="$label rc=$rc"; fi
  [ -n "$ABBRUCH" ] && { log "ABBRUCH: $ABBRUCH"; jour "**ABBRUCH**: $ABBRUCH - keine weiteren Laeufe"; }
  return $rc
}
lauf GOLD1 kandidat.sh gx10-vllm:goldvllm "DRAFT_VOCAB=$DV"
lauf SGL1  kandidat_sglang.sh
lauf GOLD2 kandidat.sh gx10-vllm:goldvllm "DRAFT_VOCAB=$DV"
lauf SGL2  kandidat_sglang.sh
if [ -z "$ABBRUCH" ]; then
  python3 "$HIER/entscheide.py" paar GOLD1 SGL1 GOLD2 SGL2 > "$M/entscheidung.json" 2>&1; jour "entscheide.py paar rc=$?"
else
  echo "{\"abbruch\": \"$ABBRUCH\"}" > "$M/entscheidung.json"
fi

# Rueckweg: erster echter Restore-Test von GoldVllm (Zeit gemessen)
# Hermes/OneDrive VOR dem Restore zurueck - sonst meldet verify-goldvllm.sh "hermes-gateway aktiv" als Drift (Fehler vom 25.09.)
zurueck
log "Restore GoldVllm"; t=$(date +%s)
bash /opt/gx10/bin/restore-goldvllm.sh --ausfuehren > "$M/restore_goldvllm.txt" 2>&1; rrc=$?
echo "{\"restore_rc\": $rrc, \"restore_s\": $(( $(date +%s) - t ))}" > "$M/restore_zeit.json"
jour "restore-goldvllm.sh --ausfuehren rc=$rrc nach $(( $(date +%s) - t )) s: $(tail -1 "$M/restore_goldvllm.txt")"
log "fertig"
