# FINAL C_de REPORT — Bestätigung 25.09.2026, 06:35–08:52

Letzter GX10-Optimierungstest. Auftrag: C_de reproduzierbar gegen Production B bestätigen oder endgültig ablehnen.
Ablauf: `JOURNAL.md`. Skript: `scripts/cde_test.sh`. Rohdaten: `measurements/`, `~/gx10-cde-0925/`.

## Urteil

# C_de BESTÄTIGT.
# C_de ist neue empfohlene Golden Configuration.
# GX10-OPTIMIERUNG ABGESCHLOSSEN – ZIEL ERREICHT.

- Durchschnittlicher End-to-End-Gewinn **+5.11 %**: Paar 1 **+3.95 %**, Paar 2 **+6.28 %**, beide ≥ 3 %.
- Qualität 12/12 in allen vier Läufen.
- Keine TTUA-p95- oder TTFT-Regression.
- 0 Xid, 0 OOM-Kill, 0 CUDA-/Engine-Fehler, 0 Wächter- oder Watchdog-Eingriffe, 0 Health-Ausfälle.
- RAM −0.65 GiB, innerhalb der Toleranz.

**Nicht übernommen:** Produktion läuft wieder als B (`pruefe_b.sh` OK, 08:50). C_de ist dokumentiert als Golden-Empfehlung;
die dauerhafte Übernahme entscheidet Justin (§10).

## 1 Konfiguration

| | B (Production) | C_de |
|---|---|---|
| Image | `gx10-vllm:b-v0290-d542745` (`sha256:c4a75dcb…`) | identisch |
| Modell | `RadixArk/Qwen3.8-Flash-Next-NVFP4` @ `7b719225` | identisch |
| KV / Kontext / Seqs / KV-dtype / MTP / Prefix | 12'884'901'888 / 262'144 / 16 / auto (bf16) / 2 / an | identisch |
| FAST_ROWS / Det-Top-k | 512 / aus | identisch |
| **Draft-Vokabular** | aus (volles lm_head, 248'320 Zeilen) | **`VLLM_MTP_DRAFT_VOCAB`** = `draft_vocab_de_65536.npy`, read-only gemountet |
| Vokabular-Datei | – | `/home/justin/gx10-nightrun/draftvocab/draft_vocab_de_65536.npy`, 262'272 B, **SHA256 `a864739485e0804049fe3481eff53770157f4b76cd6d91f556ff91ce454a23a1`** (am 22.09. bitgleich reproduziert; Korpus `Ragnarok/*/sources/text`, 65'536 IDs) |

Einzige Variable: das Draft-Vokabular. Die Serve-Argumente wurden per `diff` gegen den Nachtlauf verifiziert
(`vorpruefung.txt`: 8/8 OK). Gleiche Messkette in allen vier Läufen (`kandidat.sh`):
- Normalisierung `drop_caches`, Aufwärmen
- `benchmark_gx10.py` (G30 mit 30 Agentenschritten, TTUA, TP1/2/4)
- `nacht_bench.py`: Decode, TTFT kalt 30k/80k/110k, Agent 30k/80k, Qualitätsset `04b36f24…` bei Temperatur 0
- PLE-Probe

Die Prompts sind im Harness fest, also in jedem Lauf dieselben.

## 2 Rohwerte (alle vier Läufe)

| | B1 | CDE1 | B2 | CDE2 |
|---|---:|---:|---:|---:|
| **G30 s** | 74.68 | **68.84** | 74.78 | **65.53** |
| **TTUA Median s** | 1.763 | **1.651** | 1.766 | **1.570** |
| **TTUA p95 s** | 2.373 | **2.323** | 2.416 | **1.891** |
| **Agent 30k s** | 30.08 | 27.83 | 27.21 | 26.46 |
| **Agent 80k s** | 52.40 | 54.45 | 53.44 | 51.62 |
| TTFT kalt 30k / 80k / 110k s | 14.60 / 38.62 / 56.93 | 14.64 / 38.81 / 57.04 | 14.56 / 38.67 / 56.74 | 14.63 / 38.57 / 56.98 |
| Decode tok/s | 22.97 | 26.75 | 23.60 | 26.27 |
| ms pro Decode-Schritt (ABGELEITET: Acceptance-Länge / Decode) | 90.1 | 81.1 | 88.1 | 80.7 |
| MTP Acceptance-Länge / -Rate (Decode) | 2.07 / 0.54 | 2.17 / 0.59 | 2.08 / 0.54 | 2.12 / 0.56 |
| MTP Acceptance-Länge gesamt | 2.365 | 2.393 | 2.361 | 2.371 |
| TP1 / TP2 / TP4 tok/s | 19.0 / 29.7 / 46.2 | 21.1 / 29.8 / 48.1 | 19.6 / 29.4 / 44.0 | 20.6 / 30.9 / 47.7 |
| PLE-Gather Decode ms/Op | 6.18 | 6.36 | 5.81 | 6.73 |
| Qualität | 12/12 | 12/12 | 12/12 | 12/12 |
| Agenten korrekt / Tool-Call-Rate / Bench-Fehler | ja / 1.0 / 0 | ja / 1.0 / 0 | ja / 1.0 / 0 | ja / 1.0 / 0 |
| Prefix-Treffer ctx30 warm / Agent 30k | 0.945 / 0.676 | 0.945 / 0.676 | 0.945 / 0.676 | 0.945 / 0.676 |
| MemAvailable min / median MiB | 16'266 / 16'857 | 15'593 / 16'079 | 16'587 / 17'060 | 15'912 / 16'437 |
| Swap max MiB / pswpout / pswpin Δ MiB | 6'960 / 3'012 / 2'136 | 6'931 / 2'766 / 1'732 | 7'053 / 2'958 / 2'058 | 7'184 / 2'941 / 1'888 |
| PSI memory some max: Messung / Laden | 0.29 / 9.10 | 0.00 / 6.65 | 0.00 / 4.53 | 0.18 / 10.13 |
| längste Serie pswpin > 50/s (Messung) | 5 s | 5 s | 5 s | 10 s |
| Health `/health` nach Bereitschaft | 31/31 = 200 | 29/29 | 30/30 | 29/29 |
| bereit nach s / Hauptgewichte s | 861 / 554 | 882 / 573 | 882 / 565 | 862 / 556 |
| NV_ERR / Wächter | 0 / nein | 0 / nein | **1** (07:47:01, beim Laden) / nein | 0 / nein |
| GPU W median / °C max / Drosselung | 49.2 / 77 / 0 | 53.3 / 77 / 0 | 50.5 / 78 / 0 | 53.8 / 78 / 0 |

## 3 B1 gegen CDE1 (Paar 1)

| | Δ | |
|---|---:|---|
| **End-to-End (E2E-Score)** | **+3.95 %** | ≥ 3 % ✓ |
| G30 | −7.8 % | besser |
| TTUA Median / p95 | −6.4 % / −2.1 % | besser, keine p95-Regression ✓ |
| Agent 30k / 80k | −7.5 % / +3.9 % | 80k schlechter (siehe §6: verrauschte Grösse) |
| TTFT 30k / 80k / 110k | +0.3 / +0.5 / +0.2 % | im Rauschen, keine Regression ✓ |
| Decode | +16.5 % | nicht entscheidungsrelevant |
| Acceptance-Länge | +4.8 % | |
| MemAvailable min | −673 MiB (−4.1 %) | Toleranz 1'024 ✓ |

## 4 B2 gegen CDE2 (Paar 2)

| | Δ | |
|---|---:|---|
| **End-to-End (E2E-Score)** | **+6.28 %** | ≥ 3 % ✓ |
| G30 | −12.4 % | besser |
| TTUA Median / p95 | −11.1 % / **−21.7 %** | besser |
| Agent 30k / 80k | −2.8 % / −3.4 % | besser |
| TTFT 30k / 80k / 110k | +0.5 / −0.3 / +0.4 % | im Rauschen ✓ |
| Decode | +11.3 % | nicht entscheidungsrelevant |
| MemAvailable min | −675 MiB (−4.1 %) | ✓ |

**Mittel beider Paare: E2E +5.11 %**, G30 −10.1 %, TTUA Median −8.8 %, TTUA p95 −11.9 %.

## 5 Entscheidungskriterien

| # | Kriterium | Ergebnis |
|---|---|---|
| 1 | beide Paare ≥ 3 % E2E | **+3.95 % und +6.28 %** ✓ |
| 2 | Qualität 12/12 | 4 × 12/12, alle Agentenläufe korrekt, Tool-Call-Rate 1.0 ✓ |
| 3 | keine relevante TTUA-p95-/TTFT-Regression | TTUA-p95 −2.1 / −21.7 %; TTFT −0.3 bis +0.5 % ✓ |
| 4 | kein Xid/OOM/CUDA/Engine/Watchdog/Wächter | 0 Xid, 0 OOM-Kill, 0 CUDA-/Engine-Fehler im Log, 0 Wächter, 0 Watchdog ✓ (1 NV_ERR_NO_MEMORY beim Laden von **B2**, nicht C_de) |
| 5 | keine RAM-/Stabilitätsregression | MemAvailable −0.65 GiB (Toleranz 1 GiB), PSI in der Messung ≤ 0.18 %, kein andauerndes Paging, Health 100 % ✓ |

`entscheide.py paar B1 CDE1 B2 CDE2`: annehmen = **true**, keine Gründe (`measurements/entscheidung_cde.json`).

## 6 Vergleich mit dem Nachtlauf (24./25.09.)

| | Nacht CDE (gegen B0/B0_r2) | CDE1 (gegen B1) | CDE2 (gegen B2) |
|---|---:|---:|---:|
| E2E | +7.37 % | +3.95 % | +6.28 % |
| G30 | −7.4 % | −7.8 % | −12.4 % |
| TTUA Median | −5.3 % | −6.4 % | −11.1 % |
| TTUA p95 | −2.8 % | −2.1 % | −21.7 % |
| Decode | +8.9 % | +16.5 % | +11.3 % |
| MemAvailable min | −649 MiB | −673 MiB | −675 MiB |

**Drei von drei C_de-Läufen** unter identischen Bedingungen (je gegen zeitnahe B-Läufe) zeigen dasselbe Bild:
- G30 −7 bis −12 %, das stabilste agentische Mass; B streut dort zwischen identischen Läufen um ≤ 1.5 %.
- TTUA besser.
- TTFT unverändert.
- RAM konstant −0.65 GiB.

Über alle 7 Läufe beider Sitzungen: B-G30 73.60–74.78 s (4 Läufe: B0, B0_r2, B1, B2), C_de-G30 65.53–68.84 s
(3 Läufe: CDE, CDE1, CDE2). Die Bereiche überlappen nicht. Werte vom 21.09. sind nicht beigemischt.

Die schwächste Grösse ist Agent 80k (CDE1 +3.9 %). Das ist die Grösse, die zwischen identischen B-Läufen um 12 %
streut (Nachtbericht §5); sie widerspricht dem Befund daher nicht.

## 7 Vergleich mit dem widersprüchlichen Ergebnis vom 21.09.

Am 21./22.09. zeigte C_de gegen B:
- TTUA-p95 **+15 %** (2.25 gegen 1.96 s, zwei Läufe)
- Decode +8 %, G30 −4 %

Heute ist TTUA-p95 −2.1 / −21.7 % (und −2.8 % in der Nacht).

- **GEMESSEN:** Unter der heutigen Messkette ist die p95-Regression in **3 von 3** Läufen nicht reproduzierbar.
- **Nicht geklärt:** warum sie am 21.09. auftrat. Die Serve-Argumente sind identisch (diff-geprüft), das Vokabular ist
  bitgleich (gleiche SHA).
- **HYPOTHESE (nicht belegt):** Unterschiede zwischen den Nächten:
  - Normalisierung: Am 21.09. lief B_r3 noch mit `swapoff`-Normalisierung, ab 00:50 nur `drop_caches`.
  - Mehr Hintergrundlast damals: Aetheria-Lauf und OneDrive-Monitor, zusammen rund 2.5 GB.
  - B-Basis: Die B-Läufe vom 21.09. hatten ein ungewöhnlich gutes p95 von 1.95–1.96 s, heute 2.37–2.42 s.
- **Relevanz:** Die heutige Aussage stützt sich auf zeitnahe ABAB-Paare unter gleichen Bedingungen. Das ist die
  strengere Methode als der Vergleich über eine Nacht hinweg.

## 8 Stabilität, RAM, Swap, PSI, Xid, OOM, Health

- **Xid 0**, **OOM-Kill 0**, **CUDA-/Engine-Fehler 0** (Container-Logs geprüft auf `CUDA error`,
  `illegal memory access`, `EngineDeadError`, `EngineCore … died/failed`), **Wächter 0**, **Watchdog 0** über den
  ganzen Test.
- NV_ERR_NO_MEMORY: 1 Einzelmeldung 07:47:01 während des **Ladens von B2**. Das ist bekanntes Plattformverhalten
  beim Laden und betrifft nicht C_de.
- Health: 119 von 119 Proben nach Bereitschaft = 200.
- RAM: C_de braucht konstant ~0.65 GiB mehr (privater Kopf-Ausschnitt des Draft-Vokabulars, Logits-Puffer). In
  Produktion ergäbe das rechnerisch rund **6.8 GiB** statt 7.4–7.6 GiB Abstand zur Watchdog-Grenze, also ≥ 6 GiB.
- PSI memory während der Messung max 0.29 % (B1), 0.00–0.18 % bei C_de. Paging: höchstens 10 s am Stück über
  50 Seiten/s. Aktive Speicherknappheit nur beim Laden (wie immer).
- Thermik: max 78 °C, keine Drosselung; C_de zieht +3–4 W (mehr Arbeit pro Zeit).

## 9 Produktionszustand nach dem Test (08:50–08:52, `measurements/abschluss_check.txt`)

`pruefe_b.sh` OK: B mit Revision `7b719225`, 262'144, 16, KV 12'884'901'888, bf16, MTP 2, Prefix an. Container seit
08:36 (lokal), RestartCount 0. API 200/401, xiaozhi-Pfad 200. Hermes aktiv, Recovery aktiv, Watchdog aktiv,
Metriken aktiv, OneDrive-Timer aktiv. Xid 0, OOM-Kill 0, Wächter-Stopps 0.
NV_ERR seit Boot 2: 00:28 Laden MTP3 in der Nacht, 07:47 Laden B2.

**Production B: HEALTHY.**

## 10 Übernahme (Empfehlung, nicht ausgeführt, Entscheidung Justin)

1. Vokabular dauerhaft ablegen, read-only und root-eigen. Heute liegt es unter `~/gx10-nightrun/draftvocab/`; es
   gehört an einen festen Ort, der nicht aufgeräumt wird. SHA256 prüfen.
2. Katalogeintrag in `~/bin/switch-model.sh`, z. B. `flash-next-b-cde` = B-Eintrag + `DRAFT_VOCAB=<Pfad im Container>`.
   **Achtung:** `serve.sh` reicht `DRAFT_VOCAB` nur als Pfad durch und mountet die Datei **nicht**. `kandidat.sh` hat
   sie per `-v …:/opt/llm/draft_vocab_custom.npy:ro` gemountet. Die Übernahme braucht also entweder einen Mount in
   `serve.sh` oder das Vokabular im Image.
3. `llm-server.service` auf den neuen Eintrag umstellen, Neustart (~14 min), neue SEALED-Datei und `pruefe_*.sh`
   für die neue Golden Configuration, B bleibt versiegelte Rückfallebene.
4. Nach der Übernahme: 24 h Produktionsmetriken (`vllm_zusammenfassung.py`) mit echtem Ben-Verkehr beobachten.

## 11 Rohdaten

`measurements/<Lauf>.{bench13.json,nacht.json,sampler.csv,psi.csv,health.csv,ple_stats.txt,ple_probe.txt,
startzeit.json,start.json,pidstat.txt,nverr.log}` für B1, CDE1, B2, CDE2; `entscheidung_cde.json`;
`abschluss_check.txt`; `configs/<Lauf>.inspect.json` (Keys maskiert). Container-Logs: `~/gx10-cde-0925/<Lauf>/`.
