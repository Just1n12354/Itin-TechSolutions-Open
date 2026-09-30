#!/usr/bin/env python3
"""Automatische Entscheidungen des Nachtlaufs 24./25.09.2026 (nur lesend, aus measurements/).

End-to-End-Score (E2E) eines Kandidaten gegen eine Basis = geometrisches Mittel der Zeitverhaeltnisse
Kandidat/Basis fuer die drei agentischen Wanduhr-Groessen, die Bens Alltag abbilden:
  g30_s (30 kurze Agentenschritte mit Tool-Calls), agent30_s (4-Schritt-Agent, 30k Kontext),
  agent80_s (4-Schritt-Agent, 80k Kontext).
Gewinn % = (1 - E2E) * 100.   Decode tok/s, TTFT und TTUA werden berichtet, entscheiden aber nicht allein.

Schutzregeln (jede Verletzung = Kandidat abgelehnt, egal wie schnell):
  - Qualitaet 12/12, agent30_ok und agent80_ok, G-Tool-Call-Rate nicht schlechter als die Basis
  - TTUA-p95 hoechstens +5 % gegen die Basis
  - keine Waechter-Ereignisse (der Sampler meldet dort Xid, Kernel-OOM, NV_ERR-Schuebe >=3/60 s, RAM, Swap-Schub),
    Messung vollstaendig. Einzelne NV_ERR_NO_MEMORY (auf GB10 beim Laden normal) nur als Warnung.
  - MemAvailable-Minimum hoechstens 1'024 MiB unter der Basis
Aufruf:
  entscheide.py paar <basis1> <kand1> <basis2> <kand2>   -> JSON {annehmen, gewinne, gruende}
  entscheide.py einzel <basis...> -- <kandidat>          -> Kandidat gegen Mittel der Basen
Exit 0 = annehmen, 1 = ablehnen, 2 = Daten fehlen.
"""
import json, math, pathlib, statistics as st, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from auswertung import zeile, M

SCHWELLE = 3.0          # % End-to-End je Paar
MITTEL_SCHWELLE = 5.0   # SGLang-Challenger (PLAN.md §7): Mittel beider Paare >= 5 %
TTFT_MAX = 10.0         # % Verschlechterung TTFT kalt 30k/80k
TTUA_P95_MAX = 5.0      # % Verschlechterung
MEM_TOLERANZ = 1024     # MiB
E2E_FELDER = ("g30_s", "agent30_s", "agent80_s")


def nverr(label):
    p = M / f"{label}.nverr.log"
    return sum(1 for _ in p.open()) if p.exists() else 0


def z(label):
    r = zeile(label)
    r["nverr"] = nverr(label)
    return r


def mittel(zeilen, k):
    w = [r.get(k) for r in zeilen if r.get(k) is not None]
    return st.mean(w) if w else None


def vergleich(basen, kand):
    """Kandidat-Zeile gegen Liste von Basis-Zeilen."""
    gruende, verh = [], []
    for f in E2E_FELDER:
        b, k = mittel(basen, f), kand.get(f)
        if b is None or k is None:
            return None, [f"Messwert {f} fehlt"]
        verh.append(k / b)
    e2e = math.exp(sum(math.log(v) for v in verh) / len(verh))
    gewinn = (1 - e2e) * 100
    if kand.get("qual") != "12/12":
        gruende.append(f"Qualitaet {kand.get('qual')}")
    if not (kand.get("agent30_ok") and kand.get("agent80_ok")):
        gruende.append("Agentenlauf falsch")
    if (kand.get("g_tool_ok") or 0) < min((b.get("g_tool_ok") or 0) for b in basen):
        gruende.append(f"Tool-Call-Rate {kand.get('g_tool_ok')}")
    tb, tk = mittel(basen, "ttua_p95"), kand.get("ttua_p95")
    if tb and tk and (tk / tb - 1) * 100 > TTUA_P95_MAX:
        gruende.append(f"TTUA-p95 {100 * (tk / tb - 1):+.1f} %")
    if kand.get("waechter"):
        gruende.append(f"Waechter: {kand['waechter'][:80]}")
    for f in ("ctx30_ttft_kalt", "ctx80_ttft_kalt"):
        b, k = mittel(basen, f), kand.get(f)
        if b and k and (k / b - 1) * 100 > TTFT_MAX:
            gruende.append(f"{f} {100 * (k / b - 1):+.1f} %")
    g = M / f"{kand['label']}.gates.json"
    if not (g.exists() and json.loads(g.read_text()).get("ok")):
        gruende.append("Korrektheits-Gates nicht bestanden")
    mb, mk = mittel(basen, "memavail_min"), kand.get("memavail_min")
    if mb and mk and mk < mb - MEM_TOLERANZ:
        gruende.append(f"MemAvailable-Min {mk} < Basis {mb:.0f} - {MEM_TOLERANZ}")
    return gewinn, gruende


def details(basen, kand):
    out = {}
    for f in ("decode_tok_s", "ttua_med", "ttua_p95", "g30_s", "agent30_s", "agent80_s",
              "ctx30_ttft_kalt", "ctx80_ttft_kalt", "ctx110_ttft_kalt", "acc_len_decode", "memavail_min"):
        b, k = mittel(basen, f), kand.get(f)
        if b and k:
            out[f] = {"basis": round(b, 3), "kandidat": k, "delta_%": round((k / b - 1) * 100, 1)}
    return out


def main():
    art = sys.argv[1]
    if art == "paar":
        b1, k1, b2, k2 = (z(x) for x in sys.argv[2:6])
        g1, gr1 = vergleich([b1], k1)
        g2, gr2 = vergleich([b2], k2)
        if g1 is None or g2 is None:
            print(json.dumps({"annehmen": False, "fehlend": gr1 + gr2})); sys.exit(2)
        annehmen = g1 >= SCHWELLE and g2 >= SCHWELLE and st.mean([g1, g2]) >= MITTEL_SCHWELLE and not gr1 and not gr2
        res = {"annehmen": annehmen, "gewinn_paar1_%": round(g1, 2), "gewinn_paar2_%": round(g2, 2),
               "gewinn_mittel_%": round(st.mean([g1, g2]), 2), "gruende": gr1 + gr2,
               "details_paar1": details([b1], k1), "details_paar2": details([b2], k2),
               "warnungen": [f"NV_ERR-Einzelmeldungen {r['label']}: {r['nverr']}" for r in (b1, k1, b2, k2) if r.get("nverr")]}
    elif art == "einzel":
        i = sys.argv.index("--")
        basen = [z(x) for x in sys.argv[2:i]]; kand = z(sys.argv[i + 1])
        g, gr = vergleich(basen, kand)
        if g is None:
            print(json.dumps({"annehmen": False, "fehlend": gr})); sys.exit(2)
        res = {"annehmen": g >= SCHWELLE and not gr, "gewinn_%": round(g, 2), "gruende": gr,
               "details": details(basen, kand),
               "warnungen": [f"NV_ERR-Einzelmeldungen {r['label']}: {r['nverr']}" for r in basen + [kand] if r.get("nverr")]}
    else:
        print(__doc__); sys.exit(2)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    sys.exit(0 if res["annehmen"] else 1)


if __name__ == "__main__":
    main()
