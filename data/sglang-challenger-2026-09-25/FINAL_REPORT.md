# SGLang-Challenger gegen GoldVllm — Abschlussbericht

25.09.2026, 12:37–15:15, auf gx10. Plan: [PLAN.md](PLAN.md). Ablauf mit allen Abweichungen: [JOURNAL.md](JOURNAL.md).
Details: [BASELINE_GOLDVLLM.md](BASELINE_GOLDVLLM.md), [SGLANG_BUILD.md](SGLANG_BUILD.md), [SGLANG_RESULTS.md](SGLANG_RESULTS.md), [COMPARISON.md](COMPARISON.md).
Rohdaten: `measurements/` (JSON/CSV), Logs: `logs/`.

## Urteil

# GOLDVLLM GEWINNT – SGLANG VERWORFEN

SGLang ist auf diesem GX10 **kompatibel**: fertiger Cookbook-Pfad, keine eigenen Patches, Qualität 12/12, Ben und Tool-Calling funktionieren.
Es macht Ben aber **nicht reproduzierbar ≥ 5 % schneller**. Der E2E-Gewinn liegt im Mittel bei **−0.70 %**
(Paar 1 −11.23 %, Paar 2 +9.84 %). Dazu kommen Regressionen bei TTFT 30k und 80k.
Das Runtime-Thema ist damit geschlossen. GoldVllm läuft wieder als Produktion und ist verifiziert.

## Kompakt

| | GoldVllm (Mittel G1/G2) | SGLang (Mittel S1/S2) | Δ |
|---|---:|---:|---:|
| **G30** | 61.70 s | 56.12 s | −9.0 % |
| **Agent 30k** | 28.43 s | 25.60 s | −10.0 % |
| **Agent 80k** | 48.37 s | 60.85 s (74.1 / 47.6) | +25.8 % |
| TTFT kalt 30k / 80k | 12.99 / 35.56 s | 14.64 / 46.39 s | +12.7 / +30.5 % |
| TTFT kalt 110k | 52.25 s | abgewiesen / 60.72 s | nicht lauffähig bzw. +16 % |
| TTFT warm 30k / 80k | 1.03 / 1.66 s | 0.44 / 0.58 s | −58 / −65 % |
| TTUA Median / p95 | 1.47 / 1.78 s | 1.28 / 1.72 s | −13 / −3 % |
| Decode | 27.4 tok/s | 23.0 tok/s | −16 % |
| Prefill kalt 80k (Tokens/TTFT) | ≈ 2'240 tok/s | ≈ 1'710 tok/s | −24 % |
| RAM: MemAvailable min | 15.1 GiB | 15.8 GiB | +0.7 GiB |
| Swap max / PSI Messung max | 7.1 GB / 2.7 | 7.6 GB / 1.2 | gleichwertig |
| Kontext tatsächlich nutzbar | 262k (Pool 424k) | 109–127k (je Boot) | **−52 bis −58 %** |
| Stabilität | 0 Xid / OOM / Engine-Fehler | 0 Xid / OOM / Engine-Fehler | gleich |

**E2E-Differenz:** Paar 1 −11.23 %, Paar 2 +9.84 %, **Mittel −0.70 %** (Schwelle ≥ 5 %, je Paar ≥ 3 %).

**Qualität:** gleich. 12/12 in allen Gate- und Messläufen beider Runtimes, Rechnen 6/6, Retrieval 30k/80k 2/2.
**Tool-Calling:** gleich. Tool-Call-Rate 1.0, Agenten 30k/80k korrekt, API-Rundlauf und echter Ben-Terminal-Call OK.
**RAM:** SGLang in der Messung leicht besser (+0.7 GiB). Beim Laden ist der Speicherdruck deutlich höher (PSI 49–50 gegen 10) und
die NVMe bekommt pro Start 48 GB Schreiblast.
**Stabilität im Test:** gleich (0/0/0). Für den Dauerbetrieb sind bei SGLang die Issues #40948 (Crash nach ~24 h mit Hard-Reboot) und
#37326 (MTP-Verfall) offen. Beides wurde hier nicht geprüft, es ist aber bekannt.

## Warum SGLang verliert, obwohl es bei kurzen Schritten schneller ist

Der Befund ist gemischt. Ich stelle ihn deshalb ausdrücklich nicht einseitig dar:
- **SGLang ist bei kurzen und warmen Agentenschritten in beiden Paaren besser:** G30 −7.5 % und −10.6 %,
  TTUA Median −11 % und −15 %, TTFT mit Prefix-Treffer etwa 60 % niedriger.
- **SGLang ist bei kaltem langem Prefill in beiden Paaren schlechter:** TTFT 80k +40 % und +21 %.
  Dazu kommt ein Ausreisser bei Agent 80k in SGL1 (+54 %, ungeklärt).
- Mit der vorab festgelegten Regel ergibt sich so kein reproduzierbarer Gewinn. Die Streuung zwischen den SGLang-Läufen ist
  deutlich grösser als bei GoldVllm (Agent 80k: 74.1 / 47.6 s gegen 48.0 / 48.8 s).

**Selbst ein Gewinn in der Messung hätte nicht für die Produktion gereicht.** Drei Befunde sind strukturell und lassen sich nicht wegtunen:
1. **Harte, schwankende Kontextgrenze unter Bens Bedarf.** Mit MTP nimmt SGLang Eingaben nur bis zur Poolgrösse an (109–127k je Boot).
   Hermes komprimiert erst bei 131k. Grössere Anfragen weist SGLang ab, und **beim Client kommt ein leerer Stream an, kein Fehler**.
   Ben bekäme also in langen Sitzungen still leere Antworten.
2. **Nichtdeterministisch bei Temperatur 0** (3/3 Starts), GoldVllm ist identisch (3/3). Das erschwert Fehlersuche und Regressionstests.
3. **Betrieb:** Jeder Start schreibt die 48-GB-PLE-Datei neu, und die offenen Langzeit-Issues passen nicht zu einem 24/7-Agenten.

## Restore — erster echter Test von `restore-goldvllm.sh --ausfuehren`

| Prüfung | Ergebnis |
|---|---|
| Laufzeit | **814 s** (14:58:22 → 15:11:56), davon ~811 s bis `/health 200` (Neustart `llm-server`) |
| Backup intakt / Modell vollständig | ja / ja |
| abweichende Dateien | **0 von 27**. GoldVllm wurde während des ganzen Tests nicht verändert |
| fremde GPU-Container | keine mehr (die Messskripte hatten sie schon entfernt) |
| `verify-goldvllm.sh` direkt nach Restore | **DRIFT: `hermes-gateway aktiv`**. Ursache ist mein Ablauf: `challenger.sh` hatte Hermes für die Messung gestoppt und startete ihn erst *nach* dem Restore wieder. Kein Fehler des Restores |
| `verify-goldvllm.sh` nach Hermes-Start | **GOLDVLLM OK** |
| `/health` / API ohne Key / mit Key | 200 / 401 / 200 |
| Ben normal / echter Terminal-Tool-Call / API-Tool-Rundlauf | 391 (19 s) / `gx10` (6 s) / OK |
| Autostart | `llm-server` enabled, `ExecStart=… flash-next-cde` |
| Watchdog / Recovery | aktiv / aktiv, Zustand NORMAL, nie ausgelöst |
| Engines | genau 1 |
| Xid / OOM / Wächter seit Teststart | 0 / 0 / 0. Drei `NV_ERR_NO_MEMORY`-Infozeilen beim Laden (12:54, 13:08, 15:09), bekanntes Muster, kein Xid |

## Eigene Fehler und Abweichungen (offen benannt)

- **K4 nachträglich geteilt.** Ich hatte „identisch bei Temperatur 0“ als hartes Gate definiert, strenger als Justins Vorgabe.
  Nachdem SGLang daran gescheitert war, habe ich K4 in K4a (hart: kein Kollaps) und K4b (Befund) geteilt, für beide Runtimes gleich.
  Das begünstigte SGLang und ist deshalb im Journal festgehalten. Am Urteil ändert es nichts.
- **K4-Prompt im ersten Entwurf untauglich.** Das Modell dachte länger als 3000 Tokens nach. Ersetzt, bevor SGLang lief.
- **OneDrive-Timer nicht pausiert.** Er ist ein Nutzer-Timer, ich hatte ihn als System-Timer gestoppt. Er lief um 13:03 und 14:04,
  beide Male in der Ladephase von GOLD1 bzw. GOLD2, also **in keiner Messung**.
- **Reihenfolge Hermes/Restore in `challenger.sh`**, siehe oben.
- **Baseline verschränkt statt als Block vorab.** Im Plan vorab begründet (fairer, keine verschwendete Baseline bei Bring-up-Abbruch).

## Aufräumen

Das SGLang-Image (14.4 GB) und die PLE-Datei (48 GB) werden entfernt. GoldVllm-Image, Modell und Backup bleiben unberührt.
Den Stand dieses Tests stellt jederzeit wieder her: `docker pull lmsysorg/sglang@sha256:a1e17bbf…` und `scripts/kandidat_sglang.sh`.
