# Itin TechSolutions Open

Offene Projekte von Itin TechSolutions rund um lokale KI auf einem einzelnen NVIDIA GB10
(ASUS Ascent GX10 / DGX Spark). Gemessen, eingefroren, mit Rohdaten, damit andere es nachbauen
oder widerlegen koennen.

> **English:** Open projects by Itin TechSolutions around local AI on a single NVIDIA GB10
> (ASUS Ascent GX10 / DGX Spark). Measured, frozen, with raw data. Start with
> [GoldVllm/README.md](GoldVllm/README.md), which is written in English.

## Projekte

| Ordner | Was | Stand |
|---|---|---|
| [`GoldVllm/`](GoldVllm/) | vLLM 0.29 mit `RadixArk/Qwen3.8-Flash-Next-NVFP4` und vollem Kontext (262'144 Tokens) auf einem GB10, 24/7 als Backend eines Agenten. Image-Rezept, Startzeile, systemd-Units, RAM-Waechter, Benchmark-Kit, Rohdaten, SGLang-Vergleich. | **fertig, eingefroren** (Stand 25.09.2026) |
| [`Hermes Ben/`](Hermes%20Ben/) | Lokaler autonomer Assistent auf dem GX10. | **noch nicht fertig**, noch nicht veroeffentlicht |
| [`Ziel/`](Ziel/) | Roadmap-Notizen. | Arbeitsnotiz |

## Wo anfangen

- **Menschen:** [GoldVllm/docs/INSTALL.md](GoldVllm/docs/INSTALL.md) (Englisch) oder die deutsche
  Anleitung [GoldVllm/Anleitung/Mensch/](GoldVllm/Anleitung/Mensch/) (Markdown + PDF).
- **KI-Assistenten mit Shell-Zugriff:** [GoldVllm/AI_AGENT_GUIDE.md](GoldVllm/AI_AGENT_GUIDE.md) oder
  [GoldVllm/Anleitung/AI/](GoldVllm/Anleitung/AI/).
- **Nur die Zahlen:** [GoldVllm/docs/RESULTS.md](GoldVllm/docs/RESULTS.md), deutsch
  [GoldVllm/de/ERGEBNISSE.md](GoldVllm/de/ERGEBNISSE.md).

## Grundsaetze

- **Messen statt behaupten.** Jede Zahl hat Rohdaten im Repo. Vergleiche nur gepaart (ABAB), weil
  Einzelmessungen bis 13 % streuen.
- **Kleinster Fix, dann STOP.** Was verworfen wurde, steht mit Begruendung drin
  ([GoldVllm/docs/LESSONS.md](GoldVllm/docs/LESSONS.md), [GoldVllm/docs/SGLANG.md](GoldVllm/docs/SGLANG.md)).
- **Ehrliche Grenzen.** Ein Geraet, eine Arbeitslast, Community-Patches statt offizieller Builds.
  Details im Abschnitt „Honest limits" von [GoldVllm/README.md](GoldVllm/README.md).

## Lizenz

Jedes Projekt traegt seine eigene Lizenz im eigenen Ordner.
GoldVllm: Apache-2.0 ([GoldVllm/LICENSE](GoldVllm/LICENSE)), Drittanteile in [GoldVllm/NOTICE](GoldVllm/NOTICE).
Das Modell selbst ist nicht enthalten und unterliegt seiner eigenen Lizenz.
