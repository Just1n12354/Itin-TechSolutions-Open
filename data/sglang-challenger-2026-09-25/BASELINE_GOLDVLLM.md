# GoldVllm — frische Baseline (25.09.2026)

Zwei Läufe, verschränkt mit SGLang (GOLD1 12:55–13:27, GOLD2 13:56–14:28). Die Konfiguration ist exakt GoldVllm:
Image `gx10-vllm:goldvllm` = `c4a75dcb`, C_de-Draft-Vokabular (SHA `a8647394…`, SHA-gleiche Kopie), MTP 2, KV 12'884'901'888 B,
16 Seqs, Prefix-Cache, FAST_ROWS 512. Der Messcontainer `bench-gold*` lief auf :8001 mit `/hf` read-only, wie bei der C_de-Qualifikation.
Rohdaten: `measurements/GOLD1.*`, `GOLD2.*`, `rohwerte_alle_laeufe.json`.

| | GOLD1 | GOLD2 | Mittel |
|---|---:|---:|---:|
| **G30 (30 Agentenschritte) s** | 61.61 | 61.79 | **61.70** |
| **Agent 30k s** | 27.89 | 28.96 | **28.43** |
| **Agent 80k s** | 47.99 | 48.75 | **48.37** |
| TTUA Median / p95 s | 1.464 / 1.771 | 1.477 / 1.791 | 1.47 / 1.78 |
| TTUA erster Schritt Agent 30k / 80k s | 14.55 / 36.67 | 15.57 / 37.97 | |
| TTFT kalt 30k / 80k / 110k s | 12.94 / 35.54 / 52.26 | 13.04 / 35.58 / 52.24 | |
| TTFT warm (Prefix-Treffer) 30k / 80k s | 1.04 / 1.65 | 1.01 / 1.67 | |
| Decode kurz tok/s | 27.83 | 26.96 | 27.4 |
| Decode nach 30k / 80k tok/s | 30.13 / 29.31 | 29.38 / 28.97 | |
| MTP Acceptance-Länge (Decode) | 2.15 | 2.08 | |
| TP1 / TP2 / TP4 tok/s | 22.5 / 33.2 / 51.0 | 23.5 / 31.7 / 52.6 | |
| Qualität | 12/12 | 12/12 | |
| Gates K1–K5 / K4b identisch | OK / ja | OK / ja | |
| Tool-Call-Rate G30 / Agenten korrekt | 1.0 / ja | 1.0 / ja | |
| MemAvailable min (Messung) MiB | 15'476 | 15'538 | |
| Swap max MiB / pswpin / pswpout Δ MiB | 7'005 / 2'224 / 3'141 | 7'235 / 2'309 / 3'225 | |
| PSI mem some max: Messung / Laden | 2.68 / 10.4 | 0.63 / 10.0 | |
| CPU / GPU-Auslastung Median (Messung) | 5.4 % / 96 % | 5.4 % / 96 % | |
| GPU-Leistung Median / max W | 53.0 / 98.7 | 51.4 / 99.1 | |
| bereit nach s | 852 | 902 | |
| Xid / OOM / Engine-Fehler / Wächter | 0 / 0 / 0 / nein | 0 / 0 / 0 / nein | |
| NV_ERR-Info (beim Laden) | 1 | 0 | |

Die Werte liegen etwas besser als bei der C_de-Qualifikation vom Morgen (G30 65.5–68.8 s), aber in derselben Grössenordnung.
Zwischen GOLD1 und GOLD2 streut G30 um 0.3 %, Agent 30k um 3.8 % und Agent 80k um 1.6 %.
