# SGLang für Qwen3.8-Flash-Next auf 1× GB10 starten

Dies ist der Pfad aus dem **offiziellen SGLang-Cookbook**
([`docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx@v0.5.20`](https://github.com/sgl-project/sglang/blob/v0.5.20/docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx),
Zelle `dgx-spark / nvfp4 / single / low-latency`, dort `verified: true`, verifiziert am 2026-09-06 auf `qwen4-main-squashed@4ccff141db`).
Ergänzt sind nur die Parameter, die ein Agent braucht: Modellname, Tool-Parser, API-Key.

## 1 Image (per Digest, nicht per Tag)

```bash
docker pull lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06   # arm64, 14.4 GB
docker run --rm --entrypoint python3 lmsysorg/sglang@sha256:a1e17bbf… -c "import sglang;print(sglang.__version__)"   # 0.0.0.dev1+g4ccff141d
```

Das ist `lmsysorg/sglang:dev-qwen38-next-local` vom 2026-09-07. Es enthält den PDL-Router-Fix gegen den MTP-„!!!!“-Kollaps auf GB10 (#38290).
Die Alternative `lmsysorg/sglang:v0.5.20-cu130` (arm64 `sha256:b0d8718a…`, enthält PR #39126) ist für Spark nicht ausdrücklich verifiziert
und hier nicht getestet.
Das NVIDIA-Image `nvcr.io/nvidia/sglang:26.08-py3` kennt das Modell nicht (#39497).

## 2 Modell

Dasselbe wie bei GoldVllm: `hf download RadixArk/Qwen3.8-Flash-Next-NVFP4 --revision 7b719225242aacd3dbd3f9407468c2ee9a9d2594`.
Ohne Konvertierung. **Read-only einhängen.**

## 3 Starten

```bash
mkdir -p ~/sglang-ple && rm -rf ~/sglang-ple/*      # PLE-Tabelle wird bei jedem Start neu geschrieben (48 GB)
KEY=$(cat ~/.config/vllm.key)
docker run -d --name sglang-qwen38 --restart no --gpus all --ipc=host --shm-size 16g -p 127.0.0.1:8000:8000 \
  -v ~/.cache/huggingface:/hf:ro -v ~/sglang-ple:/ple -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
  --entrypoint python3 lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06 \
  -m sglang.launch_server \
  --model-path /hf/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/7b719225242aacd3dbd3f9407468c2ee9a9d2594 \
  --served-model-name qwen3.8-flash-next --tp-size 1 --quantization modelopt_fp4 --fp4-gemm-backend flashinfer_cutlass \
  --page-size 64 --chunked-prefill-size 4096 --context-length 262144 \
  --speculative-algorithm NEXTN --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4 \
  --max-running-requests 8 --max-mamba-cache-size 40 --mem-fraction-static 0.85 \
  --ple-offload-embedding --ple-offload-backend file --ple-offload-dir /ple \
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder --api-key "$KEY" --enable-metrics --host 0.0.0.0 --port 8000
docker logs -f sglang-qwen38    # "The server is fired up and ready to roll!" nach ~11 min
```

Das Cookbook schreibt `--tp 1`, im Image heisst das Flag `--tp-size`. Der Wert ist derselbe.
Im Log steht, wie gross der Pool geworden ist: `max_total_num_tokens=…`. **Das ist die maximale Eingabelänge dieses Starts.**

## 4 Nicht auf /health verlassen

```bash
cd ../bench
VLLM_API_KEY=$KEY KORPUS_DIR=/pfad/zu/txt python3 gates.py --url http://127.0.0.1:8000 --label sglang --ausgabe gates.json
```

Erwartet: K1 12/12, K2 6/6, K3 2/2, K5 OK. K4 meldet bei SGLang „nicht identisch“. Das ist der Nichtdeterminismus, kein Kollaps.

## 5 Nie neben vLLM

Beide Engines zusammen passen nicht in 128 GB. Vorher die andere Engine stoppen und prüfen, dass `nvidia-smi --query-compute-apps=pid --format=csv,noheader`
leer ist. Auf dem gx10 hiess der Testcontainer `bench-*`. Damit blockiert er die automatische Recovery von vLLM, während der RAM-Wächter
ihn trotzdem stoppt (Name/Image enthält `sglang`).

## 6 Wie gemessen wurde

`../data/sglang-challenger-2026-09-25/`:
- `PLAN.md` (Quellen, Gates, Entscheidungsregel vorab festgelegt)
- `scripts/` (`kandidat_sglang.sh`, `challenger.sh` für ABAB)
- `measurements/` (JSON/CSV aller Läufe), `logs/`
- `COMPARISON.md`, `FINAL_REPORT.md`, `JOURNAL.md` (mit allen Abweichungen und eigenen Fehlern)
