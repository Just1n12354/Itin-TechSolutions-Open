# Anleitung

Zwei Fassungen derselben Anleitung, beide auf Deutsch, jeweils als Markdown (zum Bearbeiten und für GitHub) und als PDF (zum Lesen und Drucken).

| Ordner | Für wen | Inhalt |
|---|---|---|
| [`Mensch/`](Mensch/) | Menschen – vom Laien bis zum Admin | Was GoldVllm ist, Einrichten Schritt für Schritt, Alltag, Störungen, Grenzen |
| [`AI/`](AI/) | KI-Assistenten mit Shell-Zugriff auf den GB10 | Soll-Werte, harte Regeln, Installationsablauf mit Abbruchbedingungen, Fehlertabelle, Messmethodik, Berichtsformat |

Wer die Einrichtung einer KI überlässt: ihr `AI/GoldVllm_Anleitung_KI.md` geben und selbst `Mensch/GoldVllm_Anleitung.pdf` lesen.

Die PDFs werden aus den Markdown-Dateien erzeugt: `python Anleitung/pdf_bauen.py` (braucht Python mit `markdown` und Google Chrome).
Nach jeder Änderung an einer `.md` neu erzeugen, damit beide Fassungen gleich bleiben.
