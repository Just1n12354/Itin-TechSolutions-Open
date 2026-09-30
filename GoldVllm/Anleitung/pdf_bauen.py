#!/usr/bin/env python3
"""pdf_bauen.py - erzeugt aus den Anleitungen (Markdown) die PDFs daneben.

    python Anleitung/pdf_bauen.py

Braucht: Python-Paket `markdown` (pip install markdown) und Google Chrome oder Chromium.
Chrome-Pfad notfalls per Umgebungsvariable CHROME setzen.
"""
import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

HIER = Path(__file__).resolve().parent
DOKUMENTE = [
    (HIER / "Mensch" / "GoldVllm_Anleitung.md", "GoldVllm – Anleitung für Menschen"),
    (HIER / "AI" / "GoldVllm_Anleitung_KI.md", "GoldVllm – Arbeitsanweisung für KI-Assistenten"),
]

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm;
  @bottom-center { content: counter(page) " / " counter(pages); font: 8pt sans-serif; color: #777; } }
* { box-sizing: border-box; }
html { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1d1d1f; }
body { margin: 0; }
h1 { font-size: 21pt; line-height: 1.2; margin: 0 0 4pt; color: #6b4e00; border-bottom: 3px solid #c9a227; padding-bottom: 6pt; }
h1 + p { color: #555; font-size: 9pt; margin-top: 6pt; }
h2 { font-size: 14pt; margin: 20pt 0 6pt; color: #3a2c00; border-bottom: 1px solid #e3d7ae; padding-bottom: 3pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 4pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 18pt; }
hr { border: 0; border-top: 1px solid #ddd; margin: 14pt 0; }
code { font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 8.6pt; background: #f4f1e8; padding: 0 2pt; border-radius: 2pt;
  overflow-wrap: anywhere; }
pre { background: #f7f5ef; border: 1px solid #e6e0cc; border-left: 3px solid #c9a227; padding: 7pt 9pt; border-radius: 3pt;
  white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.2pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.8pt; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #ddd5bb; padding: 3.5pt 5pt; vertical-align: top; text-align: left; overflow-wrap: break-word; hyphens: manual; }
td:first-child { min-width: 24mm; }
th { background: #f3ecd4; font-weight: 600; }
tr:nth-child(even) td { background: #fcfaf4; }
blockquote { margin: 8pt 0; padding: 4pt 10pt; border-left: 3px solid #c9a227; background: #fbf8ee; }
strong { color: #111; }
a { color: #6b4e00; text-decoration: none; }
"""


def finde_chrome():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    kandidaten = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for k in kandidaten:
        if Path(k).exists():
            return k
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("Chrome/Chromium nicht gefunden - Pfad per CHROME=... setzen")


def baue(md_pfad, titel, chrome, tmp):
    text = md_pfad.read_text(encoding="utf-8")
    koerper = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    seite = (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{html.escape(titel)}</title>'
             f"<style>{CSS}</style></head><body>{koerper}</body></html>")
    html_pfad = Path(tmp) / (md_pfad.stem + ".html")
    html_pfad.write_text(seite, encoding="utf-8")
    pdf_pfad = md_pfad.with_suffix(".pdf")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_pfad}", html_pfad.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    print(f"{pdf_pfad.relative_to(HIER.parent)}  ({pdf_pfad.stat().st_size // 1024} KB)")


def main():
    chrome = finde_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        for md_pfad, titel in DOKUMENTE:
            baue(md_pfad, titel, chrome, tmp)


if __name__ == "__main__":
    main()
