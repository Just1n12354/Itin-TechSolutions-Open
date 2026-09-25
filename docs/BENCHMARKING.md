# Benchmarking method

The kit is in `bench/`. The script names and output are German, the numbers are universal.

## What we measure (agent workload, not microbenchmarks)

| Test | Tool | What it is |
|---|---|---|
| **G30** | `benchmark_gx10.py --nur-schnell --agent-schritte 30` | 30 agent steps with fixed tool schemas at temperature 0. Main metric |
| **TTUA** median / p95 | same | time until the agent's first action (tool call or text) per step |
| **Agent 30k / 80k** | `nacht_bench.py` | 4-step tool task with 30k / 80k tokens of documents in the system prompt |
| TTFT cold / warm at 30k, 80k, 110k | `nacht_bench.py` | first token for a new long prompt; warm = follow-up turn with a prefix-cache hit |
| decode, TP1/2/4 | both | tokens/s single stream and with 2/4 concurrent requests |
| quality | `qualitaet_v1.json` | 12 frozen tasks, 12/12 required |
| correctness gates | `gates.py` | quality set, exact math, retrieval at 30k/80k, repeatability + collapse detection, tool round trip |
| system | `sampler.py`, `psi_sampler.py` | per second: MemAvailable, swap, pswpin/pswpout, major faults, NVMe reads, CPU, GPU util/W/°C, throttle, Xid; PSI |

**End-to-end score (E2E):** the geometric mean of the time ratios of G30, Agent 30k and Agent 80k (candidate / baseline).
A gain in % = (1 − E2E) × 100. Decode and TTFT are reported, but they do not decide on their own.

## How we run a comparison

1. **Serial.** Stop the production engine, check the GPU is empty and MemAvailable is ≥ 90 GB.
2. For each run: a fresh container (`bench-<label>`, port 8001, model mounted read-only), `drop_caches`, a warm-up, then the **gates**.
   No gates, no measurement.
3. **ABAB**: baseline 1, candidate 1, baseline 2, candidate 2. Same time of day, same thermal and swap state.
4. The long-context documents are calibrated once via vLLM's `/tokenize` and cached (`dokumente_cache.json`),
   so every run and every runtime gets byte-identical prompts.
5. Decide with `entscheide.py paar B1 K1 B2 K2`, using a rule fixed in advance:
   - E2E gain ≥ 3 % in **each** pair (the SGLang challenger required ≥ 5 % on average);
   - quality 12/12, and the tool-call rate no worse;
   - TTUA p95 at most +5 %, TTFT 30k/80k at most +10 %;
   - MemAvailable minimum at most 1 GiB worse;
   - 0 watchdog events, Xid or OOM.

## Our noise floor

Three identical runs of the same configuration scattered ±5 % on decode and up to 13 % on agent runs. Single runs below ~10 %
are noise. Paired ABAB made +4 % to +6 % gains visible and repeatable. In our ABAB baselines, G30 differed by only 0.3 % between the two baseline runs.

## Environment

`VLLM_BASIS_URL`, `VLLM_API_KEY`, `VLLM_CONTAINER` for the benchmark scripts. `KORPUS_DIR` for the long documents in `nacht_bench.py` and `gates.py`.
`FUELLTEXT` / `AUFWAERMTEXT` for the filler text in `benchmark_gx10.py` / `aufwaermen.py`.
Our runs used NVIDIA's DGX Spark documentation as text. It is not in this repo for licensing reasons, so with other text you get
comparable but not identical numbers.
