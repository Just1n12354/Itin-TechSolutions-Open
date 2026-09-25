# GoldVllm — squeezing vLLM on a single NVIDIA GB10 (DGX Spark / ASUS Ascent GX10)

A **measured, reproducible, frozen** vLLM setup for `RadixArk/Qwen3.8-Flash-Next-NVFP4` with the **full 262,144-token context**
on **one** GB10 with 128 GB unified memory, running 24/7 as the local backend of a tool-calling agent.

Everything needed to rebuild it is here: image recipe, the exact launch line, systemd units, a RAM watchdog, correctness gates,
the benchmark kit, and the raw data of every run. Also the method: how we measured, what we changed, what we rejected, and why.

**Give this repo to a human or to an AI assistant.** Humans start with [docs/INSTALL.md](docs/INSTALL.md).
AI agents start with [AI_AGENT_GUIDE.md](AI_AGENT_GUIDE.md), which holds the rules that kept this box stable while tuning it.

> Deutsch: alle Originaldokumente in [`de/`](de/). Anleitungen auf Deutsch (Markdown + PDF): [`Anleitung/Mensch/`](Anleitung/Mensch/)
> für Menschen vom Laien bis zum Admin, [`Anleitung/AI/`](Anleitung/AI/) für KI-Assistenten.

## Results (25 Sep 2026, mean of 2 runs, agent-style workload)

| Metric | GoldVllm |
|---|---:|
| G30: 30 agent steps with tool calls | **61.7 s** |
| Agent run with 30k / 80k tokens of context (4 steps) | 28.4 / 48.4 s |
| Time to first action (TTUA), median / p95 | 1.47 / 1.78 s |
| Time to first token, cold, 30k / 80k / 110k | 13.0 / 35.6 / 52.3 s |
| Time to first token with prefix-cache hit, 30k / 80k | 1.0 / 1.7 s |
| Decode, single stream | 27.4 tok/s |
| Throughput with 1 / 2 / 4 concurrent streams | 23 / 32 / 52 tok/s |
| Quality set (12 tasks: tool calls, math, logic, multi-step, error case, needle) | 12/12 |
| KV cache | 12 GiB fixed = 424,354 tokens |
| Cold start to ready | 14–15 min |
| Xid / OOM / engine errors | 0 / 0 / 0 |

How we got there: [docs/RESULTS.md](docs/RESULTS.md). The levers ranked by measured effect: [docs/LESSONS.md](docs/LESSONS.md).

## What's inside the configuration

| Piece | Value | Measured reason |
|---|---|---|
| Engine | official vLLM **0.29.0** image | vs. the earlier Qwen preview build: cold prefill −32 to −40 % at 30k–116k, agent run at 80k −26 % |
| Patches | [`blazux/qwen3.8-Flash-DGX@d542745`](https://github.com/blazux/qwen3.8-Flash-DGX) (Apache-2.0) | PLE table (48 GB FP8) memory-mapped from NVMe, which is what makes the model fit on one GB10; GB10 fixes for FLA/GDN; FP8 hybrid; MTP backport |
| Model | `RadixArk/Qwen3.8-Flash-Next-NVFP4` @ `7b719225242aacd3dbd3f9407468c2ee9a9d2594` | pinned revision |
| Speculative decoding | MTP, 2 tokens | 1 → agent steps +18 %; 3/4 → decode −12/−16 % |
| Draft vocabulary | custom **German** 65,536-id vocabulary ([draftvocab/](draftvocab/)) | the stock (English-leaning) one drops acceptance on German text 0.70 → 0.59; the German one keeps it: +8 % decode, **+5.1 % end-to-end** (ABAB-confirmed) |
| KV cache | **12 GiB fixed** | 18.7 GiB left ~570 MiB above the RAM watchdog and cost us production once; 12 GiB leaves ≥ 9.3 GiB |

## Quick start

```bash
# 1 image (official Dockerfile of the patch repo, pinned commit; use BuildKit)
git clone https://github.com/blazux/qwen3.8-Flash-DGX.git && cd qwen3.8-Flash-DGX && git checkout d542745
DOCKER_BUILDKIT=1 docker build -f Dockerfile.v0.29 -t gx10-vllm:goldvllm . && cd ..
# 2 model, pinned revision (135 GB)
hf download RadixArk/Qwen3.8-Flash-Next-NVFP4 --revision 7b719225242aacd3dbd3f9407468c2ee9a9d2594
# 3 draft vocabulary + API key
sudo install -D -m 0444 draftvocab/draft_vocab_de_65536.npy /opt/gx10/draftvocab/draft_vocab_de_65536.npy
python3 -c 'import secrets;print(secrets.token_hex(32))' > ~/.config/vllm.key && chmod 600 ~/.config/vllm.key
# 4 start (identical to the production launch line), ready after ~15 min
VOCAB=/opt/gx10/draftvocab/draft_vocab_de_65536.npy KEYFILE=~/.config/vllm.key ./config/run-goldvllm.sh
# 5 verify correctness, not just /health
cd bench && VLLM_API_KEY=$(cat ~/.config/vllm.key) KORPUS_DIR=/path/to/some/txt \
  python3 gates.py --url http://127.0.0.1:8000 --label first --ausgabe gates.json      # -> GATES OK
```

Then install the RAM watchdog before running it 24/7: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Repository map

| Path | Content |
|---|---|
| `AI_AGENT_GUIDE.md` | rules and step order for an AI assistant installing or tuning this on a GB10 |
| `docs/` | INSTALL, CONFIGURATION (every flag and env var, with sources), OPERATIONS, BENCHMARKING, RESULTS, LESSONS, SGLANG |
| `config/` | `run-goldvllm.sh`, systemd units, RAM watchdog, recovery, the `serve.sh` patch |
| `draftvocab/` | the German draft vocabulary (SHA256 `a8647394…`) and how to build your own |
| `build/` | how our image was actually built (1-container transcript of `Dockerfile.v0.29`) |
| `bench/` | benchmark and correctness kit (G30, agent 30k/80k, TTFT, quality set, gates, samplers, ABAB decision) |
| `data/` | raw data: GoldVllm baseline, C_de qualification vs. vLLM 0.29 baseline, SGLang challenger, model manifest |
| `de/` | German originals of the docs |
| `Anleitung/` | German guides as Markdown + PDF: `Mensch/` for humans, `AI/` for AI assistants; `pdf_bauen.py` rebuilds the PDFs |

## SGLang?

Tested head-to-head on the same box on 25 Sep 2026, using the official single-Spark cookbook recipe and no custom patches.
It works, and it is faster on short and warm steps. It is slower on cold long prefill, **−0.7 % end-to-end** overall.
With MTP it only accepts inputs up to the KV pool (109–127k tokens, depending on the boot), and an oversized request comes back
as an **empty stream without an error**. vLLM stays. Details: [docs/SGLANG.md](docs/SGLANG.md).

## Honest limits

- **One device, one workload:** a German-speaking agent with tool calls, low concurrency. Kernel `7.0.0-1019-nvidia`,
  driver 580.178.04, CUDA 13.0, Docker 29.1.3.
- Our noise floor on single runs was ±5 % decode and up to 13 % on agent runs. We only trust paired ABAB comparisons.
- The image is built from community patches, **not** an official NVIDIA or vLLM build. A rebuild will not be byte-identical to ours.
- The patch repo has moved on (vLLM 0.30). GoldVllm is deliberately frozen at the tested `d542745`.
- Not tested on a second GB10 yet. Reports welcome.

## Credits and licenses

This repository: Apache-2.0 ([LICENSE](LICENSE)). Third-party parts and credits: [NOTICE](NOTICE).
vLLM (Apache-2.0) · `blazux/qwen3.8-Flash-DGX` (Apache-2.0) · deterministic top-k kernel `jschmied/qwen38-flash-next-gb10` (in the image, **off** here) ·
model `RadixArk/Qwen3.8-Flash-Next-NVFP4` under its own license (see its model card).
