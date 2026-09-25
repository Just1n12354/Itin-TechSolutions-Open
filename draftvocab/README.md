# Draft-Vokabular (C_de)

`draft_vocab_de_65536.npy`: 65'536 Token-IDs, 262'272 Bytes,
**SHA256 `a864739485e0804049fe3481eff53770157f4b76cd6d91f556ff91ce454a23a1`**.

## Was es tut

Der MTP-Drafter bewertet beim spekulativen Decoding nicht das volle Vokabular mit 248'320 Zeilen, sondern nur diese
65'536 häufigsten IDs. Das spart Zeit pro Draft-Schritt. Welche IDs das sind, entscheidet, ob die Vorschläge zur eigenen Sprache passen:

Nachtlauf 21./22.09.2026 (Acceptance-Rate im Decode):

| Vokabular | Acceptance | Decode |
|---|---:|---|
| volles lm_head (kein Draft-Vokabular) | 0.70 | Referenz |
| Standard `draft_vocab_65536.npy` (im Image, englisch geprägt) | 0.59 | kein Gewinn für diese Last |
| **deutsch (diese Datei)** | hält ≈ 0.70 | **+8 %** (zweimal gemessen) |

C_de-Qualifikation 25.09.2026, ABAB gegen B (volles lm_head):

| | B1 → CDE1 | B2 → CDE2 |
|---|---|---|
| Acceptance-Rate / -Länge (Decode) | 0.54 / 2.07 → 0.59 / 2.17 | 0.54 / 2.08 → 0.56 / 2.12 |
| Decode | 22.97 → 26.75 tok/s (+16.5 %) | 23.60 → 26.27 tok/s (+11.3 %) |
| E2E (G30, Agent 30k/80k) | +3.95 % | +6.28 % |

(Werte aus der C_de-Qualifikation und dem Nachtlauf 21./22.09., `../data/cde-qualification-2026-09-25/FINAL_CDE_REPORT.md`.)

## Wie es entstanden ist

Mit dem Werkzeug aus dem Patch-Repo, `tools/build_draft_vocab.py` aus `blazux/qwen3.8-Flash-DGX@d542745`:

```bash
python3 tools/build_draft_vocab.py <tokenizer_dir> draft_vocab_de_65536.npy --n 65536 --corpus <txt-dateien...>
# tokenizer_dir = der Modell-Snapshot 7b719225…
```

Korpus waren deutschsprachige Fachtexte: Recht, Buchhaltung, Elektroinstallation, Technik. Zusammen 5.4 Mio. Zeichen,
26'547 verschiedene Token-IDs, 100 % Abdeckung. 8'298 der 65'536 IDs weichen vom Standard ab.
Am 22.09.2026 wurde die Datei aus demselben Korpus bitgleich neu erzeugt.

## Für andere Sprachen oder Arbeitslasten

Einfach mit eigenem Korpus bauen, am besten mit Texten, wie sie der eigene Agent tatsächlich schreibt. Danach gegen den Standard messen.
Der Gewinn hängt an der Sprache. Für Englisch ist das Standardvokabular vermutlich schon passend. **Das ist nicht gemessen.**
