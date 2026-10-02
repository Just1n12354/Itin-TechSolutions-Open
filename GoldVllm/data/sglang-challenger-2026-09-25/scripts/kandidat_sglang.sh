#!/usr/bin/env bash
# SGLang-Challenger 25.09.2026: Kopie von kandidat.sh. Gatter, Sampler, Normalisierung und Messschritte UNVERAENDERT;
# nur der Start ist SGLang (Cookbook-Zelle dgx-spark/nvfp4/single/low-latency, siehe PLAN.md §2).
#   kandidat_sglang.sh <label>        Messlauf auf 127.0.0.1:8001
#   PORT=8000 KEYFILE=~/.config/qwen-vllm/api-key BEHALTEN=1 NUR_START=1 kandidat_sglang.sh SGL_BRINGUP   (Bring-up fuer Ben)
# Urspruenglicher Kopf von kandidat.sh:
# Startet, misst und entfernt EINEN Kandidaten - seriell, nie neben einer zweiten Engine.
# NACHTLAUF 24./25.09.2026: Kopie von NIGHT_RUN_2026-09-21/scripts/kandidat.sh. Serve-Argumente UNVERAENDERT.
# Ergaenzt: Logs nach ~/gx10-cde-0925, PSI-Sampler, PLE-Probe (kalt/warm), PLE-Statistik + Start-Timeline aus dem Log.
# FAST_ROWS: EXTRA_ENV="-e VLLM_PLE_MMAP_FAST_ROWS=0" (ohne = Image-Default 512).
# Qualifikation: PORT=8000 KEYFILE=~/.config/qwen-vllm/api-key BEHALTEN=1 NUR_START=1 -> Container bleibt stehen
#   (Hermes/Ben/xiaozhi landen darauf), nachtlauf.sh entfernt ihn am Ende.
#
#   kandidat.sh <label> <image> [ENV=wert ...]
#   z. B. kandidat.sh B_v029_mtp2 gx10-vllm:b-v0290-d542745 MTP=2 DRAFT_VOCAB=0
#
# Steuerbare Variablen (Standard = A-Werte):
#   MTP=2  KV=12884901888  CTX=262144  SEQS=16  DRAFT_VOCAB=0  DET_TOPK=0  BASE=v0.29|preview
#   EXTRA_ARGS=""  EXTRA_ENV=""  (zusaetzliche vllm-Argumente / "-e X=Y ..." fuer Einzelexperimente)
# Serve-Argumente = scripts/serve.sh von A (gleiche Reihenfolge). Abweichungen nach aussen:
#   Name bench-<label>, Port 127.0.0.1:8001, --restart no, /hf read-only, kein /nas_models,
#   eigener Einweg-Key (~/gx10-nightrun/keys, nie ausgegeben), Labels gx10.rolle=test.
# Voraussetzung: A ist gestoppt. Das Skript prueft das und bricht sonst ab.
set -uo pipefail
LABEL="$1"; shift 1
IMAGE=lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06
PLE=/home/justin/gx10-sglang-0925/ple
for kv in "$@"; do export "$kv"; done
MTP="${MTP:-2}"; KV="${KV:-12884901888}"; CTX="${CTX:-262144}"; SEQS="${SEQS:-16}"
DRAFT_VOCAB="${DRAFT_VOCAB:-0}"; DET_TOPK="${DET_TOPK:-0}"
BASE="${BASE:-$(docker image inspect -f '{{index .Config.Labels "qwen38.base"}}' "$IMAGE" 2>/dev/null)}"
EXTRA_ARGS="${EXTRA_ARGS:-}"; EXTRA_ENV="${EXTRA_ENV:-}"
NAME="bench-${LABEL,,}"; NAME="${NAME//_/-}"
HIER="$(cd "$(dirname "$0")" && pwd)"; NR="$(dirname "$HIER")"; DOM="$(cd "$NR/../.." && pwd)"
L=~/gx10-sglang-0925/$LABEL; mkdir -p "$L" ~/gx10-sglang-0925/keys; chmod 700 ~/gx10-sglang-0925/keys
M="$NR/measurements"; C="$NR/configs"
VENV=/home/justin/Dokumente/GitHub/Ragnarok/.venv/bin/python
PORT="${PORT:-8001}"; URL="http://127.0.0.1:$PORT"
log(){ echo "$(date +%T) $*" | tee -a "$L/ablauf.log"; }
maskiere(){ sed -E 's/[0-9a-f]{64}/<KEY>/g'; }

# --- Gatter: keine zweite Engine ---------------------------------------------
if docker ps --format '{{.Names}}' | grep -qx qwen38-flash; then log "ABBRUCH: Produktion laeuft noch"; exit 10; fi
if [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]; then log "ABBRUCH: GPU-Prozess aktiv"; exit 11; fi
ma=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
[ "$ma" -lt 90000 ] && { log "ABBRUCH: nur $ma MiB frei vor dem Start"; exit 12; }
log "Start $LABEL: SGLang image=$IMAGE MemAvailable=${ma}MiB"

# --- Vergleichbarer Speicherzustand: Page-Cache kalt, Swap leer (nur wenn RAM sicher reicht) ---
if [ "${NORMALISIEREN:-1}" = 1 ]; then
  sw=$(free -m | awk 'NR==3{print $3}'); ma=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ $((ma - sw)) -gt 40000 ]; then
    # ab 00:50: KEIN swapoff mehr - es holte kalte Seiten in den RAM zurueck, die der Kernel beim
    # naechsten langen Prefill schubweise wieder auslagerte (Fehlalarm A_ctrl 00:41, FAILURES F5).
    sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
    log "normalisiert: drop_caches (Swap ${sw} MiB bleibt) -> MemAvailable $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) MiB"
  else
    log "NICHT normalisiert: MemAvailable ${ma} MiB, Swap ${sw} MiB"
  fi
fi
echo "{\"pswpin\":$(awk '/^pswpin/{print $2}' /proc/vmstat),\"pswpout\":$(awk '/^pswpout/{print $2}' /proc/vmstat)}" > "$L/vm_start.json"
if [ -n "${KEYFILE:-}" ]; then KEYF="$KEYFILE"; else KEYF=~/gx10-sglang-0925/keys/$NAME.key; ( umask 077; python3 -c 'import secrets;print(secrets.token_hex(32))' > "$KEYF" ); fi
SNAP=/hf/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/7b719225242aacd3dbd3f9407468c2ee9a9d2594
# Cookbook: die PLE-Tabelle wird bei jedem Boot komplett geschrieben, alte Datei vorher loeschen (sonst ~55 statt ~10 min)
mkdir -p "$PLE"; find "$PLE" -mindepth 1 -delete; log "PLE-Verzeichnis geleert: $PLE (frei $(df -h --output=avail "$PLE" | tail -1))"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --restart no --label gx10.llm=1 --label gx10.rolle=test \
  --gpus all --ipc=host --shm-size 16g -p "127.0.0.1:$PORT:8000" \
  -v /home/justin/.cache/huggingface:/hf:ro -v "$PLE:/ple" -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
  --entrypoint python3 "$IMAGE" -m sglang.launch_server \
  --model-path "$SNAP" --served-model-name qwen3.8-flash-next --tp-size 1 \
  --quantization modelopt_fp4 --fp4-gemm-backend flashinfer_cutlass --page-size 64 --chunked-prefill-size 4096 \
  --context-length 262144 --speculative-algorithm NEXTN --speculative-num-steps 3 --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 --max-running-requests 8 --max-mamba-cache-size 40 --mem-fraction-static 0.85 \
  --ple-offload-embedding --ple-offload-backend file --ple-offload-dir /ple \
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder --api-key "$(cat "$KEYF")" --enable-metrics \
  --host 0.0.0.0 --port 8000 > "$L/container.id" 2> "$L/run.err" || { log "docker run fehlgeschlagen: $(maskiere < "$L/run.err" | tail -3)"; exit 13; }
docker inspect "$NAME" | maskiere > "$C/$LABEL.inspect.json"

# --- Sampler/Waechter ab Containerstart ----------------------------------------
rm -f "$L/stop"
python3 "$HIER/sampler.py" --csv "$L/sampler.csv" --ereignisse "$L/ereignisse.log" --stopdatei "$L/stop" --stoppe "$NAME" &
SAMPLER=$!
python3 "$HIER/psi_sampler.py" --csv "$L/psi.csv" --stopdatei "$L/stop" &
PSI=$!
ende(){ touch "$L/stop"; wait $SAMPLER $PSI 2>/dev/null; cp "$L/psi.csv" "$M/$LABEL.psi.csv" 2>/dev/null
  docker logs -t "$NAME" 2>&1 | maskiere > "$L/container.log"
  grep -E "server_args|Load weight end|KV Cache is allocated|max_total_num_tokens|The server is fired up|startup complete|Error|error|Traceback|Xid|out of memory|accept" "$L/container.log" \
    | grep -v Qwen3VLVideoProcessor | cut -c1-400 > "$NR/logs/$LABEL.log.txt"
  if [ "${BEHALTEN:-0}" = 1 ] && [ "${BEREIT:-0}" = 1 ]; then log "BEHALTEN=1: Container $NAME bleibt stehen"; return; fi
  docker rm -f "$NAME" >/dev/null 2>&1; log "Container $NAME entfernt"
  for _ in $(seq 1 30); do [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ] && break; sleep 2; done
  log "nach Entfernen: MemAvailable $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) MiB, GPU-Prozesse: '$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | tr '\n' ' ')'"; }
trap ende EXIT

# --- Bereitschaft -------------------------------------------------------------
t0=$(date +%s); bereit=0
while [ $(( $(date +%s) - t0 )) -lt 2400 ]; do
  st=$(docker inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null)
  [ "$st" != running ] && { log "Container $st: $(docker inspect -f 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' "$NAME" 2>/dev/null)"; break; }
  [ -s "$L/ereignisse.log" ] && { log "Waechter: $(tail -1 "$L/ereignisse.log")"; break; }
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 -H "Authorization: Bearer $(cat "$KEYF")" "$URL/v1/models")" = 200 ] && { bereit=1; break; }
  sleep 10
done
t_bereit=$(( $(date +%s) - t0 ))
if [ $bereit -ne 1 ]; then log "NICHT BEREIT nach ${t_bereit}s"; docker logs --tail 40 "$NAME" 2>&1 | maskiere > "$L/fehler_tail.txt"; exit 20; fi
BEREIT=1
log "bereit nach ${t_bereit}s; $(docker logs "$NAME" 2>&1 | grep -E 'Load weight end|KV Cache is allocated|max_total_num_tokens' | cut -c1-300 | tr '\n' ' ')"
echo "{\"label\":\"$LABEL\",\"time_to_ready_s\":$t_bereit}" > "$M/$LABEL.start.json"
[ "${NUR_START:-0}" = 1 ] && { log "NUR_START gesetzt - keine Messung"; exit 0; }

EC=$(docker inspect -f '{{.State.Pid}}' "$NAME")   # SGLang: Hauptprozess des Containers (Threads per -t)
( LC_ALL=C pidstat -t -p "$EC" 5 > "$L/pidstat_enginecore.txt" 2>&1 ) & PIDSTAT=$!
export VLLM_BASIS_URL="$URL" VLLM_CONTAINER="$NAME"
export VLLM_API_KEY="$(cat "$KEYF")"
# --- Aufwaermen, dann Messung (gleiche Werkzeuge wie fuer A) ------------------
( cd "$DOM/betrieb" && "$VENV" tools/aufwaermen.py --container "$NAME" --hoechstdauer 900 2>&1 | maskiere | tail -4 ) | tee -a "$L/ablauf.log"
[ -s "$L/ereignisse.log" ] && { log "Waechter nach Aufwaermen: $(tail -1 "$L/ereignisse.log")"; exit 21; }
# Korrektheits-Gates K1-K5 (PLAN.md §5) vor jeder Messung - identisch fuer GoldVllm und SGLang
"$VENV" "$HIER/gates.py" --url "$URL" --label "$LABEL" --ausgabe "$M/$LABEL.gates.json" 2>&1 | maskiere | tail -6 | tee -a "$L/ablauf.log"
python3 -c "import json,sys;sys.exit(0 if json.load(open('$M/$LABEL.gates.json'))['ok'] else 1)" || { log "GATES FEHLER - keine Messung"; exit 30; }
( cd "$DOM/betrieb" && BENCH_MAX_SWAP_ZUWACHS_MB=4096 "$VENV" tools/benchmark_gx10.py --nur-schnell --agent-schritte 30 \
    --ausgabe "$M/$LABEL.bench13.json" --ueberschreiben 2>&1 | maskiere | tail -25 ) | tee -a "$L/ablauf.log"
[ -s "$L/ereignisse.log" ] && { log "Waechter nach bench13: $(tail -1 "$L/ereignisse.log")"; exit 22; }
"$VENV" "$HIER/nacht_bench.py" --url "$URL" --label "$LABEL" --ausgabe "$M/$LABEL.nacht.json" 2>&1 | maskiere | tee -a "$L/ablauf.log"
[ -s "$L/ereignisse.log" ] && { log "Waechter nach nacht_bench: $(tail -1 "$L/ereignisse.log")"; exit 23; }
# PLE-Probe: identischer Text 3x (kalt -> warm) + neuer Text (kalt); direkte Messung der PLE-Fault-Kosten
python3 "$HIER/ple_probe.py" "$URL" 2>&1 | maskiere > "$M/$LABEL.ple_probe.txt"; log "PLE-Probe: $(tail -2 "$M/$LABEL.ple_probe.txt" | tr '\n' ' ')"
cp "$L/sampler.csv" "$M/$LABEL.sampler.csv"; cp "$L/ereignisse.log" "$M/$LABEL.ereignisse.log" 2>/dev/null; cp "$L/ereignisse.log.hinweise" "$M/$LABEL.nverr.log" 2>/dev/null
kill $PIDSTAT 2>/dev/null; cp "$L/pidstat_enginecore.txt" "$M/$LABEL.pidstat.txt"
log "Messung $LABEL fertig"
