#!/usr/bin/env python3
"""repo_pruefen.py - prueft Itin-TechSolutions-Open vor einem Commit.

    python werkzeuge/repo_pruefen.py

Das Repo ist oeffentlich. Geprueft wird genau das, was Git committen wuerde
(getrackt + neu, ohne Ignoriertes):

  1. Geheimnisse    private Schluessel, GitHub-, API- und AWS-Token, JWT
  2. Dateinamen     .env, private SSH-Schluessel, Datentraegerabbilder, .pyc
  3. Eigene Pfade   Home-Verzeichnisse und Tailscale-Adressen ausserhalb der
                    Rohdaten (GoldVllm/data/) und der *.gx10-original-Kopien
  4. Binaer         *.pdf und *.npy muessen 'binary' sein - bis 02.10.2026
                    hat eine zweite .gitattributes das still ausgehebelt
  5. Links          relative Markdown-Links, die ins Leere zeigen
  6. Aufgaben       00_Task/pdf_erzeugen.py --pruefen (Inhalt der JSON und
                    ob Aufgaben.pdf zur JSON passt)

Exit 0 = sauber, 1 = Fehler gefunden.

Vorlage ist Acino/werkzeuge/repo_pruefen.py. Die Suchmuster sind absichtlich
zerlegt geschrieben, damit dieses Skript sich nicht selbst als Treffer meldet.
"""
import pathlib
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = pathlib.Path(__file__).resolve().parent.parent

GEHEIM = [
    ("JWT", re.compile("ey" + r"J[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.")),
    ("privater Schluessel", re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----")),
    ("GitHub-Token", re.compile(r"\bgh[pousr]" + r"_[A-Za-z0-9]{30,}")),
    ("API-Key (sk-)", re.compile(r"\bs" + r"k-[A-Za-z0-9_-]{30,}")),
    ("AWS-Key", re.compile(r"\bAK" + r"IA[0-9A-Z]{16}\b")),
    ("Hugging-Face-Token", re.compile(r"\bh" + r"f_[A-Za-z0-9]{30,}")),
]
EIGENE_PFADE = [
    ("Home-Verzeichnis", re.compile(r"/home/" + r"[a-z][a-z0-9_-]*/|/Users/" + r"[A-Za-z]")),
    ("Windows-Profil", re.compile(r"[A-Za-z]:[\\/]+" + r"Users[\\/]", re.I)),
    ("Tailscale-Adresse", re.compile(r"\b100\." + r"(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")),
]
# Rohdaten und Originalkopien zeigen bewusst den Zustand auf dem Messgeraet.
PFADE_ERLAUBT = re.compile(r"^(V1/|GoldVllm/data/)|\.gx10-original$|^werkzeuge/repo_pruefen\.py$")

VERBOTEN = [
    ("Umgebungsdatei", re.compile(r"(^|/)\.env(\.|$)")),
    ("privater SSH-Schluessel", re.compile(r"(^|/)id_(rsa|ed25519|ecdsa|dsa)$")),
    ("Schluesseldatei", re.compile(r"\.key$")),
    ("Datentraegerabbild", re.compile(r"\.(img|img\.xz|vhdx?|iso)$", re.I)),
    ("Python-Cache", re.compile(r"(^|/)__pycache__/|\.pyc$")),
]
TEXT_ENDUNGEN = {".md", ".txt", ".json", ".py", ".sh", ".service", ".timer", ".socket",
                 ".patch", ".default", ".csv", ".log", ".tsv", ".conf", ".yml", ".yaml", ""}
MAX_TEXT = 5 * 1024 * 1024
LINK = re.compile(r"\]\(([^)\s]+)\)")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def dateien():
    out = git("ls-files", "-co", "--exclude-standard", "-z")
    return [p for p in out.decode("utf-8").split("\0") if p and (ROOT / p).exists()]


def zeile(text, pos):
    return text.count("\n", 0, pos) + 1


def pruefe_text(rel, fehler):
    p = ROOT / rel
    if p.suffix.lower() not in TEXT_ENDUNGEN or p.stat().st_size > MAX_TEXT:
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    for name, muster in GEHEIM:
        for m in muster.finditer(text):
            fehler.append(f"{rel}:{zeile(text, m.start())}: {name}")
    if not PFADE_ERLAUBT.search(rel):
        for name, muster in EIGENE_PFADE:
            for m in muster.finditer(text):
                fehler.append(f"{rel}:{zeile(text, m.start())}: {name} '{m.group(0)}'")
    if rel.endswith(".md"):
        ohne_code = re.sub(r"```.*?```", "", text, flags=re.S)
        for m in LINK.finditer(ohne_code):
            ziel = m.group(1).split("#")[0]
            if ziel and not re.match(r"^[a-z]+:", ziel) and not (p.parent / unquote(ziel)).exists():
                fehler.append(f"{rel}: toter Link -> {ziel}")


def pruefe_binaer(liste, fehler):
    binaer = [r for r in liste if r.lower().endswith((".pdf", ".npy"))]
    if not binaer:
        return
    # Nicht 'binary' abfragen: das ist ein Makro und bleibt 'set', auch wenn eine
    # tiefere .gitattributes mit '* text=auto' das text-Attribut wieder einschaltet.
    out = git("check-attr", "text", "-z", "--", *binaer).decode("utf-8").split("\0")
    for pfad, _attr, wert in zip(out[0::3], out[1::3], out[2::3], strict=False):
        if wert != "unset":
            fehler.append(f"{pfad}: wird als Text behandelt (text={wert}), muss binary sein")


def pruefe_aufgaben(fehler):
    skript = ROOT / "00_Task" / "pdf_erzeugen.py"
    r = subprocess.run([sys.executable, "-B", str(skript), "--pruefen"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        meldung = (r.stderr.strip() or r.stdout.strip()).replace("\n", " | ")
        fehler.append(f"00_Task: {meldung}")


def main():
    fehler = []
    liste = dateien()
    for rel in liste:
        for name, muster in VERBOTEN:
            if muster.search(rel):
                fehler.append(f"{rel}: verbotener Dateiname ({name})")
        pruefe_text(rel, fehler)
    pruefe_binaer(liste, fehler)
    pruefe_aufgaben(fehler)
    if any(r.startswith("V1/") for r in liste):
        fehler.append("V1/ wuerde committet - gehoert in .gitignore")

    print(f"{len(liste)} Dateien geprueft.")
    for f in fehler:
        print("  FEHLER:", f)
    print("Sauber." if not fehler else f"{len(fehler)} Fehler.")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
