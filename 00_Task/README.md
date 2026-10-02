# Aufgaben in Itin-TechSolutions-Open

`aufgaben.json` ist die Arbeitsquelle für die Aufgaben dieses Repositories.
`Aufgaben.pdf` ist nur die Ausgabe zum Lesen und Ausdrucken — massgebend ist
allein die JSON-Datei.

Nach jeder Änderung an der JSON:

```powershell
python 00_Task/pdf_erzeugen.py
```

Die PDF trägt einen Fingerabdruck der JSON. `python 00_Task/pdf_erzeugen.py --pruefen`
und `python werkzeuge/repo_pruefen.py` melden, sobald die beiden nicht mehr
zusammenpassen, eine ID doppelt vorkommt oder eine Aufgabe ohne Nachweis auf
`erledigt` steht.

Das Repo ist öffentlich. In die Aufgaben gehört nichts, was nicht öffentlich
stehen darf.

## So arbeiten wir

1. Eine Aufgabe auswählen und auf `laeuft` setzen.
2. Den aktuellen Zustand prüfen (Repo, GX10, Messdaten).
3. Eine kleine Änderung durchführen und das Ergebnis dokumentieren.
4. Erst mit einem konkreten Nachweis auf `erledigt` setzen.

Offene Punkte aus Berichten, Anleitungen und READMEs gehören ebenfalls hierher,
dort steht dann nur ein Verweis. Eine Liste an zwei Orten läuft auseinander.

## Reihenfolge

- `hoch`: Sicherheit, feste Frist oder Produktionsrisiko.
- `mittel`: konkrete technische Arbeit ohne akute Gefahr.
- `tief`: Ordnung, Dokumentation und Verbesserungen.
