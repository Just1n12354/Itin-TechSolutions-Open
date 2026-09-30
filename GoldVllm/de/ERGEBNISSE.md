# GoldVllm — Ergebnisse und Methodik

Alle Werte stammen aus eigenen Messungen auf einem ASUS Ascent GX10 (GB10) und sind als JSON/CSV in `../data/` abgelegt.
Die Messkette steht in `bench/`.

## Methodik

- **Seriell, nie zwei Engines.** Jeder Lauf startet einen frischen Container. Vorher `drop_caches`, danach Aufwärmen.
- **Gates vor jeder Messung** (`bench/gates.py`): Qualität 12/12, 6 exakte Rechnungen, Retrieval 30k/80k, Kollaps-Erkennung,
  Tool-Rundlauf. `/health 200` allein zählt nicht.
- **Ben-typische Last** (`bench/benchmark_gx10.py`, `bench/nacht_bench.py`):
  - **G30:** 30 Agentenschritte mit Tool-Calls, feste Tool-Schemas, Temperatur 0.
  - **Agent 30k/80k:** 4 Schritte mit 30k bzw. 80k Tokens Unterlagen im Systemprompt.
  - **TTFT kalt / warm** bei 30k, 80k und 110k.
  - **Decode, TP1/2/4, Qualitätsset.**
- **Sampler** jede Sekunde: MemAvailable, Swap, pswpin/pswpout, Major Faults, NVMe, CPU, GPU, Leistung, Temperatur, Drosselung, Xid.
  Dazu PSI.
- **E2E-Score** zum Vergleichen: geometrisches Mittel der Zeitverhältnisse von G30, Agent 30k und Agent 80k. Entschieden wird paarweise
  in ABAB-Reihenfolge (A1 B1 A2 B2), damit Tageszeit und Wärmezustand gleich sind.

## Baseline 25.09.2026 (`../data/goldvllm-baseline-2026-09-25/`)

| | GOLD1 | GOLD2 |
|---|---:|---:|
| G30 | 61.61 s | 61.79 s |
| Agent 30k / 80k | 27.89 / 47.99 s | 28.96 / 48.75 s |
| TTUA Median / p95 | 1.464 / 1.771 s | 1.477 / 1.791 s |
| TTFT kalt 30k / 80k / 110k | 12.94 / 35.54 / 52.26 s | 13.04 / 35.58 / 52.24 s |
| TTFT warm 30k / 80k | 1.04 / 1.65 s | 1.01 / 1.67 s |
| Decode | 27.83 tok/s | 26.96 tok/s |
| MTP-Acceptance-Länge | 2.15 | 2.08 |
| TP1 / TP2 / TP4 | 22.5 / 33.2 / 51.0 tok/s | 23.5 / 31.7 / 52.6 tok/s |
| Qualität / Gates / Wiederholbarkeit bei T=0 | 12/12 / OK / identisch | 12/12 / OK / identisch |
| MemAvailable min / Swap max | 15'476 / 7'005 MiB | 15'538 / 7'235 MiB |
| PSI mem some max (Messphase) | 2.68 | 0.63 |
| GPU-Leistung Median / max, Temperatur max | 53 / 99 W, 80 °C | 51 / 99 W, 79 °C |
| Bereit nach | 852 s | 902 s |
| Xid / OOM / Engine-Fehler | 0 / 0 / 0 | 0 / 0 / 0 |

## Weg dorthin (alle Stufen gemessen, Belege im Archiv des Autors)

| Stufe | Änderung | Ergebnis |
|---|---|---|
| A (21.09.) | Qwen-Preview-Build von vLLM + blazux-Patches, MTP 2, KV 18.74 → 12 GiB | lauffähig, 262k Kontext. KV-Reduktion gab ≥ 9 GiB Abstand zum RAM-Wächter |
| **B** (22.09.) | offizielles **vLLM 0.29.0** + dieselben Patches | **TTFT bei 30k–116k −32 bis −40 %, Agent 80k −26 %**, zweimal reproduziert. Decode, kurze Schritte und Qualität gleich |
| MTP-Sweep | 1 / 2 / 3 / 4 Tokens | 2 optimal. 1: Agentenschritte +18 %. 3/4: Decode −12/−16 % |
| Draft-Vokabular | Standard (englisch) gegen deutsch | Standard senkt die Acceptance bei deutschem Text (0.70 → 0.59). Deutsch hält sie und bringt +8 % Decode |
| **C_de = GoldVllm** (25.09.) | B + deutsches Draft-Vokabular | ABAB gegen B: **E2E +3.95 % / +6.28 %, Mittel +5.11 %**, G30 −7.8 / −12.4 %, Qualität 4×12/12 (`../data/cde-qualification-2026-09-25/`) |
| abgelehnt | FAST_ROWS=0, MTP 3/4, Det-Top-k-Kernel | jeweils schlechter oder ohne messbaren Nutzen für diese Last |
| **SGLang** (25.09.) | fertiger Cookbook-Pfad für 1× Spark | E2E −0.7 % gegen GoldVllm, harte Kontextgrenze 109–127k → verworfen (`SGLANG_README.md`) |

## Wo die Zeit hingeht (gemessen, 21.09.)

- Decode ≈ Speicherbandbreite + ein gesättigter Engine-Hauptthread (90–98 % eines Kerns) + PLE-Page-Faults.
  Bei identischem Text kostet ein kalter PLE-Zugriff etwa 23 %: 19.9 gegen 26.0 tok/s mit gecachter Tabelle.
- Kein Leistungs- oder Temperaturlimit: ≤ 80 °C, keine Drosselung.
