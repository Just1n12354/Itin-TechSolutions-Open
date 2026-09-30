# SGLang — Messergebnisse

Zwei Läufe mit derselben Messkette und denselben Prompts wie GoldVllm (SGL1 13:27–13:56, SGL2 14:28–14:58).
Die Langkontext-Dokumente stammen aus dem gemeinsamen Zwischenspeicher `measurements/dokumente_cache.json` und sind byte-gleich.
Rohdaten: `measurements/SGL1.*`, `SGL2.*`.

| | SGL1 | SGL2 | Mittel |
|---|---:|---:|---:|
| **G30 (30 Agentenschritte) s** | 57.01 | 55.22 | **56.12** |
| **Agent 30k s** | 26.87 | 24.32 | **25.60** |
| **Agent 80k s** | **74.08** | 47.61 | 60.85 |
| TTUA Median / p95 s | 1.309 / 1.818 | 1.250 / 1.630 | 1.28 / 1.72 |
| TTUA erster Schritt Agent 30k / 80k s | 18.86 / **66.26** | 16.24 / 38.98 | |
| TTFT kalt 30k / 80k / 110k s | 15.60 / 49.64 / **abgewiesen** | 13.69 / 43.15 / 60.72 | |
| TTFT warm (Prefix-Treffer) 30k / 80k s | 0.42 / 0.58 | 0.45 / 0.59 | |
| Decode kurz tok/s | 22.68 | 23.32 | 23.0 |
| Decode nach 30k / 80k tok/s | 22.62 / 24.45 | 23.63 / 25.51 | |
| MTP Acceptance (SGLang-Log, Decode) | 2.25–3.62, Rate 0.42–0.88 | ähnlich | (nicht vergleichbar mit vLLM-Zählern) |
| TP1 / TP2 / TP4 tok/s | 18.4 / 33.6 / 50.6 | 19.9 / 32.3 / 52.6 | |
| Qualität | 12/12 | 12/12 | |
| Gates K1–K5 / **K4b identisch** | OK / **nein** | OK / **nein** | |
| Tool-Call-Rate G30 / Agenten korrekt | 1.0 / ja | 1.0 / ja | |
| **KV-Pool Tokens** (Start) | **109'056** | 126'976 | Bring-up: 114'944 |
| MemAvailable min (Messung) MiB | 16'177 | 16'246 | |
| Swap max MiB / pswpin / pswpout Δ MiB | 7'517 / 2'045 / 3'647 | 7'632 / 2'121 / 3'638 | |
| PSI mem some max: Messung / Laden | 1.17 / **48.9** | 0.74 / **50.0** | |
| Major Faults Δ / NVMe gelesen GiB | 13.3 Mio. / 163 | 13.2 Mio. / 161 | |
| CPU / GPU-Auslastung Median (Messung) | 5.7 % / 96 % | 5.7 % / 96 % | |
| GPU-Leistung Median / max W | 38.0 / 65.0 | 40.9 / 65.1 | |
| bereit nach s | 682 | 671 | |
| Xid / OOM / Engine-Fehler / Wächter | 0 / 0 / 0 / nein | 0 / 0 / 0 / nein | |
| Drosselung (Sampler) | 0 | 1 Messpunkt ≠ 0 | |

## Befunde

1. **Das Limit für lange Eingaben ist hart und hängt vom Boot ab.** SGLang lehnt jede Eingabe über dem KV-Pool ab:
   `Input length (115676 tokens) exceeds the maximum allowed length (109050 tokens)`.
   Der Pool lag in drei Starts bei 109k, 115k und 127k Tokens, je nach freiem Speicher beim Start.
   **Beim Client kommt das nicht als Fehler an**, sondern als leerer Stream (`prompt_tokens=1`, kein `finish_reason`).
   Hermes komprimiert erst bei 131k. Lange Ben-Sitzungen würden also still leere Antworten bekommen.
2. **Kurze und warme Schritte sind schneller als bei GoldVllm.** TTFT mit Prefix-Treffer liegt bei 0.42–0.59 s gegenüber 1.0–1.7 s.
   TTUA Median ist 11–15 % besser, G30 7.5–10.6 % besser.
3. **Kalter langer Prefill ist langsamer.** TTFT kalt 80k liegt bei 43–50 s gegenüber 35.5 s. Der erste Agent-80k-Schritt in SGL1 brauchte 66 s.
   Warum SGL1 bei 80k so viel schlechter war als SGL2, ist ungeklärt. Möglich ist der kleinere Pool in SGL1 (109k).
   **Das ist eine Vermutung, nicht belegt.**
4. **Decode ist 13–19 % langsamer.** 23.0 gegenüber 27.4 tok/s. Das C_de-DE-Draft-Vokabular hat in SGLang kein Gegenstück.
5. **Nichtdeterministisch bei Temperatur 0** in allen drei SGLang-Starts (K4b). GoldVllm war in allen drei Starts identisch.
6. **Laden:** Der PLE-Neuschrieb erzeugt pro Start 48 GB Schreiblast auf der NVMe und hohen Speicherdruck (PSI bis 50).
   In der Messphase ist der Speicherdruck nicht höher als bei GoldVllm. Der Boot ist mit rund 11 min schneller als bei GoldVllm (14–15 min).
7. SGLang braucht weniger Leistung (Median 38–41 W gegenüber 51–53 W) bei gleicher gemeldeter GPU-Auslastung.
