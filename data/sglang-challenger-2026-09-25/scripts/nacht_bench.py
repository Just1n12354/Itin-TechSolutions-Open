#!/usr/bin/env python3
"""Ergaenzungsmessung Nachtlauf 21./22.09.2026 - identisch fuer A und alle Kandidaten.

Ergaenzt tools/benchmark_gx10.py (Methodik 1.3: A-E, G) um das, was dort fehlt:
  ctx      Kontexte ~30k / ~80k / ~110k Tokens: TTFT kalt, TTFT mit Prefix-Treffer
           (angehaengter Turn wie bei Ben), Decode-Rate nach langem Kontext
  decode   reine Generierung, kurzer Prompt, 3 Wiederholungen
  agentctx Mehrschritt-Agent (3 Tool Calls + Abschluss) auf 30k und 80k Kontext
  qual     eingefrorenes Qualitaetsset scripts/qualitaet_v1.json (SHA256 im Bericht)
Zu jedem Teil: Delta der vLLM-Zaehler aus /metrics (Spec-Decode, Prefix-Cache).

Key: nur aus Umgebungsvariable VLLM_API_KEY. Wird nie ausgegeben oder gespeichert.
Aendert nichts am System - schickt nur Anfragen an --url.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, statistics, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

HIER = Path(__file__).resolve().parent
DOM = HIER.parents[2]                       # NvidiaDeveloper
KORPUS = sorted((DOM / "sources" / "text").glob("*.txt"))
QSET = HIER / "qualitaet_v1.json"
KEY = os.environ.get("VLLM_API_KEY", "").strip()
ZEITLIMIT = 900

def _post(url: str, nutzlast: dict, stream: bool = False, timeout: int = ZEITLIMIT):
    req = urllib.request.Request(url, data=json.dumps(nutzlast).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)

# ---------------------------------------------------------------- Metriken
ZAEHLER = ("vllm:spec_decode_num_drafts_total", "vllm:spec_decode_num_draft_tokens_total",
           "vllm:spec_decode_num_accepted_tokens_total", "vllm:prefix_cache_queries_total",
           "vllm:prefix_cache_hits_total", "vllm:prompt_tokens_total",
           "vllm:generation_tokens_total", "vllm:num_preemptions_total")

def metriken(basis: str) -> dict:
    try:
        text = urllib.request.urlopen(f"{basis}/metrics", timeout=10).read().decode()
    except Exception as e:
        return {"fehler": str(e)}
    werte: dict = {}
    for z in text.splitlines():
        if z.startswith("#"):
            continue
        m = re.match(r'^([a-zA-Z_:]+)(\{[^}]*\})?\s+([0-9.eE+-]+)$', z)
        if not m:
            continue
        name, labels, wert = m.group(1), m.group(2) or "", float(m.group(3))
        if name in ZAEHLER:
            werte[name] = werte.get(name, 0.0) + wert
        elif name == "vllm:spec_decode_num_accepted_tokens_per_pos_total":
            pos = re.search(r'position="(\d+)"', labels)
            if pos:
                k = f"accepted_pos{pos.group(1)}"
                werte[k] = werte.get(k, 0.0) + wert
    return werte

def delta(vor: dict, nach: dict) -> dict:
    d = {k: round(nach.get(k, 0) - vor.get(k, 0), 1) for k in set(vor) | set(nach)
         if isinstance(nach.get(k, 0), float)}
    drafts = d.get("vllm:spec_decode_num_drafts_total", 0)
    dtok = d.get("vllm:spec_decode_num_draft_tokens_total", 0)
    acc = d.get("vllm:spec_decode_num_accepted_tokens_total", 0)
    q = d.get("vllm:prefix_cache_queries_total", 0)
    h = d.get("vllm:prefix_cache_hits_total", 0)
    return {
        "roh": d,
        "mtp_acceptance_rate": round(acc / dtok, 4) if dtok else None,
        # mittlere akzeptierte Laenge je Verifikationsschritt inkl. des Bonus-Tokens
        "mtp_acceptance_length": round(1 + acc / drafts, 3) if drafts else None,
        "prefix_hit_rate": round(h / q, 4) if q else None,
    }

# ---------------------------------------------------------------- Anfrage
def chat(basis: str, modell: str, messages: list, max_tokens: int, tools=None,
         temperatur: float = 0.0, thinking: bool | None = None) -> dict:
    nutz = {"model": modell, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperatur, "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        nutz["tools"] = tools; nutz["tool_choice"] = "auto"
    if thinking is not None:
        nutz["chat_template_kwargs"] = {"enable_thinking": thinking}
    e = {"fehler": None, "t_erstes_token_s": None, "t_reasoning_s": None, "t_content_s": None,
         "t_tool_s": None, "dauer_s": None, "prompt_tokens": None, "completion_tokens": None,
         "finish_reason": None, "content": "", "tool_calls": []}
    t0 = time.perf_counter(); tc: dict = {}; t_last = None
    try:
        with _post(f"{basis}/v1/chat/completions", nutz, stream=True) as r:
            for roh in r:
                z = roh.decode("utf-8", "ignore").strip()
                if not z.startswith("data:"):
                    continue
                rest = z[5:].strip()
                if rest == "[DONE]":
                    break
                b = json.loads(rest)
                if b.get("usage"):
                    e["prompt_tokens"] = b["usage"].get("prompt_tokens")
                    e["completion_tokens"] = b["usage"].get("completion_tokens")
                for c in b.get("choices", []):
                    d = c.get("delta") or {}
                    jetzt = time.perf_counter() - t0
                    hat = False
                    if d.get("reasoning_content") or d.get("reasoning"):
                        hat = True; e["t_reasoning_s"] = e["t_reasoning_s"] or jetzt
                    if d.get("content"):
                        hat = True; e["t_content_s"] = e["t_content_s"] or jetzt
                        e["content"] += d["content"]
                    for t in d.get("tool_calls") or []:
                        hat = True; e["t_tool_s"] = e["t_tool_s"] or jetzt
                        s = tc.setdefault(t.get("index", 0), {"name": "", "args": ""})
                        f = t.get("function") or {}
                        s["name"] += f.get("name") or ""; s["args"] += f.get("arguments") or ""
                    if hat:
                        e["t_erstes_token_s"] = e["t_erstes_token_s"] or jetzt
                        t_last = jetzt
                    if c.get("finish_reason"):
                        e["finish_reason"] = c["finish_reason"]
    except Exception as ex:
        e["fehler"] = f"{type(ex).__name__}: {ex}"[:300]
    e["dauer_s"] = round(time.perf_counter() - t0, 3)
    for i in sorted(tc):
        try:
            args = json.loads(tc[i]["args"]) if tc[i]["args"] else {}
        except Exception:
            args = {"_ungueltig": tc[i]["args"][:200]}
        e["tool_calls"].append({"name": tc[i]["name"], "args": args})
    n = e["completion_tokens"]
    if n and n > 1 and e["t_erstes_token_s"] is not None and t_last and t_last > e["t_erstes_token_s"]:
        e["decode_tok_s"] = round((n - 1) / (t_last - e["t_erstes_token_s"]), 2)
    else:
        e["decode_tok_s"] = None
    for k in ("t_erstes_token_s", "t_reasoning_s", "t_content_s", "t_tool_s"):
        if e[k] is not None:
            e[k] = round(e[k], 3)
    return e

def tokenzahl(basis: str, modell: str, text: str) -> int:
    with _post(f"{basis}/tokenize", {"model": modell, "prompt": text}, timeout=120) as r:
        return int(json.loads(r.read())["count"])

_KORPUS_TEXT = None
def korpus() -> str:
    global _KORPUS_TEXT
    if _KORPUS_TEXT is None:
        _KORPUS_TEXT = "\n\n".join(p.read_text(errors="ignore") for p in KORPUS)
    return _KORPUS_TEXT

# SGLang-Challenger 25.09.2026: /tokenize gibt es nur bei vLLM. Die Dokumente entstehen einmal (Lauf G1, GoldVllm)
# und liegen danach im Zwischenspeicher - alle Laeufe beider Runtimes bekommen byte-gleiche Texte.
DOKCACHE = Path(os.environ.get("DOKCACHE", str(HIER.parent / "measurements" / "dokumente_cache.json")))

def dokument(basis: str, modell: str, ziel_tokens: int, versatz: int) -> str:
    schl = f"{ziel_tokens}:{versatz}"
    cache = json.loads(DOKCACHE.read_text()) if DOKCACHE.is_file() else {}
    if schl in cache:
        return cache[schl]
    text = _dokument_kalibriert(basis, modell, ziel_tokens, versatz)
    cache[schl] = text; DOKCACHE.write_text(json.dumps(cache))
    return text

def _dokument_kalibriert(basis: str, modell: str, ziel_tokens: int, versatz: int) -> str:
    """Text mit ~ziel_tokens Tokens ab Versatz (zyklisch), per /tokenize kalibriert."""
    k = korpus(); zeichen = int(ziel_tokens * 3.6)
    for _ in range(4):
        roh = (k[versatz % len(k):] + "\n\n" + k) * 2
        text = roh[:zeichen]
        n = tokenzahl(basis, modell, text)
        if abs(n - ziel_tokens) / ziel_tokens < 0.02:
            break
        zeichen = int(zeichen * ziel_tokens / max(n, 1))
    return text

# ---------------------------------------------------------------- Teile
def teil_ctx(basis, modell, label):
    aus = []
    for i, ziel in enumerate((30000, 80000, 110000)):
        doc = dokument(basis, modell, ziel, versatz=37_000 * (i + 1))
        kopf = f"[Messlauf {label} ctx{ziel}]\n"
        msgs = [{"role": "system", "content": "Du bist ein genauer Assistent."},
                {"role": "user", "content": kopf + doc + "\n\nFasse den Text in drei Saetzen zusammen."}]
        m0 = metriken(basis); kalt = chat(basis, modell, msgs, 256); m1 = metriken(basis)
        msgs2 = msgs + [{"role": "assistant", "content": kalt["content"] or "..."},
                        {"role": "user", "content": "Nenne jetzt zwei konkrete Zahlen aus dem Text."}]
        warm = chat(basis, modell, msgs2, 256); m2 = metriken(basis)
        aus.append({"ziel_tokens": ziel, "kalt": kalt, "kalt_metriken": delta(m0, m1),
                    "warm_turn": warm, "warm_metriken": delta(m1, m2)})
        print(f"   ctx {ziel}: prompt={kalt['prompt_tokens']} TTFT kalt={kalt['t_erstes_token_s']}s "
              f"warm={warm['t_erstes_token_s']}s decode={kalt['decode_tok_s']}/{warm['decode_tok_s']} tok/s "
              f"finish={kalt['finish_reason']}/{warm['finish_reason']} fehler={kalt['fehler'] or warm['fehler']}", flush=True)
    return aus

def teil_decode(basis, modell, label):
    aus = []
    for i in range(3):
        msgs = [{"role": "user", "content": f"[{label}-{i}] Erklaere ausfuehrlich in mindestens 400 Woertern, "
                 "wie ein Wechselrichter in einer Photovoltaikanlage funktioniert."}]
        m0 = metriken(basis); r = chat(basis, modell, msgs, 512); m1 = metriken(basis)
        r.pop("content", None); aus.append({"lauf": i, "ergebnis": r, "metriken": delta(m0, m1)})
        print(f"   decode {i}: {r['decode_tok_s']} tok/s, {r['completion_tokens']} tok, "
              f"accept={aus[-1]['metriken']['mtp_acceptance_rate']}", flush=True)
    return aus

AGENT_TOOLS = [
    {"type": "function", "function": {"name": "datei_groesse", "description": "Groesse einer Datei in Bytes.",
      "parameters": {"type": "object", "properties": {"pfad": {"type": "string"}}, "required": ["pfad"]}}},
    {"type": "function", "function": {"name": "fertig", "description": "Meldet das Endergebnis und beendet die Aufgabe.",
      "parameters": {"type": "object", "properties": {"antwort": {"type": "string"}}, "required": ["antwort"]}}}]
AGENT_GROESSEN = {"/projekt/a.txt": 1200, "/projekt/b.txt": 3400, "/projekt/c.txt": 5600}

def teil_agentctx(basis, modell, label):
    aus = []
    for i, ziel in enumerate((30000, 80000)):
        doc = dokument(basis, modell, ziel, versatz=211_000 + 53_000 * i)
        msgs = [{"role": "system", "content": f"[Agentlauf {label} ctx{ziel}] Du bist Ben, ein Agent. "
                 "Arbeite ausschliesslich ueber Werkzeuge, ein Aufruf pro Schritt. Projektunterlagen:\n\n" + doc},
                {"role": "user", "content": "Ermittle nacheinander die Groessen von /projekt/a.txt, /projekt/b.txt "
                 "und /projekt/c.txt (je ein Werkzeugaufruf pro Schritt). Melde danach die Summe in Bytes "
                 "mit dem Werkzeug fertig."}]
        schritte = []; t0 = time.perf_counter(); m0 = metriken(basis); ergebnis = None
        for s in range(8):
            r = chat(basis, modell, msgs, 2000, tools=AGENT_TOOLS)
            ttua = r["t_tool_s"] or r["t_content_s"]
            schritte.append({"schritt": s, "ttua_s": ttua, "dauer_s": r["dauer_s"], "prompt_tokens": r["prompt_tokens"],
                             "completion_tokens": r["completion_tokens"], "finish": r["finish_reason"],
                             "tools": r["tool_calls"], "fehler": r["fehler"]})
            if r["fehler"] or not r["tool_calls"]:
                break
            call = r["tool_calls"][0]; cid = f"call_{s}"
            msgs.append({"role": "assistant", "content": r["content"] or None,
                         "tool_calls": [{"id": cid, "type": "function",
                                         "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}]})
            if call["name"] == "fertig":
                ergebnis = str(call["args"].get("antwort", "")); break
            wert = AGENT_GROESSEN.get(str(call["args"].get("pfad", "")), "FEHLER: unbekannte Datei")
            msgs.append({"role": "tool", "tool_call_id": cid, "content": str(wert)})
        dauer = time.perf_counter() - t0; m1 = metriken(basis)
        pfade = [c["args"].get("pfad") for st in schritte for c in st["tools"] if c["name"] == "datei_groesse"]
        korrekt = (pfade == list(AGENT_GROESSEN) and ergebnis is not None
                   and re.sub(r"[ '.,]", "", ergebnis).find("10200") >= 0)
        ttuas = [s["ttua_s"] for s in schritte if s["ttua_s"] is not None]
        aus.append({"ziel_tokens": ziel, "korrekt": korrekt, "pfade": pfade, "ergebnis": ergebnis,
                    "schritte": schritte, "gesamt_s": round(dauer, 2),
                    "ttua_median_s": round(statistics.median(ttuas), 3) if ttuas else None,
                    "ttua_warm_median_s": round(statistics.median(ttuas[1:]), 3) if len(ttuas) > 1 else None,
                    "metriken": delta(m0, m1)})
        print(f"   agentctx {ziel}: korrekt={korrekt} schritte={len(schritte)} gesamt={dauer:.1f}s "
              f"TTUA erster={ttuas[0] if ttuas else None} warm-median={aus[-1]['ttua_warm_median_s']} "
              f"hit={aus[-1]['metriken']['prefix_hit_rate']}", flush=True)
    return aus

def _enthaelt(text: str, varianten: list) -> bool:
    t = text.lower()
    return any(v.lower() in t for v in varianten)

def teil_qual(basis, modell, label):
    q = json.loads(QSET.read_text()); tools = q["werkzeuge"]; mt = q["sampling"]["max_tokens"]
    aus = []; punkte = 0
    for a in q["aufgaben"]:
        msgs = [{"role": "system", "content": q["system"]}]
        ok = False; det: dict = {"id": a["id"]}
        if a["art"] == "nadel":
            doc = dokument(basis, modell, a["kontext_tokens"], versatz=301_000)
            p = int(len(doc) * a["position"]); doc = doc[:p] + "\n" + a["nadel"] + "\n" + doc[p:]
            msgs.append({"role": "user", "content": "Unterlagen:\n" + doc + "\n\n" + a["user_frage"]})
            r = chat(basis, modell, msgs, mt, tools=tools)
            ok = not r["tool_calls"] and _enthaelt(r["content"], a["erwartet"]["enthaelt_eins"])
            det.update(finish=r["finish_reason"], antwort=r["content"][-200:], tools=r["tool_calls"])
        elif a["art"] in ("tool", "ohne_tool"):
            msgs.append({"role": "user", "content": a["user"]})
            r = chat(basis, modell, msgs, mt, tools=tools)
            det.update(finish=r["finish_reason"], tools=r["tool_calls"], antwort=r["content"][-200:])
            if a["art"] == "tool":
                e = a["erwartet"]
                ok = (len(r["tool_calls"]) >= 1 and r["tool_calls"][0]["name"] == e["name"]
                      and e["enthaelt"].lower() in str(r["tool_calls"][0]["args"].get(e["arg"], "")).lower())
            else:
                ok = not r["tool_calls"] and _enthaelt(r["content"], a["erwartet"]["enthaelt_eins"])
        elif a["art"] == "mehrschritt":
            msgs.append({"role": "user", "content": a["user"]}); e = a["erwartet"]; aufrufe = []; final = ""
            for s in range(e["max_schritte"]):
                r = chat(basis, modell, msgs, mt, tools=tools)
                if r["fehler"] or not r["tool_calls"]:
                    final = r["content"]; det["finish"] = r["finish_reason"]; break
                c = r["tool_calls"][0]; cid = f"q{s}"; aufrufe.append(c["args"].get("pfad"))
                msgs.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}]})
                msgs.append({"role": "tool", "tool_call_id": cid,
                             "content": a["werkzeug_ergebnisse"].get(str(c["args"].get("pfad")), "FEHLER: unbekannt")})
            wdh = max([aufrufe.count(x) for x in set(aufrufe)] or [0])
            ok = (aufrufe[:len(e["aufrufe"])] == e["aufrufe"] and _enthaelt(final, e["enthaelt_eins"])
                  and wdh <= e.get("max_wiederholung", 1))
            det.update(aufrufe=aufrufe, antwort=final[-200:], wiederholung_max=wdh)
        det["ok"] = ok; punkte += ok; aus.append(det)
        print(f"   qual {a['id']}: {'OK' if ok else 'FEHLER'} finish={det.get('finish')}", flush=True)
    return {"qset_sha256": hashlib.sha256(QSET.read_bytes()).hexdigest(), "punkte": punkte,
            "von": len(q["aufgaben"]), "details": aus,
            "laengen_abbrueche": sum(1 for d in aus if d.get("finish") == "length")}

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--label", required=True)
    p.add_argument("--teile", default="decode,ctx,agentctx,qual")
    p.add_argument("--ausgabe", required=True)
    a = p.parse_args()
    if not KEY:
        print("VLLM_API_KEY fehlt"); return 2
    req = urllib.request.Request(f"{a.url}/v1/models", headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        modell = json.loads(r.read())["data"][0]["id"]
    bericht = {"werkzeug": "nacht_bench.py", "label": a.label, "url": a.url, "modell": modell,
               "start": datetime.now().astimezone().isoformat(timespec="seconds"),
               "metriken_start": metriken(a.url), "teile": {}}
    for t in a.teile.split(","):
        print(f"== {t} ==", flush=True); t0 = time.perf_counter()
        bericht["teile"][t] = globals()[f"teil_{t}"](a.url, modell, a.label)
        bericht.setdefault("dauer_s", {})[t] = round(time.perf_counter() - t0, 1)
        Path(a.ausgabe).write_text(json.dumps(bericht, indent=1, ensure_ascii=False))
    bericht["metriken_ende"] = metriken(a.url)
    bericht["gesamt_metriken"] = delta(bericht["metriken_start"], bericht["metriken_ende"])
    bericht["ende"] = datetime.now().astimezone().isoformat(timespec="seconds")
    Path(a.ausgabe).write_text(json.dumps(bericht, indent=1, ensure_ascii=False))
    print("gesamt:", json.dumps(bericht["gesamt_metriken"]["mtp_acceptance_rate"]),
          bericht["gesamt_metriken"]["mtp_acceptance_length"], bericht["gesamt_metriken"]["prefix_hit_rate"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
