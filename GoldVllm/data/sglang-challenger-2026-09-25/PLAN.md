# SGLang-Challenger gegen GoldVllm — Plan

Stand 25.09.2026, 12:50. Einmaliger Runtime-Vergleich, keine Optimierungsphase. Auftrag und Grenzen gibt Justin vor:
Es gilt nur ein **bereits existierender, nachvollziehbarer** GB10/SM121-Pfad für Qwen3.8-Flash-Next. Es gibt keine eigene
QSA-, PLE- oder Kernel-Portierung, kein vLLM-Tuning, keinen SGLang-Sweep und keine Änderung an GoldVllm.

## 1 Analyse: Gibt es einen fertigen Pfad?

**Ja.** Jede Angabe ist mit Quelle belegt. Mit [P] markierte Angaben habe ich am 25.09. selbst an der Primärquelle nachgeprüft.

| Befund | Quelle |
|---|---|
| Unser Checkpoint meldet `architectures: ["Qwen4ExpForConditionalGeneration"]`, `model_type: qwen4_exp`. `7b719225` ist weiterhin `main` | HF-API `RadixArk/Qwen3.8-Flash-Next-NVFP4` |
| Die SGLang-Unterstützung für `qwen4_exp` kam mit PR [#37500](https://github.com/sgl-project/sglang/pull/37500), gemergt 2026-09-08, `52fecfdf09` [P] | GitHub-API |
| NVFP4 auf DGX Spark, file-backed PLE und PDL-Router-Fix gegen den MTP-„!!!!“-Kollaps kamen mit PR [#39126](https://github.com/sgl-project/sglang/pull/39126), gemergt 2026-09-13, `cebca698e2` [P]. Getestet auf sm121, CUDA 13.0, TP=1 | GitHub-API |
| Release `v0.5.20` (2026-09-18) enthält #39126 (Compare: 107 voraus, 0 zurück) [P] | GitHub-API |
| **Das offizielle Cookbook hat ein verifiziertes Rezept für 1× DGX Spark mit genau unserem RadixArk-Checkpoint.** `verified: true`, verifiziert am 2026-09-06 auf `qwen4-main-squashed@4ccff141db`, Docker-Image `lmsysorg/sglang:dev-qwen38-next-local` [P] | [`docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx@v0.5.20`](https://github.com/sgl-project/sglang/blob/v0.5.20/docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx), Zellen `dgx-spark / nvfp4 / single` |
| Image `lmsysorg/sglang:dev-qwen38-next-local`: Index `sha256:9d2a843c…`, **arm64 `sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06`**, 14.4 GB, 2026-09-07 [P] | Docker-Hub-API |
| Alternative: `lmsysorg/sglang:v0.5.20-cu130`, arm64 `sha256:b0d8718a4424bb22e448e04407ab3ce5f7399a4c5fc702d6fbe36c3772ec8862` [P]. Für Spark nicht ausdrücklich verifiziert | Docker-Hub-API |
| Tool-Parser `qwen3_coder`, Reasoning-Parser `qwen3` und `--api-key` sind vorhanden, die API ist OpenAI-kompatibel | Recherche (v0.5.20-Quellcode), am Image mit `--help` gegenprüfen |
| NVIDIA-Image `nvcr.io/nvidia/sglang:26.08-py3` kennt `qwen4_exp` nicht | [#39497](https://github.com/sgl-project/sglang/issues/39497) |

**Für diesen Test gibt es keine eigene Entwicklung.** Modellklasse, QSA-Backend, PLE-Tabelle, MTP (NEXTN) und NVFP4
stammen alle aus SGLang selbst.

### Bekannte Grenzen des fertigen Pfads (aus dem Cookbook und den Issues)

| Grenze | Folge für Ben |
|---|---|
| **KV-Pool mit MTP nur ~93k Tokens** (8 Requests, 40 Mamba-Slots). GoldVllm hat 424k | Hermes komprimiert erst bei 0.5 × 262'144 = **131k**. Anfragen zwischen 93k und 131k würde SGLang abweisen. **Den Vergleich blockiert das nicht:** G30, Agent 30k und Agent 80k passen, und nur sie bilden die E2E-Grösse. **Für die Produktion schon.** Gewinnt SGLang, muss das vor einer Qualifikation gelöst sein |
| Die PLE-Tabelle wird als 47.7-GiB-Datei auf der NVMe **bei jedem Boot neu geschrieben**. Eine alte Datei vorher löschen, sonst dauert der Boot ~55 statt ~10 min | 48 GB Schreiblast pro Start, eigenes Verzeichnis nötig |
| [#40948](https://github.com/sgl-project/sglang/issues/40948) (offen, 09-23, GB10): QSA-Graph-Crash nach ~24 h, danach Treiber-Lock und Hard-Reboot | Nur für eine Qualifikation relevant, nicht für diesen Test |
| [#37326](https://github.com/sgl-project/sglang/issues/37326): MTP-Acceptance fällt über die Laufzeit gegen 0 | ditto |
| [#38319](https://github.com/sgl-project/sglang/issues/38319): Race zwischen Chunked Prefill und Radix-Cache korrumpiert KV-Seiten, der Fix #38355 ist offen | **Grund für die Korrektheits-Gates vor jeder Messung** |
| Kein Gegenstück zu `VLLM_MTP_DRAFT_VOCAB`. C_de' DE-Vokabular hat in SGLang kein Äquivalent | Gehört zum fairen Vergleich: gemessen wird, was die Runtime heute kann |

## 2 Konfiguration des Challengers

| | Wert |
|---|---|
| Image | `lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06` (das verifizierte Spark-Image). **Einmalige, vorab festgelegte Rückfalloption:** Startet es nicht, einmal `v0.5.20-cu130@sha256:b0d8718a…` mit identischen Argumenten. Danach Schluss |
| Container | `bench-sglang-<lauf>`, `--restart no`, Labels `gx10.llm=1 gx10.rolle=test` |
| Modell | Original-Snapshot `…/snapshots/7b719225…`, **read-only** gemountet (`-v ~/.cache/huggingface:/hf:ro`). Keine Kopie, keine Konvertierung |
| PLE | Cookbook-Pflicht für 1× Spark: `--ple-offload-embedding --ple-offload-backend file`. Die Tabelle liegt unter `~/gx10-sglang-0925/ple/`, eigenes Verzeichnis, vor jedem Start geleert (2.8 TB frei) |
| MTP | Cookbook-Zelle *low-latency*: `--speculative-algorithm NEXTN --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4`. Vergleichbar mit GoldVllm MTP=2, beide mit Spekulation |
| Kontext | `--context-length 262144` (Pool ~93k, siehe oben) |
| Speicher | `--mem-fraction-static 0.85` laut Rezept, `--max-running-requests 8 --max-mamba-cache-size 40 --page-size 64 --chunked-prefill-size 4096` |
| Quantisierung | `--quantization modelopt_fp4 --fp4-gemm-backend flashinfer_cutlass --tp 1` |
| Zusätze für Ben (notwendig, kein Tuning) | `--served-model-name qwen3.8-flash-next`, `--tool-call-parser qwen3_coder` (wie GoldVllm), `--reasoning-parser qwen3` (so im Rezept), `--api-key <Key>`, `--host 0.0.0.0 --port 8000` |
| Port | Bring-up und Ben-Test auf **`127.0.0.1:8000` mit dem Produktions-Key**, damit Hermes, der Tailscale-Proxy und xiaozhi unverändert bleiben. Messläufe auf `127.0.0.1:8001` mit Einweg-Key, wie bei GoldVllm |
| Docker-Optionen | `--gpus all --ipc=host --shm-size 16g`, wie GoldVllm |

Vor dem ersten Start prüfe ich mit `--help` im Image, ob alle Flags existieren. Fehlt ein Flag aus dem Rezept, ist das
ein Befund und keine Einladung zum Basteln.

Der Startbefehl (Messlauf; beim Bring-up Port 8000 und Produktions-Key):

```bash
docker run -d --name bench-sglang-<lauf> --restart no --label gx10.llm=1 --label gx10.rolle=test \
  --gpus all --ipc=host --shm-size 16g -p 127.0.0.1:8001:8000 \
  -v /home/justin/.cache/huggingface:/hf:ro -v /home/justin/gx10-sglang-0925/ple:/ple \
  -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
  lmsysorg/sglang@sha256:a1e17bbf0e9618364dc6395a4de5f9c3e8dfc9f43d603995b7a6aebc83de6e06 \
  python3 -m sglang.launch_server \
  --model-path /hf/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/7b719225242aacd3dbd3f9407468c2ee9a9d2594 \
  --served-model-name qwen3.8-flash-next --tp 1 --quantization modelopt_fp4 --fp4-gemm-backend flashinfer_cutlass \
  --page-size 64 --chunked-prefill-size 4096 --context-length 262144 \
  --speculative-algorithm NEXTN --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4 \
  --max-running-requests 8 --max-mamba-cache-size 40 --mem-fraction-static 0.85 \
  --ple-offload-embedding --ple-offload-backend file --ple-offload-dir /ple \
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder --api-key <KEY> --host 0.0.0.0 --port 8000
```

## 3 Schutz während des Tests: kein Umbau nötig

Ich habe den Code von Wächter und Recovery gelesen (`/usr/local/sbin/llm-memory-guard.sh`, `llm-recovery.sh`).
**Beide bleiben unverändert und aktiv.**

| Mechanismus | Verhalten im Test | Warum das passt |
|---|---|---|
| `llm-memory-guard` (alle 10 s, 122 GB belegt) | Stoppt bei echter Speichernot jeden Container, dessen Image oder Name `sglang` oder `vllm` enthält. Native Prozesse stoppt er ebenso | Der echte Speicherschutz gilt auch für SGLang |
| `llm-recovery` (jede Minute) | Handelt **nur** nach einem Wächter-Stopp und **nie**, solange ein `bench-*`-Container läuft (`busy()`) | Ein laufendes `bench-sglang-*` blockiert die Recovery. Ein geplantes `systemctl stop llm-server` ist kein Wächter-Ereignis und löst sie nicht aus |
| Wächter stoppt SGLang | Dann läuft kein `bench-*` mehr, und nach 10 min Cooldown holt die Recovery GoldVllm zurück | Gewollt: Speichernot ist eine Abbruchbedingung, und Ben kommt von selbst zurück |
| Zusätzlicher Test-Wächter | `sampler.py` aus der Messkette stoppt den Testcontainer schon vor dem System-Wächter | wie bei der C_de-Qualifikation |
| Reboot mitten im Test | `llm-server` startet GoldVllm (enabled). Der Testcontainer hat `--restart no` und bleibt aus | Autostart führt immer auf GoldVllm |

**Nie zwei Engines:** GoldVllm wird mit `sudo systemctl stop llm-server` gestoppt. Der Service bleibt enabled, keine Datei ändert sich.
Jeder Start prüft vorher: kein `qwen38-flash`, kein GPU-Prozess, MemAvailable ≥ 90 GiB (Gatter aus `kandidat.sh`).

**Zustand sichern:** GoldVllm ist eingefroren (`~/gx10-backups/GoldVllm`, `chattr +i`). Vor dem Stopp laufen
`verify-goldvllm.sh` und `inventar` (Container-Inspect).

## 4 Ablauf

Eine Abweichung von der Reihenfolge im Auftrag, mit Begründung: Die GoldVllm-Baseline läuft **nicht vorab als Block**,
sondern **verschränkt** (G1 S1 G2 S2).
- Das ist fairer: gleicher Tageszeitpunkt, gleicher thermischer und Swap-Zustand. Genau so wurde C_de gegen B qualifiziert.
- Das ist sparsamer: Fällt SGLang schon beim Bring-up durch, war keine Stunde Baseline umsonst.
- Die Baseline ist trotzdem frisch und liegt **vor** jeder SGLang-Messung.

| Schritt | Inhalt | Ben |
|---|---|---|
| 0 | Image-Pull, `--help`-Prüfung, Skripte (kein GPU-Zugriff) | läuft |
| 1 | `verify-goldvllm.sh`, dann `systemctl stop llm-server` | **weg** |
| 2 | **Bring-up SGLang** auf :8000, danach die Gates (§5). Fällt ein Gate durch: **STOP**, Restore, Urteil *SGLANG NICHT KOMPATIBEL* | Test-Ben auf SGLang |
| 3 | **G1**: GoldVllm-Messlauf (`kandidat.sh`, Image `c4a75dcb`, C_de-Werte, :8001) | weg |
| 4 | **S1**: SGLang-Messlauf, vorher die Gates erneut | weg |
| 5 | **G2**, dann **S2** | weg |
| 6 | Auswertung (`entscheide.py`), Urteil | weg |
| 7 | `restore-goldvllm.sh --ausfuehren` (**erster echter Restore-Test**, Zeit gemessen), `verify-goldvllm.sh`, Ben-Test | wieder da |

Geschätzte Gesamtdauer: 4–5 h. Den grössten Teil davon ist Ben nicht erreichbar.

## 5 Korrektheits-Gates (vor jeder SGLang-Messung; `/health 200` zählt nicht)

| Gate | Test | Bestanden |
|---|---|---|
| K1 | Qualitätsset `qualitaet_v1.json` (12 Aufgaben: 4 Tool, 2 ohne Tool, 3 Rechnen/Logik, Mehrschritt, Fehlerfall, Nadel), Temperatur 0 | **12/12** |
| K2 | Deterministische Rechnungen: 6 feste Aufgaben mit eindeutiger Zahl (mehrstellige Multiplikation, Division, Summe), Temperatur 0 | 6/6 exakt |
| K3 | Retrieval: je eine eingebettete Seriennummer in 30k- und 80k-Dokumenten aus dem Messkorpus, an fester Stelle | 2/2 exakt |
| K4 | Wiederholbarkeit: dieselbe Anfrage 3× bei Temperatur 0 | identische Antworten, keine Wiederholungsmuster („!!!!“), kein Leertext |
| K5 | API-Tool-Rundlauf (`lagerbestand`) wie im Boot-Test | Tool-Call und Antwort korrekt |
| K6 | **Echter Ben:** `hermes -z` normale Anfrage (17×23 = 391) und Terminal-Tool (`cat /etc/hostname` → `gx10`) | beide korrekt |
| K7 | 0 Xid, 0 OOM, keine Tracebacks und keine Engine-Fehler im Log, kein Wächter-Eingriff | 0 |

K1–K4 laufen zur Referenz auch gegen GoldVllm (G1). K6 geht nur auf :8000, also nur im Bring-up.

## 6 Messmethodik

- **Dieselbe Messkette wie bei der C_de-Qualifikation**, kopiert nach `scripts/`, Messlogik unverändert:
  - Normalisierung mit `drop_caches`, danach `aufwaermen.py`.
  - `benchmark_gx10.py --nur-schnell --agent-schritte 30`: G30 (30 Agentenschritte, Tool-Schemas fest), TTUA Median/p95, TP1/2/4.
  - `nacht_bench.py`: Decode, TTFT kalt 30k/80k/110k, Agent 30k/80k, Qualität.
  - Sampler (RAM, Swap, pswpin/pswpout, GPU, Xid), PSI-Sampler, pidstat.
- **Eine Anpassung, damit die Prompts gleich bleiben:** `nacht_bench.py` kalibriert seine Dokumente über `/tokenize`, das gibt es nur bei vLLM.
  Die Dokumente entstehen deshalb im Lauf G1 und kommen in einen Zwischenspeicher (`dokumente_cache.json`).
  S1, G2 und S2 lesen **dieselben Texte**, also byte-gleiche Prompts für beide Runtimes.
- **Die vLLM-Zähler** (MTP-Acceptance, Prefix-Treffer) gibt es bei SGLang nicht. Sie werden als „n/a“ berichtet und entscheiden nichts.
- **116k:** Agent 116k und Prefill 116k/110k liegen über dem SGLang-Pool von ~93k. Scheitern sie, wird das als Befund berichtet und nicht umgangen.
- Keine Cherry-Picks: alle vier Läufe, alle Werte, auch Fehlschläge. Rohdaten in `measurements/`.

## 7 Entscheidung

E2E wie bei C_de (`entscheide.py`): geometrisches Mittel der Zeitverhältnisse von **G30, Agent 30k, Agent 80k**,
berechnet je Paar (G1/S1, G2/S2).

**SGLang gewinnt nur, wenn alle Bedingungen erfüllt sind:**
- E2E-Gewinn ≥ 5 % im Mittel, in **beiden** Paaren ≥ 3 %.
- Qualität 12/12 und alle Gates bestanden.
- Tool-Call-Rate mindestens gleich.
- TTUA p95 höchstens +5 %, TTFT 30k/80k höchstens +10 %.
- MemAvailable-Minimum höchstens 1 GiB schlechter, PSI nicht deutlich höher.
- 0 Xid, 0 OOM, 0 Engine-Fehler.
- Betrieb realistisch wartbar. Die 93k-Grenze und der PLE-Neuschrieb pro Boot fliessen hier ein.

Sonst gilt: **GOLDVLLM GEWINNT – SGLANG VERWORFEN**. Fällt ein Gate durch: **SGLANG NICHT KOMPATIBEL – GOLDVLLM WIEDERHERGESTELLT**.

## 8 Abbruchbedingungen (sofort Restore)

- Ein Korrektheits-Gate fällt durch, oder die Ausgabe ist verdächtig: Wiederholungen, Leertext, falsche Zahlen.
- Start scheitert zweimal: einmal das verifizierte Image, einmal die vorab festgelegte v0.5.20-Rückfalloption.
- Xid, OOM, Engine-Crash, Wächter- oder Sampler-Eingriff.
- Ein Rezept-Flag fehlt, oder der Betrieb bräuchte Code-Änderungen.
- MemAvailable unter 10 GiB über mehr als 60 s während der Messung.

## 9 Rückweg

`gx10/GoldVllm/restore-goldvllm.sh --ausfuehren` stoppt alle fremden GPU-Container und startet `llm-server` neu.
Danach folgen `verify-goldvllm.sh` → `GOLDVLLM OK`, der Ben-Test (`ben_golden_test.sh`) und die Kontrolle auf genau eine Engine.
Die Restore-Zeit wird gemessen. Aufräumen danach: SGLang-Image und PLE-Datei (48 GB) werden gelöscht, wenn SGLang verliert.
Das GoldVllm-Image bleibt unangetastet.

## 10 Risiken

| Risiko | Gegenmittel |
|---|---|
| Speicher: 0.85 × 121 GiB für GPU-Pools plus Host-RSS lässt wenig Luft über der Wächter-Grenze (8.1 GiB) | sampler.py und Wächter aktiv, Abbruchbedingung. Kein Herunterdrehen der Werte |
| Stille Output-Korruption (#38319, MTP-Kollaps) | Gates K1–K4 vor **jeder** Messung, Qualität in jedem Lauf |
| Ben lange weg | vorher angekündigt. Ein Reboot führt immer auf GoldVllm |
| NVMe-Schreiblast 48 GB pro SGLang-Start (3 Starts ≈ 150 GB) | vertretbar für einen einmaligen Test |
| Der erste echte Restore scheitert | B-Rollback (`rollback_zu_b.sh`) als zweite, getestete Ebene |
