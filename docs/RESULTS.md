# Results

All numbers come from our own measurements on one ASUS Ascent GX10 (GB10), stored as JSON/CSV in `data/`.

## GoldVllm baseline, 25 Sep 2026 (`data/goldvllm-baseline-2026-09-25/`)

| | GOLD1 | GOLD2 |
|---|---:|---:|
| G30 | 61.61 s | 61.79 s |
| Agent 30k / 80k | 27.89 / 47.99 s | 28.96 / 48.75 s |
| TTUA median / p95 | 1.464 / 1.771 s | 1.477 / 1.791 s |
| TTFT cold 30k / 80k / 110k | 12.94 / 35.54 / 52.26 s | 13.04 / 35.58 / 52.24 s |
| TTFT warm 30k / 80k | 1.04 / 1.65 s | 1.01 / 1.67 s |
| decode | 27.83 tok/s | 26.96 tok/s |
| MTP acceptance length | 2.15 | 2.08 |
| TP1 / TP2 / TP4 | 22.5 / 33.2 / 51.0 tok/s | 23.5 / 31.7 / 52.6 tok/s |
| quality / gates / repeatable at T=0 | 12/12 / OK / identical | 12/12 / OK / identical |
| MemAvailable min / swap max | 15,476 / 7,005 MiB | 15,538 / 7,235 MiB |
| PSI memory some, max (measurement phase) | 2.68 | 0.63 |
| GPU power median / max, temp max | 53 / 99 W, 80 °C | 51 / 99 W, 79 °C |
| ready after | 852 s | 902 s |
| Xid / OOM / engine errors | 0 / 0 / 0 | 0 / 0 / 0 |

## The path (every step measured; the earlier steps are in the author's archive)

| Step | Change | Result |
|---|---|---|
| A (21 Sep) | Qwen preview build of vLLM + blazux patches, MTP 2; KV 18.74 → 12 GiB | runs with 262k context; the KV reduction bought ≥ 9 GiB of headroom above the watchdog |
| **B** (22 Sep) | official **vLLM 0.29.0** + the same patches | **cold TTFT at 30k–116k −32 to −40 %, agent 80k −26 %**, reproduced twice; decode, short steps and quality unchanged |
| MTP sweep | 1 / 2 / 3 / 4 tokens | 2 is optimal. 1: agent steps +18 %. 3/4: decode −12/−16 % |
| draft vocabulary | stock (English) vs. German | the stock one drops acceptance on German text (0.70 → 0.59); the German one keeps it, +8 % decode |
| **C_de = GoldVllm** (25 Sep) | B + German draft vocabulary | ABAB against B: **E2E +3.95 % / +6.28 %, mean +5.11 %**; G30 −7.8 / −12.4 %; quality 4×12/12 (`data/cde-qualification-2026-09-25/`) |
| rejected | FAST_ROWS=0, MTP 3/4, deterministic top-k kernel | each worse, or no measurable benefit for this workload |
| **SGLang** (25 Sep) | official single-Spark cookbook recipe | E2E −0.7 % vs. GoldVllm, hard input limit 109–127k → rejected ([SGLANG.md](SGLANG.md)) |

## Validation of the frozen state

- A real reboot came back on its own: ready after 902 s, exactly one engine, verify OK, a real agent request and a real terminal tool call OK.
- Rollback to B and back to GoldVllm: both directions OK.
- The first real restore from the frozen backup after the SGLang test: 814 s, 0 of 30 files differing, all checks green.

## Where the time goes (measured, 21 Sep)

- Decode ≈ memory bandwidth + a saturated engine main thread (90–98 % of one core) + PLE page faults.
  On identical text, cold PLE access costs about 23 %: 19.9 vs. 26.0 tok/s with the table cached.
- No power or thermal limit: ≤ 80 °C, no throttling.
