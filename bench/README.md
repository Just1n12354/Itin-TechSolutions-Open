# Mess-Kit

Dieselben Werkzeuge wie in allen Messungen unter `../data/`, auch beim SGLang-Vergleich (`../data/sglang-challenger-2026-09-25/`).

| Datei | Zweck |
|---|---|
| `gates.py` | Korrektheit vor jeder Messung: Qualität 12/12, exakte Rechnungen, Retrieval 30k/80k, Kollaps und Wiederholbarkeit, Tool-Rundlauf |
| `benchmark_gx10.py` | G30 (30 Agentenschritte), TTUA, TP1/2/4 (`--nur-schnell --agent-schritte 30`) |
| `nacht_bench.py` | Decode, TTFT kalt/warm 30k/80k/110k, Agent 30k/80k, Qualitätsset |
| `qualitaet_v1.json` | eingefrorenes Qualitätsset (SHA256 steht im Bericht jedes Laufs) |
| `aufwaermen.py` | vor der Messung aufwärmen |
| `sampler.py`, `psi_sampler.py` | RAM, Swap, Page-Faults, NVMe, CPU, GPU, Xid, PSI, jede Sekunde. `sampler.py --stoppe <container>` stoppt einen Testcontainer bei Gefahr |
| `auswertung.py`, `entscheide.py` | Kennzahlen je Lauf, E2E-Score und paarweise ABAB-Entscheidung |

Umgebung: `VLLM_BASIS_URL`, `VLLM_API_KEY`, `VLLM_CONTAINER`. Für die Langkontext-Dokumente `KORPUS_DIR` (beliebige `*.txt`).
Die Dokumente werden einmal kalibriert und in `dokumente_cache.json` abgelegt, damit alle Läufe byte-gleiche Prompts bekommen.
Die Kalibrierung braucht den vLLM-Endpunkt `/tokenize`, also zuerst gegen vLLM laufen lassen.
Fülltext für `benchmark_gx10.py` / `aufwaermen.py`: `FUELLTEXT` / `AUFWAERMTEXT` (eine `.txt`-Datei). Ohne diese Variablen gibt es einen Platzhaltersatz, der mit Prefix-Caching zu gute Zahlen liefert. Also echten Text verwenden.
