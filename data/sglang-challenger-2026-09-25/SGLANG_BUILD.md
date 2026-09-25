# SGLang — Build und Bring-up

**Es wurde nichts selbst gebaut.** Verwendet wurde das fertige Image, auf dem das offizielle SGLang-Cookbook die
Zelle für 1× DGX Spark verifiziert hat. Quellen und Herleitung stehen in [PLAN.md](PLAN.md) §1.

| | |
|---|---|
| Image | `lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06` (arm64 von `dev-qwen38-next-local`, 2026-09-07), lokal getaggt als `gx10-sglang:dev-qwen38-4ccff141` |
| Pull | 5 min 8 s, 14.4 GB, bei laufender Produktion (keine GPU-Nutzung) |
| SGLang | `0.0.0.dev1+g4ccff141d`, Commit `4ccff141dbe992794f9da6c3aa23535b4f72000d` („[Kernel] Wait for the PDL dependency before loading the router bias (Triton + radix) (#38290)“) = Branch `qwen4-main-squashed`, genau der Stand der Cookbook-Verifikation |
| Stack im Image | torch `2.13.0+cu130`, CUDA 13.0 |
| Patches | keine |
| Flags | alle Rezept-Flags per `--help` vorhanden. `--tp` heisst `--tp-size` (gleicher Wert 1). Tool-Parser `qwen3_coder` vorhanden |
| Startskript | `scripts/kandidat_sglang.sh` (Messläufe) bzw. dasselbe mit `PORT=8000 KEYFILE=… BEHALTEN=1 NUR_START=1` (Bring-up) |
| Rückfalloption v0.5.20 | nicht gebraucht |

## Startargumente (identisch in allen SGLang-Läufen)

Cookbook-Zelle `dgx-spark / nvfp4 / single / low-latency` plus die für Ben nötigen Zusätze (`--served-model-name`,
`--tool-call-parser qwen3_coder`, `--api-key`, `--enable-metrics`):

```
python3 -m sglang.launch_server --model-path /hf/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/7b719225…
  --served-model-name qwen3.8-flash-next --tp-size 1 --quantization modelopt_fp4 --fp4-gemm-backend flashinfer_cutlass
  --page-size 64 --chunked-prefill-size 4096 --context-length 262144
  --speculative-algorithm NEXTN --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4
  --max-running-requests 8 --max-mamba-cache-size 40 --mem-fraction-static 0.85
  --ple-offload-embedding --ple-offload-backend file --ple-offload-dir /ple
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder --api-key <KEY> --enable-metrics --host 0.0.0.0 --port 8000
```

Docker: `--gpus all --ipc=host --shm-size 16g --restart no`, `/hf` **read-only**, `/ple` = `~/gx10-sglang-0925/ple` (vor jedem Start geleert).
Das GoldVllm-Image, das Modell und das Backup blieben unberührt. Das Modell war die ganze Zeit schreibgeschützt eingehängt.

## Bring-up (12:37–12:55)

| Schritt | Ergebnis |
|---|---|
| Laden | Hauptgewichte 497.7 s (80.0 GB), MTP-Kopf 84.6 s (4.8 GB) |
| Bereit | **672 s** nach Start (GoldVllm: 852–902 s) |
| KV-Pool | **114'944 Tokens** (in den Messläufen 109'056 und 126'976, je nach freiem Speicher beim Start). GoldVllm: 424'354 |
| MemAvailable bereit | 18.2–18.7 GiB, Swap 7.4 GB |
| Log | „The server is fired up and ready to roll!“, 0 Tracebacks, 0 CUDA-Fehler. Hinweis „Breakable CUDA graph is incompatible with multimodal model; disabling prefill CUDA graph“ (Info, im Rezept so vorgesehen) |
| Gates K1/K2/K3/K5 | 12/12, 6/6, 2/2 (30k/81k), OK |
| K4 | drei Antworten bei Temperatur 0 **nicht identisch** (ab Zeichen 63, alle inhaltlich korrekt, kein Kollaps). Nachtest: Rechnung 5× exakt gleich. → K4 in K4a (hart) / K4b (Befund) geteilt, siehe JOURNAL.md |
| **K6 echter Ben** | `hermes -z` 17×23 → **391** (27 s), Terminal-Tool `cat /etc/hostname` → **gx10** (5 s) |
| K7 | 0 Xid, 0 OOM, 0 Wächter-Eingriffe |

Ergebnis: **SGLang ist auf diesem GX10 mit unserem Checkpoint ohne eigene Patches funktionsfähig**, einschliesslich Ben und Tool-Calling.
Damit war der Performance-Vergleich laut Auftrag durchzuführen.
