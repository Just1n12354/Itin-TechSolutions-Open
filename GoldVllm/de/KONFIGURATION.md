# GoldVllm — Konfiguration erklärt

Die Startzeile stammt aus `config/run-goldvllm.sh` und ist identisch mit der Produktion vom 25.09.2026.
„Gemessen“ heisst: eigene Messung auf dem GX10, Belege im Archiv des Autors. „laut blazux“ heisst: Begründung aus `scripts/serve.sh`
des Patch-Repos übernommen, nicht selbst nachgemessen.

## vLLM-Argumente

| Argument | Wert | Warum |
|---|---|---|
| Modellpfad | Snapshot `7b719225…` statt Repo-Name | fixe Revision, offline startbar (`HF_HUB_OFFLINE=1`) |
| `--served-model-name` | `qwen3.8-flash-next` | stabiler Name für die Clients |
| `--load-format` | `safetensors` | Standard des Checkpoints |
| `--max-model-len` | `262144` | voller Kontext des Modells |
| `--max-num-seqs` | `16` | reicht für einen Agenten plus Nebenanfragen |
| `--gpu-memory-utilization` | `0.80` | ist hier **wirkungslos**, weil der KV-Cache fest vorgegeben wird (nächste Zeile). Bleibt als Obergrenze stehen |
| `--kv-cache-memory-bytes` | `12884901888` (12 GiB) | 424'354 Tokens, also 1.62× Vollkontext. Gemessen (21.09.): Mit 18.74 GiB (663k Tokens) blieben nur ~570 MiB Abstand zum RAM-Wächter, ein zusätzlicher Agentenprozess (~2.2 GB) kostete einmal die Produktion. Mit 12 GiB sind es ≥ 9.3 GiB Abstand, bei gleicher Generationsrate |
| `--kv-cache-dtype` | `auto` (bf16) | laut blazux auf v0.29 Pflicht: FP8-KV ist dort nicht portiert |
| `--enable-prefix-caching` | an | laut blazux mit dem block_size-Fix dieses Images korrekt. Agenten schicken immer denselben langen Präfix. Gemessen: warmer Turn bei 80k 1.7 s statt 35.6 s |
| `--enable-chunked-prefill` + `--max-num-batched-tokens 8192` | an | so im blazux-`serve.sh`. Einzeln nicht nachgemessen |
| `-cc.cudagraph_mode` | `PIECEWISE` | laut blazux: Der PLE-Gather ist eine CPU-Operation mit Host-Kopie und muss ausserhalb der CUDA-Graphen laufen, deshalb nie FULL |
| `-cc.splitting_ops` | 13 Ops (siehe Skript) | an diesen Ops werden die Graphen geteilt, darunter `ple_mmap_lookup_ids`. Die Namen gelten für vLLM ≥ 0.29 (`qwen4_exp_*`). Der Preview-Build hatte andere Namen |
| `--no-enable-flashinfer-autotune` | an | so im blazux-`serve.sh` gesetzt. Einen Grund nennt es nicht |
| `--speculative-config` | `{"method":"mtp","num_speculative_tokens":2}` | Gemessen: MTP 2 ist optimal. MTP 1 macht die Agentenschritte 18 % langsamer, MTP 3/4 das Decode 12/16 % langsamer |
| `--enable-auto-tool-choice --tool-call-parser qwen3_coder` | an | XML-artige Tool-Calls von Qwen3.x |
| `--reasoning-parser` | `qwen3` | trennt `reasoning_content` vom Text |
| `--api-key` | aus Datei | Pflicht. Ohne Key gibt es 401 |

## Umgebungsvariablen

| Variable | Wert | Bedeutung |
|---|---|---|
| `VLLM_PLE_MMAP` | `1` | PLE-Tabelle (48 GB FP8) per mmap von der NVMe statt im RAM. Erst dadurch passt das Modell auf ein GB10 |
| `VLLM_PLE_MMAP_WORKERS` | `32` | Threads für den Gather |
| `VLLM_PLE_MMAP_MADVISE` | `random` | laut blazux: kein Readahead, sauberer Page-Cache |
| `VLLM_PLE_MMAP_PREWARM` | `0` | die Tabelle wird beim Start nicht vorgeladen. Wirkung einzeln nicht gemessen |
| `VLLM_PLE_MMAP_FAST_ROWS` | **nicht gesetzt** (Image-Standard 512) | Gemessen: `0` war schlechter und ist endgültig abgelehnt |
| `VLLM_MTP_DRAFT_VOCAB` | `/opt/llm/draft_vocab_custom.npy` | eingehängtes **deutsches** Draft-Vokabular (`draftvocab/`). Standard (englisch, im Image `/opt/llm/draft_vocab_65536.npy`) senkt bei deutschem Text die Acceptance von 0.70 auf 0.59 |
| `VLLM_QSA_EXACT_TOPK` | `0` | laut blazux: `1` wäre ein exakter `torch.topk`-Fallback, deterministisch, aber −20 bis −40 % beim langen Prefill |
| `VLLM_QSA_DET_TOPK` | **nicht gesetzt** | deterministischer Top-k-Kernel (jschmied) aus, anders als der blazux-Standard. Gemessen: Prefill und Decode kostet er nichts, im Einzellauf aber G30 +5 % und TTUA-p95 +19 %. Der Nutzen wurde nicht gemessen. GoldVllm war auch ohne ihn bei Temperatur 0 wiederholbar (3/3 Starts identisch) |
| `VLLM_FP8_PAD_M4` | `0` | laut blazux auf der v0.29-Basis wirkungslos (vllm#52775) |
| `VLLM_USE_FLASHINFER_SAMPLER` | `1` | so im blazux-`serve.sh` fest gesetzt |
| `VLLM_ALLOW_LONG_MAX_MODEL_LEN` | `0` | laut blazux nur für YaRN-Kontextverlängerung auf `1`. Hier nicht genutzt |
| `HF_HOME` / `HF_HUB_OFFLINE` | `/hf` / `1` | Cache im Container, kein Netz beim Start |

## Docker

`--gpus all --ipc=host --shm-size 16g`, Port nur `127.0.0.1:8000`, `--restart no`.
**Den Lebenszyklus steuert allein systemd.** Eine zwischenzeitlich gesetzte Policy `unless-stopped` hat bei uns keinen Reboot überlebt.

## Speicherbild im Betrieb (gemessen)

| | |
|---|---|
| Gewichte (ohne PLE) | 79.4 GiB |
| KV-Cache | 12.0 GiB |
| MemAvailable im Betrieb | 15.1–16 GiB (Minimum unter Last) |
| Swap belegt | ~7 GB |
| Abstand zum RAM-Wächter (122 GB belegt) | ~7 GiB |
