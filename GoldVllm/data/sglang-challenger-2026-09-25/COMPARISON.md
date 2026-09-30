# GoldVllm gegen SGLang — Vergleich

Paarweise wie bei der C_de-Qualifikation (`scripts/entscheide.py paar GOLD1 SGL1 GOLD2 SGL2`, Ergebnis `measurements/entscheidung.json`).
E2E ist das geometrische Mittel der Zeitverhältnisse von G30, Agent 30k und Agent 80k. Positiv heisst: SGLang ist schneller.

## E2E

| | Paar 1 (GOLD1/SGL1) | Paar 2 (GOLD2/SGL2) | Mittel | Schwelle |
|---|---:|---:|---:|---|
| **E2E-Gewinn SGLang** | **−11.23 %** | **+9.84 %** | **−0.70 %** | Mittel ≥ 5 %, je Paar ≥ 3 % |

**Nicht erfüllt.** Die beiden Paare liegen 21 Prozentpunkte auseinander. Der ganze Unterschied kommt von Agent 80k.

## Einzelwerte (Δ = SGLang gegen GoldVllm im selben Paar)

| Messwert | Paar 1 Δ | Paar 2 Δ | Richtung |
|---|---:|---:|---|
| G30 | −7.5 % | −10.6 % | SGLang besser, in beiden Paaren |
| Agent 30k | −3.7 % | −16.0 % | SGLang besser |
| Agent 80k | **+54.4 %** | −2.3 % | uneinheitlich, SGL1 stark schlechter |
| TTUA Median | −10.6 % | −15.4 % | SGLang besser |
| TTUA p95 | +2.7 % | −9.0 % | im Rahmen (Grenze +5 %) |
| TTFT kalt 30k | **+20.5 %** | +5.0 % | SGLang schlechter, **über der Grenze von +10 % in Paar 1** |
| TTFT kalt 80k | **+39.7 %** | **+21.3 %** | SGLang schlechter, **in beiden Paaren über der Grenze** |
| TTFT kalt 110k | abgewiesen | +16.2 % | SGLang schlechter bzw. nicht lauffähig |
| TTFT warm 30k / 80k | ≈ −60 % / −65 % | ≈ −56 % / −65 % | SGLang deutlich besser |
| Decode | −18.5 % | −13.5 % | SGLang schlechter |
| MemAvailable min | +701 MiB | +708 MiB | SGLang leicht besser |
| PSI mem Messung max | 1.17 gegen 2.68 | 0.74 gegen 0.63 | gleichwertig |
| PSI mem Laden max | 48.9 gegen 10.4 | 50.0 gegen 10.0 | SGLang schlechter (PLE-Neuschrieb) |

## Qualität, Tool-Calling, Stabilität

| | GoldVllm | SGLang |
|---|---|---|
| Qualität (12 Aufgaben) | 12/12, 12/12, 12/12 (Referenz) | 12/12, 12/12, 12/12 (Bring-up) |
| Rechnen K2 / Retrieval K3 | 6/6, 2/2 in allen Läufen | 6/6, 2/2 in allen Läufen |
| Tool-Call-Rate G30 / Agenten 30k+80k | 1.0 / korrekt | 1.0 / korrekt |
| API-Tool-Rundlauf / echter Ben | OK / OK | OK / OK |
| Wiederholbarkeit bei Temperatur 0 | identisch (3/3 Starts) | **nicht identisch (3/3 Starts)** |
| Eingaben über 109–127k | laufen (Pool 424k) | **still abgewiesen** (leerer Stream) |
| Xid / OOM / Engine-Fehler / Wächter | 0 | 0 |
| Health während der Messung | durchgehend 200 | durchgehend 200 |

## Entscheidungsgründe (entscheide.py)

`annehmen: false`. Die Gründe:
- E2E-Mittel −0.70 % statt ≥ 5 %.
- Paar 1 −11.23 % statt ≥ 3 %.
- TTFT kalt 30k +20.5 % (Paar 1).
- TTFT kalt 80k +39.7 % (Paar 1) und +21.3 % (Paar 2).

Unabhängig von der Rechnung sprechen drei weitere Punkte gegen einen Produktionsbetrieb, siehe FINAL_REPORT.md:
das harte Kontextlimit unter Hermes' 131k-Schwelle, der Nichtdeterminismus und die offenen Stabilitäts-Issues.
