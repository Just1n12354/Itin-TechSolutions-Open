#!/usr/bin/env python3
"""pdf_erzeugen.py - erzeugt 00_Task/Aufgaben.pdf aus aufgaben.json.

Die PDF ist nur eine Ausgabe zum Lesen und Ausdrucken. Massgebend bleibt
aufgaben.json. Damit die PDF nicht still veraltet wie die alte Aufgaben.pdf
bis V1, traegt sie den SHA-256 der JSON in ihren Metadaten; --pruefen meldet,
sobald beides nicht mehr zusammenpasst.

Vorlage ist Acino/00_Task/pdf_erzeugen.py. --pruefen prueft auch den Inhalt
der JSON selbst: doppelte IDs, ungueltige Werte, erledigt ohne Nachweis.
werkzeuge/repo_pruefen.py ruft genau diese Pruefung auf.

    python 00_Task/pdf_erzeugen.py            PDF neu schreiben
    python 00_Task/pdf_erzeugen.py --pruefen  nur pruefen, Exit 1 bei Fehler oder veralteter PDF

Braucht reportlab (pip install reportlab). Die Ausgabe ist reproduzierbar:
gleiche JSON ergibt byte-gleiche PDF, also keine Scheinaenderungen im Git.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

HIER = pathlib.Path(__file__).resolve().parent
QUELLE = HIER / "aufgaben.json"
ZIEL = HIER / "Aufgaben.pdf"

PRIO_ORDNUNG = {"hoch": 0, "mittel": 1, "tief": 2}
STATUS_ORDNUNG = {"laeuft": 0, "offen": 1}
PRIO_FARBE = {"hoch": "#B3261E", "mittel": "#B26A00", "tief": "#5F6B76"}


def fingerabdruck():
    roh = QUELLE.read_bytes().replace(b"\r\n", b"\n")
    return "aufgaben-sha256:" + hashlib.sha256(roh).hexdigest()


def ist_aktuell():
    return ZIEL.exists() and fingerabdruck().encode() in ZIEL.read_bytes()


def inhaltsfehler(d):
    """Was an der JSON selbst falsch ist - eine Liste lesbarer Meldungen."""
    fehler = []
    gesehen = set()
    for i, a in enumerate(d.get("aufgaben") or []):
        aid = a.get("id") or f"#{i + 1}"
        if aid in gesehen:
            fehler.append(f"{aid}: ID doppelt")
        gesehen.add(aid)
        for feld in ("id", "titel", "was", "quelle", "erfasst"):
            if not a.get(feld):
                fehler.append(f"{aid}: Feld '{feld}' fehlt oder ist leer")
        if a.get("status") not in ("offen", "laeuft", "erledigt"):
            fehler.append(f"{aid}: status '{a.get('status')}' ungueltig")
        if a.get("prio") not in PRIO_ORDNUNG:
            fehler.append(f"{aid}: prio '{a.get('prio')}' ungueltig")
        # Erledigt ohne Nachweis ist genau der Zustand, der eine Liste
        # wertlos macht: niemand kann spaeter sagen, ob es stimmt.
        if a.get("status") == "erledigt" and not a.get("nachweis"):
            fehler.append(f"{aid}: erledigt ohne Nachweis")
        for feld in ("erfasst", "erledigt"):
            wert = a.get(feld)
            if wert:
                try:
                    datetime.date.fromisoformat(wert)
                except (TypeError, ValueError):
                    fehler.append(f"{aid}: {feld} '{wert}' ist kein Datum JJJJ-MM-TT")
    return fehler


def datum_de(iso):
    try:
        return datetime.date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return iso or "-"


def bauen():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    from xml.sax.saxutils import escape

    d = json.loads(QUELLE.read_text(encoding="utf-8"))
    aufgaben = d.get("aufgaben", [])
    name = d.get("repo") or HIER.parent.name
    offen = [a for a in aufgaben if a.get("status") != "erledigt"]
    erledigt = [a for a in aufgaben if a.get("status") == "erledigt"]
    offen.sort(key=lambda a: (STATUS_ORDNUNG.get(a.get("status"), 9),
                              PRIO_ORDNUNG.get(a.get("prio"), 9),
                              a.get("projekt", ""), a.get("id", "")))
    erledigt.sort(key=lambda a: a.get("id", ""))

    grau = colors.HexColor("#5F6B76")
    linie = colors.HexColor("#D5DADF")
    s = {
        "titel": ParagraphStyle("titel", fontName="Helvetica-Bold", fontSize=20, leading=24),
        "unter": ParagraphStyle("unter", fontName="Helvetica", fontSize=9.5, leading=13, textColor=grau),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=10, spaceAfter=6, keepWithNext=1),
        "kopf": ParagraphStyle("kopf", fontName="Helvetica-Bold", fontSize=10.5, leading=13),
        "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8, leading=10, textColor=grau),
        "text": ParagraphStyle("text", fontName="Helvetica", fontSize=9, leading=12, alignment=TA_LEFT),
        "warum": ParagraphStyle("warum", fontName="Helvetica-Oblique", fontSize=8.5, leading=11, textColor=grau),
        "id": ParagraphStyle("id", fontName="Helvetica-Bold", fontSize=9, leading=11),
        "klein": ParagraphStyle("klein", fontName="Helvetica", fontSize=8, leading=10),
        "zahl": ParagraphStyle("zahl", fontName="Helvetica-Bold", fontSize=16, leading=18),
    }
    e = lambda t: escape(str(t or ""))

    def badge(prio, status):
        farbe = PRIO_FARBE.get(prio, "#5F6B76")
        txt = f'<font color="{farbe}"><b>{e(prio).upper()}</b></font>'
        if status == "laeuft":
            txt += '<br/><font color="#1B6E3A"><b>LAEUFT</b></font>'
        return Paragraph(txt, s["meta"])

    story = [
        Paragraph(f"{e(name)} - Aufgaben", s["titel"]),
        Spacer(1, 2 * mm),
        Paragraph(f"{e(d.get('worum'))} Stand {datum_de(d.get('stand'))}. "
                  "Erzeugt aus <font face='Courier'>00_Task/aufgaben.json</font> - "
                  "massgebend ist die JSON, nicht diese PDF.", s["unter"]),
        Spacer(1, 5 * mm),
    ]

    zaehler = [[Paragraph(str(n), s["zahl"]) for n in (
                    len(offen),
                    sum(a.get("prio") == "hoch" for a in offen),
                    sum(a.get("status") == "laeuft" for a in offen),
                    len(erledigt))],
               [Paragraph(t, s["meta"]) for t in ("offen", "davon hoch", "laufen", "erledigt")]]
    t = Table(zaehler, colWidths=[42 * mm] * 4)
    t.setStyle(TableStyle([("LINEBELOW", (0, 1), (-1, 1), 0.5, linie),
                           ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                           ("TEXTCOLOR", (1, 0), (1, 0), colors.HexColor(PRIO_FARBE["hoch"]))]))
    story += [t, Spacer(1, 4 * mm)]

    story.append(Paragraph("Offen", s["h2"]))
    for a in offen:
        rechts = [Paragraph(e(a.get("titel")), s["kopf"]),
                  Paragraph(f"{e(a.get('projekt'))} · erfasst {datum_de(a.get('erfasst'))}", s["meta"]),
                  Spacer(1, 1.5 * mm),
                  Paragraph(e(a.get("was")), s["text"])]
        if a.get("warum"):
            rechts += [Spacer(1, 1 * mm), Paragraph("Warum: " + e(a["warum"]), s["warum"])]
        rechts += [Spacer(1, 1 * mm), Paragraph("Quelle: " + e(a.get("quelle")), s["meta"])]
        zeile = Table([[[Paragraph(e(a.get("id")), s["id"]), badge(a.get("prio"), a.get("status"))], rechts]],
                      colWidths=[20 * mm, 148 * mm])
        zeile.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBEFORE", (0, 0), (0, 0), 2.5, colors.HexColor(PRIO_FARBE.get(a.get("prio"), "#5F6B76"))),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, linie),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(KeepTogether(zeile))

    if erledigt:
        story.append(Paragraph("Erledigt", s["h2"]))
        zeilen = [[Paragraph("<b>ID</b>", s["klein"]), Paragraph("<b>Aufgabe</b>", s["klein"]),
                   Paragraph("<b>Nachweis</b>", s["klein"])]]
        for a in erledigt:
            datum = f" ({datum_de(a['erledigt'])})" if a.get("erledigt") else ""
            zeilen.append([Paragraph(e(a.get("id")), s["klein"]),
                           Paragraph(e(a.get("titel")) + e(datum), s["klein"]),
                           Paragraph(e(a.get("nachweis")), s["meta"])])
        t = Table(zeilen, colWidths=[16 * mm, 58 * mm, 94 * mm], repeatRows=1)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, linie),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(t)

    def fuss(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(grau)
        canvas.drawString(21 * mm, 10 * mm, f"{name}-Aufgaben · Stand {datum_de(d.get('stand'))} · oeffentliches Repo")
        canvas.drawRightString(A4[0] - 21 * mm, 10 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(ZIEL), pagesize=A4, leftMargin=21 * mm, rightMargin=21 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"{name} - Aufgaben", author="Justin Itin",
                            subject="Erzeugt aus 00_Task/aufgaben.json",
                            keywords=fingerabdruck(), invariant=1)
    doc.build(story, onFirstPage=fuss, onLaterPages=fuss)
    return len(offen), len(erledigt)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pruefen", action="store_true", help="nur pruefen, nichts schreiben")
    args = ap.parse_args()
    try:
        d = json.loads(QUELLE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        print(f"aufgaben.json nicht lesbar: {fehler}", file=sys.stderr)
        return 1
    fehler = inhaltsfehler(d)
    for f in fehler:
        print("FEHLER " + f, file=sys.stderr)
    if args.pruefen:
        ok = ist_aktuell()
        print("Aufgaben.pdf aktuell." if ok else
              "Aufgaben.pdf veraltet oder fehlt - python 00_Task/pdf_erzeugen.py ausfuehren.")
        return 0 if ok and not fehler else 1
    if fehler:
        print("Keine PDF geschrieben - erst die JSON reparieren.", file=sys.stderr)
        return 1
    try:
        n_offen, n_erledigt = bauen()
    except ImportError:
        print("reportlab fehlt: pip install reportlab", file=sys.stderr)
        return 2
    print(f"Geschrieben: {ZIEL.name} ({n_offen} offen, {n_erledigt} erledigt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
