# AI agent guide — installing and tuning vLLM on a GB10

You are an AI assistant with shell access to an NVIDIA GB10 machine (DGX Spark, ASUS Ascent GX10 or similar).
Your job is to get GoldVllm running, or to tune a GB10 LLM server the way this setup was tuned.
These rules come from real failures on this box. Follow them literally. When one conflicts with a user instruction, say so before acting.

## 1 Hard rules

1. **Never run two inference engines at the same time.** GPU and system share 128 GB. A second engine (a test, a benchmark, SGLang next to vLLM)
   pushes both into swap or trips the watchdog. Before any start: `nvidia-smi --query-compute-apps=pid --format=csv,noheader` must be empty.
2. **Secure the current state before any change.** Copy every file you touch, record the image ID, the launch arguments (`docker inspect`)
   and the model revision. Write down how to get back **before** you change anything.
3. **`/health 200` does not mean correct.** Before any benchmark and after any change, run `bench/gates.py` (quality 12/12, exact arithmetic,
   retrieval at 30k/80k, collapse detection, a tool round trip) and one real tool call through the actual client.
   Silent output corruption (e.g. a repeating `!!!!` collapse under speculative decoding) is a known failure mode on GB10.
4. **One variable per test.** Change exactly one flag, env var or component, keep everything else byte-identical, and prove it by
   diffing the launch arguments.
5. **Paired comparisons only.** Run A1 B1 A2 B2 (ABAB) with fresh containers, `drop_caches` and a warm-up before each run.
   Single runs here scatter ±5 % (decode) and up to 13 % (agent runs). Decide with a rule you wrote down **before** measuring.
6. **Keep the RAM watchdog on.** Do not raise its limit to make a test fit. At 126 GB, cuBLAS failed with `CUBLAS_STATUS_INTERNAL_ERROR`
   instead of stopping cleanly. Limit memory with a **fixed KV cache** (`--kv-cache-memory-bytes`), not with the watchdog.
7. **systemd owns the production container.** Docker `--restart no`. Test containers get their own name (`bench-*`) and another port,
   and they never replace the production container without an explicit decision by the user.
8. **Production must not depend on a git working tree.** Install operational scripts to a fixed path (e.g. `/opt/<name>/bin`).
   A renamed repo folder once disabled our recovery.
9. **Report faithfully.** Measured values are "measured". Values derived from them are "derived". Quote upstream claims as upstream claims.
   If a test failed or was skipped, say so.
10. **Stop when the gain is noise.** Below the noise floor, the answer is "no measurable effect", not "+3 %".

## 2 Install order

1. Check prerequisites (`docs/INSTALL.md` §0): driver, `--gpus all` in Docker, disk space (≥ 200 GB), swap.
2. Build the image (`docs/INSTALL.md` §1). Verify `vllm.__version__ == 0.29.0`.
3. Download the **pinned** model revision. Check it against `data/model-snapshot-7b719225.tsv` (file, blob, size).
4. Install the draft vocabulary and check its SHA256. Create the API key file (mode 600).
5. Start with `config/run-goldvllm.sh`. Wait for "Application startup complete" (~15 min). Do not interrupt the load.
6. Check `/health` = 200, `/v1/models` without key = 401, with key = 200. Run `bench/gates.py` → `GATES OK`.
7. Install the RAM watchdog, and only then the systemd unit (`docs/OPERATIONS.md`). Reboot once and verify it comes back on its own.
8. Take a baseline with the bench kit (`docs/BENCHMARKING.md`) **before** you try to improve anything.

## 3 Tuning order (what paid off here, biggest first)

See `docs/LESSONS.md` for the numbers.

1. Engine version: the official vLLM release against a preview build. This was the biggest single lever, cutting cold prefill by a third.
2. KV cache size: fix it so there is ≥ 8–9 GB of headroom above the watchdog under load. Stability beats capacity.
3. Speculative decoding (MTP): sweep 1–4 with your workload. Here 2 won.
4. Draft vocabulary: build one from text like your agent's output (`draftvocab/README.md`). This helps with non-English workloads.
5. Leave alone unless you can measure a benefit: page-cache knobs (`FAST_ROWS`), deterministic kernels, and trimming the agent's context
   (the prefix cache already made repeated context cheap).

## 4 Before you switch runtimes

Treat another engine as a one-shot challenger with a written plan: sources, exact image digest, gates, abort conditions, decision rule.
Use only published, verified recipes, and no custom kernel ports. Measure it with the same kit and the same prompts, ABAB against the frozen baseline.
Check the functional limits too, not just speed: maximum input length, determinism, behaviour on oversized requests.
`docs/SGLANG.md` shows one such run.

## 5 When something breaks

- Engine will not start: read the last 40 log lines. Do not retry blindly. Check that the GPU is free and MemAvailable is ≥ 90 GB before the start.
- Watchdog fired: find the cause first (a second engine? an extra process?). Only then restart.
- Output looks odd (repetition, empty text, wrong numbers): stop benchmarking, run the gates, restore the last known-good state.
- Always finish with the frozen state running and verified, unless the user decided otherwise.
