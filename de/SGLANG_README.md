# SGLang auf einem einzelnen GB10: Qwen3.8-Flash-Next, gemessen gegen GoldVllm

Ein einmaliger, fairer Vergleich vom 25.09.2026 auf einem ASUS Ascent GX10 (NVIDIA GB10, 128 GB Unified Memory).
Das Modell ist dasselbe wie bei GoldVllm, `RadixArk/Qwen3.8-Flash-Next-NVFP4` @ `7b719225…`.
Verwendet wurde **der fertige, offiziell verifizierte SGLang-Pfad** für 1× DGX Spark, ohne eigene Patches.

> **English TL;DR:** SGLang (image `lmsysorg/sglang@sha256:a1e17bbf…`, commit `4ccff141db`, the official single-Spark cookbook recipe)
> runs this model on one GB10 out of the box: correct output, tool calling works. Against a tuned vLLM 0.29 setup (GoldVllm) it is
> faster on short/warm agent steps, slower on cold long prefill, net −0.7 % end-to-end. With MTP it only accepts inputs up to the KV pool
> (109–127k tokens depending on boot), and oversized requests come back as an **empty stream without an error**.
> Output is not deterministic at temperature 0. Verdict for a long-context agent: vLLM stays.

## Urteil

**GOLDVLLM GEWINNT – SGLANG VERWORFEN.** Kompatibel ja, schneller nein.

| | GoldVllm (vLLM 0.29) | SGLang | Δ |
|---|---:|---:|---:|
| G30 (30 Agentenschritte) | 61.7 s | 56.1 s | −9 % |
| Agent 30k | 28.4 s | 25.6 s | −10 % |
| Agent 80k | 48.4 s | 60.9 s (74.1 / 47.6) | +26 % |
| TTFT kalt 30k / 80k | 13.0 / 35.6 s | 14.6 / 46.4 s | +13 / +31 % |
| TTFT mit Prefix-Treffer 80k | 1.66 s | 0.58 s | −65 % |
| TTUA Median / p95 | 1.47 / 1.78 s | 1.28 / 1.72 s | −13 / −3 % |
| Decode | 27.4 tok/s | 23.0 tok/s | −16 % |
| **E2E (G30, Agent 30k/80k)** | – | Paar 1 −11.2 %, Paar 2 +9.8 % | **−0.7 %** |
| Qualität / Tool-Calling | 12/12 / 1.0 | 12/12 / 1.0 | gleich |
| Wiederholbarkeit bei Temperatur 0 | identisch | **nicht identisch** | |
| maximale Eingabe | 262k | **109–127k** (je Boot) | |
| Bereit nach Kaltstart | 852–902 s | 671–682 s | SGLang schneller |
| Xid / OOM / Engine-Fehler | 0 | 0 | gleich |

Mittel aus je zwei Läufen, ABAB. Alle Rohdaten, Logs und das Journal: `../data/sglang-challenger-2026-09-25/FINAL_REPORT.md`.

## Die drei Befunde, die man vor einem Wechsel kennen sollte

1. **Die Kontextgrenze ist hart und kommt still.** Mit MTP nimmt SGLang auf einem Spark nur so viele Tokens an, wie in den KV-Pool passen.
   Der Pool lag bei drei Starts bei 109'056, 114'944 und 126'976 Tokens, je nachdem, wie viel Speicher beim Start frei war.
   Grössere Anfragen lehnt der Server ab (`Input length (115676 tokens) exceeds the maximum allowed length (109050 tokens)`).
   **Beim Client kommt ein leerer Stream an, keine Fehlermeldung.** Ein Agent, der erst bei 131k komprimiert, bekäme still leere Antworten.
2. **Nicht deterministisch bei Temperatur 0.** Drei gleiche Anfragen ergaben drei verschiedene, aber korrekte Texte, ab dem 63. Zeichen.
   Exakte Rechnungen blieben gleich. Das erschwert Regressionstests.
3. **Jeder Start schreibt die PLE-Tabelle neu.** Das sind 48 GB auf die NVMe, mit Speicherdruck bis PSI 50 beim Laden.
   Die alte Datei vorher löschen, sonst dauert der Boot etwa 55 statt etwa 11 Minuten.

Dazu sind laut SGLang-Issues offen: #40948 (QSA-Graph-Crash nach ~24 h mit Hard-Reboot, GB10) und #37326 (MTP-Acceptance fällt über die Laufzeit).
Beides war nicht Teil dieses Tests.

## Nachstellen

[INSTALL.md](INSTALL.md): Image per Digest, Startzeile, PLE-Verzeichnis, Korrektheits-Gates, Messung.
