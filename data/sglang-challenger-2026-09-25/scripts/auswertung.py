#!/usr/bin/env python3
"""Verdichtet die Messdateien eines Labels zu einer Zeile der Master-Tabelle.
   auswertung.py A0 B_v029 ...        -> Markdown-Tabellen auf stdout
   auswertung.py --json A0 B_v029     -> JSON
Quellen je Label: measurements/<L>.bench13.json, <L>.nacht.json, <L>.sampler.csv, <L>.start.json"""
import csv, json, statistics as st, sys
from pathlib import Path
M = Path(__file__).resolve().parent.parent / "measurements"

def lade(p):
    try: return json.loads(p.read_text())
    except Exception: return None

def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None

def zeile(label):
    r = {"label": label}
    b = lade(M / f"{label}.bench13.json"); n = lade(M / f"{label}.nacht.json"); s = lade(M / f"{label}.start.json")
    if b:
        t = {x.get("test"): x for x in b.get("tests", [])}
        g = t.get("G_agent", {})
        r["g30_s"] = g.get("gesamtdauer_s"); r["ttua_med"] = (g.get("time_to_useful_action_s") or {}).get("median")
        r["ttua_p95"] = (g.get("time_to_useful_action_s") or {}).get("p95"); r["g_tool_ok"] = g.get("tool_call_erfolgsrate")
        for k in (1, 2, 4):
            r[f"tp{k}"] = (t.get(f"E_parallel_{k}") or {}).get("generation_tokens_s_summe")
        r["c_lang_ttft"] = (t.get("C_lang") or {}).get("ttft_s"); r["c_lang_gen"] = (t.get("C_lang") or {}).get("generation_tokens_s")
        r["d_kalt"] = (t.get("D_prefix_kalt") or {}).get("ttft_s"); r["d_warm"] = (t.get("D_prefix_warm") or {}).get("ttft_s")
        r["a_kurz_gen"] = (t.get("A_kurz") or {}).get("generation_tokens_s")
        r["bench_fehler"] = sum(1 for x in b.get("tests", []) if x.get("fehler") or x.get("abgebrochen"))
        v = b.get("vllm", {}); r["kv_tokens"] = v.get("kv_cache_kapazitaet_tokens")
    if n:
        te = n.get("teile", {})
        dec = te.get("decode") or []
        r["decode_tok_s"] = med([d["ergebnis"].get("decode_tok_s") for d in dec])
        acc = [d["metriken"] for d in dec]
        r["acc_rate_decode"] = med([a.get("mtp_acceptance_rate") for a in acc])
        r["acc_len_decode"] = med([a.get("mtp_acceptance_length") for a in acc])
        g = n.get("gesamt_metriken", {})
        r["acc_rate_ges"] = g.get("mtp_acceptance_rate"); r["acc_len_ges"] = g.get("mtp_acceptance_length")
        r["prefix_hit_ges"] = g.get("prefix_hit_rate")
        for c in te.get("ctx") or []:
            z = c["ziel_tokens"] // 1000
            r[f"ctx{z}_ttft_kalt"] = c["kalt"].get("t_erstes_token_s"); r[f"ctx{z}_ttft_warm"] = c["warm_turn"].get("t_erstes_token_s")
            r[f"ctx{z}_dec"] = c["kalt"].get("decode_tok_s"); r[f"ctx{z}_hit_warm"] = c["warm_metriken"].get("prefix_hit_rate")
            r[f"ctx{z}_prompt"] = c["kalt"].get("prompt_tokens")
            r[f"ctx{z}_fehler"] = c["kalt"].get("fehler") or c["warm_turn"].get("fehler")
        for a in te.get("agentctx") or []:
            z = a["ziel_tokens"] // 1000
            r[f"agent{z}_s"] = a.get("gesamt_s"); r[f"agent{z}_ok"] = a.get("korrekt")
            r[f"agent{z}_ttua_warm"] = a.get("ttua_warm_median_s"); r[f"agent{z}_hit"] = a["metriken"].get("prefix_hit_rate")
            r[f"agent{z}_ttua_erster"] = (a["schritte"][0].get("ttua_s") if a.get("schritte") else None)
        q = te.get("qual")
        if q: r["qual"] = f'{q["punkte"]}/{q["von"]}'; r["qual_length"] = q.get("laengen_abbrueche")
    if s: r["ready_s"] = s.get("time_to_ready_s")
    p = M / f"{label}.sampler.csv"
    if p.exists():
        rows = list(csv.DictReader(p.open()))
        if rows:
            ma = [int(x["memavail_mib"]) for x in rows]; sw = [int(x["swap_used_mib"]) for x in rows]
            last = rows[-1]; first = rows[0]
            r["memavail_min"] = min(ma); r["memavail_med"] = int(st.median(ma))
            r["swap_max"] = max(sw); r["pswpout_delta_mib"] = (int(last["pswpout"]) - int(first["pswpout"])) * 4 // 1024
            r["pswpin_delta_mib"] = (int(last["pswpin"]) - int(first["pswpin"])) * 4 // 1024
            last_ok = [x for x in rows if x["gpu_w"] not in ("", "[N/A]")]
            aktiv = [x for x in last_ok if float(x["gpu_util"] or 0) >= 50]
            r["power_med_aktiv"] = med([float(x["gpu_w"]) for x in aktiv]); r["power_max"] = max(float(x["gpu_w"]) for x in last_ok) if last_ok else None
            r["temp_max"] = max(int(x["gpu_c"]) for x in last_ok) if last_ok else None
            r["throttle_nonzero"] = sum(1 for x in rows if x.get("throttle") not in ("0x0000000000000000", "", None))
            r["nvme_read_gib"] = round(sum(float(x["nvme_read_mib"]) for x in rows) / 1024, 1)
            r["majfault_delta"] = int(last["pgmajfault"]) - int(first["pgmajfault"])
    ev = M / f"{label}.ereignisse.log"
    r["waechter"] = ev.read_text().strip().replace("\n", " | ") if ev.exists() and ev.stat().st_size else ""
    return r

def main():
    args = sys.argv[1:]; js = "--json" in args; labels = [a for a in args if a != "--json"]
    rows = [zeile(l) for l in labels]
    if js:
        print(json.dumps(rows, indent=1)); return
    spalten = ["label", "g30_s", "ttua_med", "ttua_p95", "g_tool_ok", "decode_tok_s", "tp1", "tp2", "tp4",
               "acc_rate_decode", "acc_len_decode", "prefix_hit_ges", "agent30_s", "agent30_ttua_warm", "agent30_hit",
               "agent80_s", "agent80_ttua_warm", "ctx30_ttft_kalt", "ctx80_ttft_kalt", "ctx110_ttft_kalt",
               "ctx110_dec", "qual", "memavail_min", "swap_max", "pswpout_delta_mib", "power_med_aktiv", "temp_max",
               "ready_s", "waechter"]
    print("| " + " | ".join(spalten) + " |"); print("|" + "---|" * len(spalten))
    for r in rows:
        print("| " + " | ".join(str(r.get(s, "")) for s in spalten) + " |")

if __name__ == "__main__":
    main()
