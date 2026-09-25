#!/bin/bash
# llm-recovery.sh - bringt vLLM (Produktion) zurueck, NACHDEM llm-memory-guard es gestoppt hat.
#
# Warum: llm-memory-guard.sh stoppt bei Speichernot alle LLM-Container. llm-server.service ist
# oneshot + RemainAfterExit=yes, Restart=on-failure greift deshalb nicht, der Container hat
# --restart no. Ohne diesen Dienst bleibt das Modell nach einem Waechter-Eingriff dauerhaft weg.
#
# Konfiguration: /etc/default/llm-recovery (Vorlage: llm-recovery.default), wird vom
# llm-recovery.service als EnvironmentFile gelesen. Pflicht ist nur LLMR_KEYFILE.
#
# Grundsatz: Der Waechter selbst bleibt unveraendert. Dieses Skript handelt NUR, wenn
#   1. im Journal ein Stopp-Ereignis von llm-memory-guard steht, das noch nicht behandelt ist,
#   2. der Produktionscontainer qwen38-flash NICHT laeuft,
#   3. kein Start/Test gerade laeuft (llm-server activating, LLMR_BUSY_PATTERN, Container bench-*),
#   4. der Speicher sich stabil erholt hat (RECOVER_MIN_MIB, STABLE_RUNS Laeufe in Folge),
#   5. die GPU gesund ist (nvidia-smi antwortet, keine neue Xid seit dem Ereignis),
#   6. das Versuchsbudget nicht aufgebraucht ist (MAX_ATTEMPTS je WINDOW_S, COOLDOWN_S).
# Nach MAX_ATTEMPTS Fehlschlaegen: Zustand FAILED, keine weiteren Versuche bis --reset.
# Zustaende: NORMAL -> WARNING (nur Log) -> STOPPED (Waechter) -> WAIT_MEM -> RECOVERING -> NORMAL | FAILED
#
# Aufruf:  llm-recovery.sh            ein Lauf (vom Timer, alle 60 s)
#          llm-recovery.sh --status   Zustand anzeigen
#          llm-recovery.sh --reset    FAILED quittieren, Versuchszaehler leeren
# Stilllegen ohne Deinstallation: touch /etc/llm-recovery.disabled
# Testmodus (keine Aktion, fremdes Zustandsverzeichnis): LLMR_SIMULATE=1 + SIM_*-Variablen (SIM_NOW, SIM_MEMAVAIL,
#   SIM_EVENT_TS, SIM_RUNNING, SIM_BUSY, SIM_XID, SIM_GPU_OK, SIM_RESTART_OK, SIM_HEALTH_OK) und LLMR_STATE_DIR
set -u

LOG_TAG="llm-recovery"
STATE_DIR="${LLMR_STATE_DIR:-/var/lib/llm-recovery}"
DISABLE_FILE="${LLMR_DISABLE_FILE:-/etc/llm-recovery.disabled}"
PROD="${LLMR_CONTAINER:-qwen38-flash}"
UNIT="${LLMR_UNIT:-llm-server.service}"
URL="${LLMR_URL:-http://127.0.0.1:8000}"
KEYFILE="${LLMR_KEYFILE:-}"                         # Pflicht: API-Key-Datei, z. B. /home/<nutzer>/.config/vllm.key
# Optional: zusaetzliche Pruefung nach dem Neustart, z. B. bench/gates.py. Exit 0 = gesund.
# Laeuft als LLMR_HEALTH_USER (leer = root). XDG_RUNTIME_DIR wird gesetzt, sonst scheitert dort
# jedes "systemctl --user" mit "Failed to connect to bus" und ein gesundes vLLM gilt als krank.
HEALTH_CMD="${LLMR_HEALTH_CMD:-}"
HEALTH_USER="${LLMR_HEALTH_USER:-}"
# Prozesse, waehrend derer die Recovery nicht eingreift (eigene Start-/Rollback-Skripte), als pgrep -f-Muster
BUSY_PATTERN="${LLMR_BUSY_PATTERN:-[r]un-goldvllm.sh}"

WATCHDOG_MIB=8259          # Grenze von llm-memory-guard (122 GB belegt) als MemAvailable
WARN_MIB=10307             # WARNING-Log unter Watchdog + 2 GiB
# Bedarf im Betrieb, gemessen auf dem Referenzgeraet am 24.09.2026: GPU 97'384 MiB + Host-RSS (EngineCore + API)
# 6'215 MiB = 103'599 MiB. Schwelle = Bedarf + Watchdog-Grenze + 2 GiB = ~113'900 MiB.
# Normalzustand ohne vLLM waere ~116'300 MiB. Liegt MemAvailable darunter, ist der Verursacher noch da.
RECOVER_MIN_MIB="${LLMR_RECOVER_MIN_MIB:-114000}"
STABLE_RUNS=3              # so viele Timer-Laeufe in Folge ueber RECOVER_MIN_MIB
COOLDOWN_S=600             # frueheste Recovery 10 min nach dem Ereignis bzw. dem letzten Versuch
MAX_ATTEMPTS=2             # je WINDOW_S
WINDOW_S=21600             # 6 h
EVENT_MAX_AGE_S=7200       # aeltere Ereignisse nicht mehr automatisch behandeln

SIM="${LLMR_SIMULATE:-0}"
mkdir -p "$STATE_DIR"

log(){ # $1 Prioritaet, Rest Text
  local p="$1"; shift
  if [ "$SIM" = 1 ]; then echo "[$p] $*"; else printf '%s\n' "$*" | systemd-cat -t "$LOG_TAG" -p "$p"; fi
}
now(){ echo "${SIM_NOW:-$(date +%s)}"; }
rd(){ cat "$STATE_DIR/$1" 2>/dev/null || echo "${2:-}"; }
wr(){ echo "$2" > "$STATE_DIR/$1"; }

mem_avail_mib(){
  [ -n "${SIM_MEMAVAIL:-}" ] && { echo "$SIM_MEMAVAIL"; return; }
  awk '/^MemAvailable:/{printf "%d", $2/1024}' /proc/meminfo
}
last_guard_stop(){ # Epoche des letzten Stopp-Ereignisses (0 = keins)
  [ -n "${SIM_EVENT_TS:-}" ] && { echo "$SIM_EVENT_TS"; return; }
  journalctl -t llm-memory-guard -b -o short-unix --no-pager 2>/dev/null \
    | awk '/wegen hoher Speichernutzung gestoppt/{t=int($1)} END{print t+0}'
}
container_running(){
  [ -n "${SIM_RUNNING:-}" ] && { [ "$SIM_RUNNING" = 1 ]; return; }
  [ "$(docker inspect -f '{{.State.Running}}' "$PROD" 2>/dev/null)" = "true" ]
}
busy(){ # laeuft gerade ein Start, Rollback oder Test?
  [ -n "${SIM_BUSY:-}" ] && { [ "$SIM_BUSY" = 1 ]; return; }
  [ "$(systemctl is-active "$UNIT")" = "activating" ] && return 0
  [ -n "$BUSY_PATTERN" ] && pgrep -f "$BUSY_PATTERN" >/dev/null && return 0
  docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^bench-' && return 0
  return 1
}
xid_since(){ # Anzahl Xid-Meldungen seit Epoche $1
  [ -n "${SIM_XID:-}" ] && { echo "$SIM_XID"; return; }
  journalctl -k -b --since "@$1" --no-pager 2>/dev/null | grep -c 'NVRM: Xid'
}
gpu_ok(){
  [ -n "${SIM_GPU_OK:-}" ] && { [ "$SIM_GPU_OK" = 1 ]; return; }
  timeout 20 nvidia-smi -L >/dev/null 2>&1
}
do_restart(){
  if [ "$SIM" = 1 ]; then echo "[SIM] systemctl restart $UNIT"; [ "${SIM_RESTART_OK:-1}" = 1 ]; return; fi
  systemctl reset-failed "$UNIT" 2>/dev/null
  systemctl restart "$UNIT"      # blockiert bis bereit (ExecStartPost wartet auf /v1/models), max. 40 min
}
health_ok(){
  if [ "$SIM" = 1 ]; then [ "${SIM_HEALTH_OK:-1}" = 1 ]; return; fi
  local k c uid
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$URL/health") || return 1
  [ "$c" = 200 ] || { log err "Healthcheck /health = $c"; return 1; }
  k=$(tr -d '\n' < "$KEYFILE")
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Authorization: Bearer $k" "$URL/v1/models")
  [ "$c" = 200 ] || { log err "Healthcheck /v1/models = $c"; return 1; }
  [ -z "$HEALTH_CMD" ] && return 0
  if [ -n "$HEALTH_USER" ]; then
    uid=$(id -u "$HEALTH_USER") || { log err "LLMR_HEALTH_USER $HEALTH_USER unbekannt"; return 1; }
    sudo -u "$HEALTH_USER" env XDG_RUNTIME_DIR="/run/user/$uid" sh -c "$HEALTH_CMD" >/dev/null 2>&1
  else
    sh -c "$HEALTH_CMD" >/dev/null 2>&1
  fi || { log err "LLMR_HEALTH_CMD meldet Fehler: $HEALTH_CMD"; return 1; }
  return 0
}

case "${1:-}" in
  --status)
    echo "Zustand:        $(rd state NORMAL)"
    echo "Ereignis erledigt bis: $(rd handled_event 0)"
    echo "Versuche:       $(rd attempts '')"
    echo "Stabil-Zaehler: $(rd stable 0)"
    echo "MemAvailable:   $(mem_avail_mib) MiB (Watchdog $WATCHDOG_MIB, Recovery ab $RECOVER_MIN_MIB)"
    [ -e "$DISABLE_FILE" ] && echo "STILLGELEGT durch $DISABLE_FILE"
    exit 0;;
  --reset)
    wr state NORMAL; wr attempts ""; wr stable 0; wr handled_event "$(last_guard_stop)"
    log notice "Zustand manuell zurueckgesetzt"; exit 0;;
esac

[ -e "$DISABLE_FILE" ] && exit 0
if [ "$SIM" != 1 ] && [ ! -r "$KEYFILE" ]; then
  log err "LLMR_KEYFILE nicht gesetzt oder nicht lesbar ('$KEYFILE') - Recovery inaktiv, siehe /etc/default/llm-recovery"
  exit 0
fi
exec 9>"$STATE_DIR/lock"; flock -n 9 || exit 0

T=$(now); MEM=$(mem_avail_mib); STATE=$(rd state NORMAL)

# WARNING: nur protokollieren, hoechstens alle 5 min
if [ "$MEM" -lt "$WARN_MIB" ] && container_running; then
  if [ $((T - $(rd last_warn 0))) -ge 300 ]; then
    log warning "WARNING: MemAvailable $MEM MiB, Watchdog-Grenze $WATCHDOG_MIB MiB (Abstand $((MEM - WATCHDOG_MIB)) MiB)"
    wr last_warn "$T"
  fi
fi

EV=$(last_guard_stop); HANDLED=$(rd handled_event 0)
if [ "$EV" -le "$HANDLED" ]; then
  [ "$STATE" != NORMAL ] && [ "$STATE" != FAILED ] && container_running && wr state NORMAL
  exit 0
fi
# ab hier: unbehandeltes Waechter-Ereignis
[ "$STATE" = FAILED ] && exit 0
if container_running; then  # jemand hat schon neu gestartet
  log notice "Waechter-Ereignis $EV, Container laeuft bereits wieder - nichts zu tun"
  wr handled_event "$EV"; wr state NORMAL; wr stable 0; exit 0
fi
if [ $((T - EV)) -gt "$EVENT_MAX_AGE_S" ]; then
  log warning "Waechter-Ereignis $EV aelter als $EVENT_MAX_AGE_S s - keine automatische Recovery, bitte manuell pruefen"
  wr handled_event "$EV"; wr state NORMAL; exit 0
fi
[ "$STATE" = NORMAL ] && { log warning "STOPPED: Waechter hat vLLM gestoppt (Ereignis $EV), warte auf Speichererholung"; wr state WAIT_MEM; wr stable 0; }
busy && { log info "Start/Rollback/Test laeuft - warte"; exit 0; }

if [ "$MEM" -lt "$RECOVER_MIN_MIB" ]; then
  wr stable 0
  if [ $((T - $(rd last_memlog 0))) -ge 300 ]; then
    log warning "WAIT_MEM: MemAvailable $MEM MiB < $RECOVER_MIN_MIB MiB - Verursacher belegt noch Speicher, kein Neustart"
    wr last_memlog "$T"
  fi
  exit 0
fi
S=$(( $(rd stable 0) + 1 )); wr stable "$S"
[ "$S" -lt "$STABLE_RUNS" ] && exit 0

LAST_TRY=$(rd last_try 0)
[ $((T - EV)) -lt "$COOLDOWN_S" ] && exit 0
[ $((T - LAST_TRY)) -lt "$COOLDOWN_S" ] && exit 0

# Versuchsbudget im Fenster
ATT=""; for a in $(rd attempts ""); do [ $((T - a)) -lt "$WINDOW_S" ] && ATT="$ATT $a"; done
N=$(echo $ATT | wc -w)
if [ "$N" -ge "$MAX_ATTEMPTS" ]; then
  log err "FAILED: $N Recovery-Versuche in $((WINDOW_S/3600)) h erfolglos - keine weiteren Versuche. Quittieren: llm-recovery.sh --reset"
  wr state FAILED; exit 0
fi

X=$(xid_since "$EV")
if [ "$X" -gt 0 ]; then
  log err "FAILED: $X Xid-Meldung(en) seit dem Waechter-Ereignis - GPU-Zustand unklar, kein automatischer Neustart"
  wr state FAILED; exit 0
fi
gpu_ok || { log err "FAILED: nvidia-smi antwortet nicht - kein automatischer Neustart"; wr state FAILED; exit 0; }

wr attempts "$ATT $T"; wr last_try "$T"; wr state RECOVERING
log warning "RECOVERING: Versuch $((N+1))/$MAX_ATTEMPTS, MemAvailable $MEM MiB, starte $UNIT neu (ca. 15 min)"
if do_restart && health_ok; then
  log notice "NORMAL: Recovery erfolgreich, vLLM gesund (MemAvailable $(mem_avail_mib) MiB)"
  wr handled_event "$EV"; wr state NORMAL; wr stable 0
else
  log err "Recovery-Versuch $((N+1)) fehlgeschlagen"
  wr state WAIT_MEM; wr stable 0
fi
exit 0
