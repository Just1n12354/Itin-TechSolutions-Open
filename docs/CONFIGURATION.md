# GoldVllm configuration explained

The launch line is `config/run-goldvllm.sh`, identical to the production container of 25 Sep 2026.
"Measured" means our own measurement on the GX10; the raw data is in `data/` or in the author's archive.
"Per blazux" means the reason is taken from `scripts/serve.sh` of the patch repo and was not re-measured by us.

## vLLM arguments

| Argument | Value | Why |
|---|---|---|
| model path | snapshot `7b719225…` instead of the repo name | pinned revision, starts offline (`HF_HUB_OFFLINE=1`) |
| `--served-model-name` | `qwen3.8-flash-next` | stable name for clients |
| `--load-format` | `safetensors` | checkpoint format |
| `--max-model-len` | `262144` | full model context |
| `--max-num-seqs` | `16` | enough for one agent plus side requests |
| `--gpu-memory-utilization` | `0.80` | **has no effect** here because the KV cache is fixed (next row); kept as an upper bound |
| `--kv-cache-memory-bytes` | `12884901888` (12 GiB) | 424,354 tokens = 1.62× full context. Measured (21 Sep): with 18.74 GiB (663k tokens) only ~570 MiB were left above the RAM watchdog, and one extra agent process (~2.2 GB) once cost us production. 12 GiB leaves ≥ 9.3 GiB at the same generation rate |
| `--kv-cache-dtype` | `auto` (bf16) | per blazux mandatory on v0.29: FP8 KV is not ported there |
| `--enable-prefix-caching` | on | per blazux correct with this image's block_size fix. Agents resend the same long prefix. Measured: warm turn at 80k takes 1.7 s instead of 35.6 s |
| `--enable-chunked-prefill` + `--max-num-batched-tokens 8192` | on | as in blazux `serve.sh`; not measured separately |
| `-cc.cudagraph_mode` | `PIECEWISE` | per blazux: the PLE gather is a CPU op with a host copy and must run outside CUDA graphs, so never FULL |
| `-cc.splitting_ops` | 13 ops (see script) | graph split points, including `ple_mmap_lookup_ids`. The names are valid for vLLM ≥ 0.29 (`qwen4_exp_*`); the preview build used other names |
| `--no-enable-flashinfer-autotune` | on | set in blazux `serve.sh`, which gives no reason |
| `--speculative-config` | `{"method":"mtp","num_speculative_tokens":2}` | measured: 2 is optimal. 1 makes agent steps 18 % slower, 3/4 make decode 12/16 % slower |
| `--enable-auto-tool-choice --tool-call-parser qwen3_coder` | on | Qwen3.x XML-style tool calls |
| `--reasoning-parser` | `qwen3` | separates `reasoning_content` from the text |
| `--api-key` | from file | mandatory; 401 without it |

## Environment

| Variable | Value | Meaning |
|---|---|---|
| `VLLM_PLE_MMAP` | `1` | the PLE table (48 GB FP8) is memory-mapped from NVMe instead of held in RAM; this is what makes the model fit on one GB10 |
| `VLLM_PLE_MMAP_WORKERS` | `32` | gather threads |
| `VLLM_PLE_MMAP_MADVISE` | `random` | per blazux: no readahead, cleaner page cache |
| `VLLM_PLE_MMAP_PREWARM` | `0` | the table is not preloaded at start; effect not measured separately |
| `VLLM_PLE_MMAP_FAST_ROWS` | **unset** (image default 512) | measured: `0` was worse and was rejected |
| `VLLM_MTP_DRAFT_VOCAB` | `/opt/llm/draft_vocab_custom.npy` | the mounted **German** draft vocabulary (`draftvocab/`). The stock one (`/opt/llm/draft_vocab_65536.npy` in the image) drops acceptance on German text from 0.70 to 0.59 |
| `VLLM_QSA_EXACT_TOPK` | `0` | per blazux, `1` would be an exact `torch.topk` fallback: deterministic, but −20 to −40 % on long prefill |
| `VLLM_QSA_DET_TOPK` | **unset** | deterministic top-k kernel (jschmied) off, unlike the blazux default. Measured: no prefill or decode cost, but in a single run G30 +5 % and TTUA p95 +19 %; the benefit was not measured. GoldVllm was repeatable at temperature 0 without it (identical in 3/3 starts) |
| `VLLM_FP8_PAD_M4` | `0` | per blazux a no-op on the v0.29 base (vllm#52775) |
| `VLLM_USE_FLASHINFER_SAMPLER` | `1` | hard-set in blazux `serve.sh` |
| `VLLM_ALLOW_LONG_MAX_MODEL_LEN` | `0` | per blazux only `1` for YaRN context extension; not used |
| `HF_HOME` / `HF_HUB_OFFLINE` | `/hf` / `1` | cache inside the container, no network at start |

## Docker

`--gpus all --ipc=host --shm-size 16g`, port on `127.0.0.1:8000` only, `--restart no`.
**systemd alone owns the lifecycle.** A `unless-stopped` policy we tried once did not survive a reboot.

## Memory picture in operation (measured)

| | |
|---|---|
| weights (without PLE) | 79.4 GiB |
| KV cache | 12.0 GiB |
| MemAvailable under load (minimum) | 15.1–16 GiB |
| swap used | ~7 GB |
| headroom to the RAM watchdog (122 GB used) | ~7 GiB |

## The one patch we made to `serve.sh`

`config/serve.sh.goldvllm.patch`: a `case` branch so that `DRAFT_VOCAB=/opt/gx10/*` mounts the file read-only into the container.
`run-goldvllm.sh` does not need `serve.sh` at all; the patch is only relevant if you start through the patch repo's `serve.sh`.
