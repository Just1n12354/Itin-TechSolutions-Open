# SGLang vs. GoldVllm on one GB10 (25 Sep 2026)

A one-shot, pre-registered, paired comparison on the same box, with the same model (`RadixArk/Qwen3.8-Flash-Next-NVFP4` @ `7b719225…`),
the same prompts and the same kit. Full protocol, raw data and journal (German): `data/sglang-challenger-2026-09-25/`.

## Verdict: vLLM (GoldVllm) wins, SGLang rejected

| | GoldVllm (vLLM 0.29) | SGLang | Δ |
|---|---:|---:|---:|
| G30 (30 agent steps) | 61.7 s | 56.1 s | −9 % |
| Agent 30k | 28.4 s | 25.6 s | −10 % |
| Agent 80k | 48.4 s | 60.9 s (74.1 / 47.6) | +26 % |
| TTFT cold 30k / 80k | 13.0 / 35.6 s | 14.6 / 46.4 s | +13 / +31 % |
| TTFT with prefix hit, 80k | 1.66 s | 0.58 s | −65 % |
| TTUA median / p95 | 1.47 / 1.78 s | 1.28 / 1.72 s | −13 / −3 % |
| decode | 27.4 tok/s | 23.0 tok/s | −16 % |
| **E2E (G30, agent 30k/80k)** | | pair 1 −11.2 %, pair 2 +9.8 % | **−0.7 %** |
| quality / tool calling | 12/12 / 1.0 | 12/12 / 1.0 | equal |
| repeatable at temperature 0 | identical | **not identical** | |
| max input | 262k | **109–127k** (per boot) | |
| cold start to ready | 852–902 s | 671–682 s | SGLang faster |
| Xid / OOM / engine errors | 0 | 0 | equal |

The rule, fixed in advance: SGLang had to win by ≥ 5 % on average and ≥ 3 % in both pairs, with no TTFT/TTUA regression. It did neither.

## Three findings to know before switching

1. **Hard, silent input limit.** With MTP, SGLang on one Spark only accepts as many tokens as fit into its KV pool: 109,056 / 114,944 / 126,976
   in three boots, depending on free memory at start. Larger requests are rejected
   (`Input length (115676 tokens) exceeds the maximum allowed length (109050 tokens)`), and **the client gets an empty stream, no error**.
   An agent that compacts at 131k would silently receive empty answers.
2. **Not deterministic at temperature 0.** The same request three times gave three different but correct texts (diverging at character 63).
   Exact arithmetic stayed identical.
3. **Every start rewrites the PLE table**: 48 GB to NVMe, with memory pressure up to PSI 50 while loading. Delete the old file first,
   otherwise the boot takes ~55 instead of ~11 min.

Also open upstream, and not part of this test: #40948 (QSA graph crash after ~24 h requiring a hard reboot on GB10) and #37326 (MTP acceptance decaying over uptime).

## Reproduce

Recipe: official SGLang cookbook, cell `dgx-spark / nvfp4 / single / low-latency` (`verified: true`, verified on `qwen4-main-squashed@4ccff141db`,
[`docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx@v0.5.20`](https://github.com/sgl-project/sglang/blob/v0.5.20/docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx)),
plus what an agent needs (model name, tool parser, API key).

```bash
docker pull lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06   # arm64 of dev-qwen38-next-local, 14.4 GB
mkdir -p ~/sglang-ple && rm -rf ~/sglang-ple/*
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
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder --api-key "$(cat ~/.config/vllm.key)" --enable-metrics --host 0.0.0.0 --port 8000
```

- Never next to vLLM: stop the other engine first.
- The cookbook writes `--tp 1`; in the image the flag is `--tp-size`.
- The log line `max_total_num_tokens=…` shows this boot's maximum input length.
- The NVIDIA image `nvcr.io/nvidia/sglang:26.08-py3` does not know this model (#39497).
- The alternative `lmsysorg/sglang:v0.5.20-cu130` (arm64 `sha256:b0d8718a…`) was not tested here.
