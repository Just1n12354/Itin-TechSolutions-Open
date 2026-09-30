# Lessons: what squeezes vLLM on a GB10, and what doesn't

Ranked by measured effect for a single-user, tool-calling agent with long context. Every item has a number behind it (see RESULTS.md).

## What paid off

1. **Use the official engine release, not a preview build.** Switching from the Qwen preview build to official vLLM 0.29.0,
   with the same patches, cut cold prefill at 30k–116k by 32–40 % and an 80k agent run by 26 %. This was the biggest single lever.
2. **Fix the KV cache size and leave headroom.** On unified memory, "as much KV as fits" is a trap. 18.7 GiB left ~570 MiB
   above the watchdog, and one extra process took production down. 12 GiB (still 424k tokens, 1.6× full context) leaves ≥ 9 GB.
   `--gpu-memory-utilization` becomes irrelevant once `--kv-cache-memory-bytes` is set.
3. **Sweep speculative decoding with your own workload.** MTP 2 won. MTP 1 slowed agent steps by 18 %; 3 and 4 slowed decode by 12–16 %.
   Note that on the author's earlier runs, MTP made a run with 2 concurrent requests 18 % slower than without MTP.
4. **Match the draft vocabulary to your language.** The stock 65k vocabulary is English-leaning. On German text it dropped acceptance
   from 0.70 to 0.59. A vocabulary built from German domain text kept acceptance and gave +8 % decode; confirmed ABAB at +5.1 % end-to-end.
5. **Prefix caching is what makes agents fast.** A warm follow-up turn at 80k takes 1.7 s instead of 35.6 s cold.

## What did not pay off

- **Trimming old tool results from the agent's context.** 44.5 % of all processed tokens were resent tool results, which looked like
  the biggest lever. Trimming them cut context by 39 % with practically no speed gain, because the prefix cache already served the repeats cheaply.
  A metric that counts waste is not the same as one that measures its cost.
- **`VLLM_PLE_MMAP_FAST_ROWS=0`**: worse. Rejected.
- **MTP 3/4**: slower decode.
- **The deterministic top-k kernel**: no prefill/decode cost, but G30 +5 % and TTUA p95 +19 % in a single run, and no measured benefit.
  GoldVllm was repeatable at temperature 0 without it.
- **Another runtime (SGLang)**: faster on short and warm steps, slower on cold long prefill, net −0.7 %. It has a hard input limit
  below our agent's needs.

## Things that bite you on a GB10

- **The only hard limit is memory.** Power and thermals were never the problem: at most ~100 W and 80 °C, no throttling.
- **Decode is bound by bandwidth, one saturated engine thread, and PLE page faults.** Cold PLE rows cost ~23 % decode speed.
  The model reads 16 rows of 160 bytes per token from a 47.7 GiB table, each on its own 4 KiB page.
- **Measure your noise first.** Three identical runs scattered ±5 % (decode) and up to 13 % (agent runs). Without ABAB, a +5 % gain is invisible.
- **`/health` lies by omission.** Gate every measurement on correctness.
- **Reboot once.** Two things only showed up after a reboot: a KV setting silently reverting, and a restart policy that did not survive.
- **Keep production out of your git tree.** A folder rename disabled our recovery.
