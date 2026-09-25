# GoldVllm — Qwen3.8-Flash-Next auf einem einzelnen NVIDIA GB10 (DGX Spark / ASUS Ascent GX10)

Eine **reproduzierbare, gemessene vLLM-Konfiguration** für `RadixArk/Qwen3.8-Flash-Next-NVFP4` mit vollen **262'144 Tokens Kontext**
auf **einem** GB10 mit 128 GB Unified Memory. Im Dauerbetrieb läuft sie als lokales Backend für einen Agenten (Hermes, „Ben“):
Tool-Calling, lange Kontexte, 24/7.

> **English TL;DR:** Qwen3.8-Flash-Next NVFP4 on a single GB10 (DGX Spark class), full 262k context, vLLM 0.29.0 +
> the community patches from `blazux/qwen3.8-Flash-DGX`, MTP=2 speculative decoding with a German-tuned draft vocabulary.
> Everything needed to rebuild it is here: image recipe, exact launch line, systemd unit, memory watchdog, checks, raw benchmark data.
> SGLang was tested head-to-head on the same box and lost (see `de/SGLANG_README.md`).

## Ergebnis in einem Satz

30 Agentenschritte in **61.7 s**, erste Antwort bei 80k Kontext nach **35.6 s**, **27.4 tok/s** Decode, **12/12** im Qualitätsset,
0 Xid, 0 OOM, stabil über Neustarts. Gemessen am 25.09.2026, Mittel aus zwei Läufen.

| Messwert (25.09.2026) | GoldVllm |
|---|---:|
| G30: 30 Agentenschritte mit Tool-Calls | 61.7 s |
| Agent 30k / 80k Kontext (4 Schritte) | 28.4 / 48.4 s |
| TTUA Median / p95 (Zeit bis zur ersten Aktion) | 1.47 / 1.78 s |
| TTFT kalt 30k / 80k / 110k | 13.0 / 35.6 / 52.3 s |
| TTFT mit Prefix-Treffer 30k / 80k | 1.0 / 1.7 s |
| Decode, ein Nutzer | 27.4 tok/s |
| Durchsatz 1 / 2 / 4 parallel | 23 / 32 / 52 tok/s |
| Qualität (12 Aufgaben inkl. Tool-Calls, Nadel im Heuhaufen) | 12/12 |
| KV-Cache | 12 GiB fest, 424'354 Tokens |
| Bereit nach Kaltstart | 14–15 min |

Details, Rohdaten und der Weg dorthin (A → B → C_de): [ERGEBNISSE.md](ERGEBNISSE.md).

## Was drinsteckt

| Baustein | Wert | Warum |
|---|---|---|
| vLLM | 0.29.0 (offizielles Image `vllm/vllm-openai:v0.29.0`) | gegenüber dem Qwen-Preview-Build −32 bis −40 % TTFT bei langem Kontext |
| Community-Patches | [`blazux/qwen3.8-Flash-DGX@d542745`](https://github.com/blazux/qwen3.8-Flash-DGX) (Apache-2.0) | PLE-Tabelle per mmap von der NVMe, GB10-Anpassungen für FLA/GDN, FP8-Hybrid, MTP-Backport |
| Modell | `RadixArk/Qwen3.8-Flash-Next-NVFP4` @ `7b719225242aacd3dbd3f9407468c2ee9a9d2594` | passt mit PLE-mmap auf ein GB10 |
| Spekulatives Decoding | MTP, 2 Tokens | 1 = Agentenschritte +18 %, 3/4 = Decode −12/−16 % |
| Draft-Vokabular | eigenes deutsches Vokabular, 65'536 IDs ([draftvocab/](../draftvocab/)) | Standard (englisch) senkt die Acceptance bei deutschem Text. Das DE-Vokabular bringt +8 % Decode und +5 % E2E |
| KV-Cache | 12 GiB fest | genug für 262k plus Reserve, lässt Luft über dem RAM-Wächter |

## Aufbau dieses Ordners

```
GoldVllm/
├── README.md          Übersicht (englisch)
├── AI_AGENT_GUIDE.md  Regeln für KI-Assistenten (englisch)
├── Anleitung/         Mensch/ und AI/: Anleitungen auf Deutsch, je als Markdown und PDF
├── de/
│   ├── README.md          diese Seite
│   ├── INSTALL.md         Schritt für Schritt: Image bauen, Modell laden, starten, prüfen
│   ├── KONFIGURATION.md   jedes Argument und jede Umgebungsvariable mit Begründung
│   ├── BETRIEB.md         systemd, RAM-Wächter, Recovery, Prüfung, Restore, Stolpersteine
│   ├── ERGEBNISSE.md      Messwerte, Methodik, Vergleich mit den Vorstufen
│   └── SGLANG_*.md        Vergleich mit SGLang und wie man ihn nachstellt
├── docs/              dieselben Dokumente auf Englisch, plus LESSONS
├── config/            run-goldvllm.sh, systemd-Units, RAM-Wächter, serve.sh-Patch
├── draftvocab/        draft_vocab_de_65536.npy (SHA256 a8647394…) und wie es entsteht
├── build/             Image-Rezept
├── bench/             Mess-Kit (G30, Agent 30k/80k, TTFT, Qualitätsset, Gates, Sampler)
└── data/              Rohdaten: Baseline 25.09., C_de-Qualifikation (JSON/CSV), Modell-Manifest
```

Der Restore Point des Autors (Inventar, Siegel, Restore/Verify gegen sein Backup) ist gerätespezifisch und nicht Teil dieses Repos.

## Grenzen (ehrlich)

- Gemessen auf **einem** Gerät, einem ASUS Ascent GX10 (Kernel 7.0.0-1019-nvidia, Treiber 580.178.04, CUDA 13.0).
  Auf anderem OS- oder Treiberstand kann es anders aussehen.
- Die Arbeitslast ist ein deutschsprachiger Agent mit Tool-Calls. Das deutsche Draft-Vokabular hilft **bei deutschem Text**.
  Für englische Arbeitslasten ist ein eigenes Vokabular sinnvoll (Rezept in `draftvocab/`).
- Ein Nutzer bzw. wenig Parallelität. Für viele gleichzeitige Nutzer ist die Konfiguration nicht optimiert.
- Das Image ist aus Community-Patches gebaut und kein offizieller NVIDIA- oder vLLM-Build.
- `blazux/qwen3.8-Flash-DGX` ist inzwischen weiter (vLLM 0.30). GoldVllm ist bewusst auf dem getesteten Stand `d542745` eingefroren.

## Dank und Lizenzen

- vLLM (Apache-2.0), Image `vllm/vllm-openai:v0.29.0`.
- `blazux/qwen3.8-Flash-DGX` (Apache-2.0): Patches, `serve.sh`, `build_draft_vocab.py`. Unsere Änderung an `serve.sh` liegt als Patch in `config/`.
- Deterministischer Top-k-Kernel (im Image, in GoldVllm **aus**): `jschmied/qwen38-flash-next-gb10@e0ef69d`.
- Modell: `RadixArk/Qwen3.8-Flash-Next-NVFP4`, Lizenz laut Model Card.
