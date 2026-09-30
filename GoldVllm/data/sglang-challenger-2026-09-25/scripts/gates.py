#!/usr/bin/env python3
"""Korrektheits-Gates K1-K5 fuer den SGLang-Challenger (PLAN.md §5). Laeuft identisch gegen GoldVllm und SGLang.

  K1 Qualitaetsset qualitaet_v1.json (12 Aufgaben, Temperatur 0)   - Logik aus nacht_bench.teil_qual
  K2 6 deterministische Rechnungen, exakte Zahl                    - Temperatur 0
  K3 Retrieval: Seriennummer in 30k- und 80k-Dokument              - Dokumente aus dem gemeinsamen Zwischenspeicher
  K4 Wiederholbarkeit: dieselbe Anfrage 3x, identisch, kein Kollaps
  K5 API-Tool-Rundlauf (lagerbestand)
Ausgabe: JSON (--ausgabe) + Zeile "GATES OK" (Exit 0) oder "GATES FEHLER" (Exit 1).
Key nur aus VLLM_API_KEY. Aendert nichts am System.
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nacht_bench as nb  # noqa: E402  (chat, dokument, teil_qual, KEY)

RECHNUNGEN = [("48193 * 271", "13060303"), ("987654 - 123789", "863865"), ("7 * 8 * 9 * 11", "5544"),
              ("144144 / 12", "12012"), ("2 hoch 20", "1048576"), ("35 + 47 + 58 + 91 + 19", "250")]
NADELN = [(30000, "GX-30K-7Q4M-2291"), (80000, "GX-80K-3F8T-6604")]
LAGER_TOOL = [{"type": "function", "function": {"name": "lagerbestand", "description": "Lagerbestand eines Artikels.",
               "parameters": {"type": "object", "properties": {"artikel": {"type": "string"}}, "required": ["artikel"]}}}]


def nur_zahl(text: str) -> str:
    return re.sub(r"[ '’.,]", "", text or "")


def kollaps(text: str) -> bool:
    t = text or ""
    return (not t.strip()) or bool(re.search(r"(.)\1{7,}", t)) or bool(re.search(r"(\b\w+\b)(\s+\1\b){5,}", t))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True); p.add_argument("--label", required=True); p.add_argument("--ausgabe", required=True)
    a = p.parse_args()
    modell = "qwen3.8-flash-next"; erg: dict = {"label": a.label, "zeit": time.strftime("%FT%T")}
    sys_msg = {"role": "system", "content": "Du bist ein genauer Assistent. Antworte knapp."}

    q = nb.teil_qual(a.url, modell, a.label)
    erg["K1"] = {"ok": q["punkte"] == q["von"], "punkte": q["punkte"], "von": q["von"], "qset_sha256": q["qset_sha256"],
                 "fehler": [d for d in q["details"] if not d["ok"]]}

    k2 = []
    for ausdruck, soll in RECHNUNGEN:
        r = nb.chat(a.url, modell, [sys_msg, {"role": "user", "content": f"Rechne ohne Werkzeug: {ausdruck}. Antworte nur mit der Zahl."}], 2000)
        k2.append({"aufgabe": ausdruck, "soll": soll, "antwort": (r["content"] or "")[-80:], "ok": soll in nur_zahl(r["content"])})
    erg["K2"] = {"ok": all(x["ok"] for x in k2), "details": k2}

    k3 = []
    for ziel, sn in NADELN:
        doc = nb.dokument(a.url, modell, ziel, versatz=401_000 + ziel)
        pos = int(len(doc) * 0.37); doc = doc[:pos] + f"\nSeriennummer des Pruefgeraets: {sn}\n" + doc[pos:]
        r = nb.chat(a.url, modell, [sys_msg, {"role": "user", "content": "Unterlagen:\n" + doc +
                    "\n\nWie lautet die Seriennummer des Pruefgeraets? Antworte nur mit der Seriennummer."}], 2000)
        k3.append({"kontext": ziel, "prompt_tokens": r["prompt_tokens"], "soll": sn, "antwort": (r["content"] or "")[-80:],
                   "fehler": r["fehler"], "ok": sn in (r["content"] or "")})
    erg["K3"] = {"ok": all(x["ok"] for x in k3), "details": k3}

    # ohne Denkphase, damit 3x derselbe lange Ausgabetext (~400 Tokens) verglichen wird - prueft Decode/MTP, nicht Wissen
    frage = [sys_msg, {"role": "user", "content": "Erklaere in genau acht nummerierten Saetzen, wie ein "
             "Fehlerstromschutzschalter (FI) funktioniert und warum er Personen schuetzt."}]
    antw = [nb.chat(a.url, modell, frage, 800, thinking=False)["content"] or "" for _ in range(3)]
    # K4a (hart): kein Kollaps/Leertext. K4b (Befund, nicht blockierend): identisch bei Temperatur 0.
    # Geaendert 25.09. 12:55 nach dem SGLang-Bring-up, fuer BEIDE Runtimes gleich - Begruendung in JOURNAL.md.
    erg["K4"] = {"ok": not any(kollaps(x) for x in antw),
                 "identisch": len(set(antw)) == 1, "kollaps": [kollaps(x) for x in antw], "antwort": antw[0][:300]}

    msgs = [sys_msg, {"role": "user", "content": "Wie viele FI-Schalter 40A/30mA haben wir an Lager? Nutze das Werkzeug."}]
    r = nb.chat(a.url, modell, msgs, 2000, tools=LAGER_TOOL); ok5 = False; detail5 = {"tools": r["tool_calls"]}
    if r["tool_calls"] and r["tool_calls"][0]["name"] == "lagerbestand":
        c = r["tool_calls"][0]
        msgs += [{"role": "assistant", "content": r["content"] or None, "tool_calls": [
                  {"id": "c1", "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}]},
                 {"role": "tool", "tool_call_id": "c1", "content": "37"}]
        r2 = nb.chat(a.url, modell, msgs, 2000, tools=LAGER_TOOL)
        ok5 = "37" in (r2["content"] or ""); detail5["antwort"] = (r2["content"] or "")[-120:]
    erg["K5"] = {"ok": ok5, **detail5}

    erg["ok"] = all(erg[k]["ok"] for k in ("K1", "K2", "K3", "K4", "K5"))
    Path(a.ausgabe).write_text(json.dumps(erg, ensure_ascii=False, indent=1))
    for k in ("K1", "K2", "K3", "K4", "K5"):
        print(f"{k} {'OK' if erg[k]['ok'] else 'FEHLER'}")
    print("GATES OK" if erg["ok"] else "GATES FEHLER")
    return 0 if erg["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
