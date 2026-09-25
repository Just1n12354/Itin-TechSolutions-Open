#!/usr/bin/env python3
"""PLE-Page-Cache-Probe (aendert nichts): misst, ob Decode durch Major-Faults auf der
mmap-PLE-Tabelle gebremst wird.
Ablauf: Prompt P1 dreimal identisch (temperature 0 -> identische Tokens -> identische
PLE-Zeilen; ab Lauf 2 liegen sie im Page-Cache), dann Kontrolle P2 (neuer Text) einmal.
Je Lauf: Decode-tok/s, pgmajfault-Delta, NVMe-Lese-MiB (systemweit, System sonst ruhig).
Key nur aus VLLM_API_KEY."""
import json, os, sys, time, urllib.request
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
KEY = os.environ["VLLM_API_KEY"]

def vm(k):
    for z in open("/proc/vmstat"):
        a, b = z.split()
        if a == k: return int(b)
def nvme():
    for z in open("/proc/diskstats"):
        f = z.split()
        if f[2] == "nvme0n1": return int(f[5]) * 512 / 1048576

def lauf(prompt):
    req = urllib.request.Request(f"{URL}/v1/chat/completions", data=json.dumps({
        "model": "qwen3.8-flash-next", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400, "temperature": 0.0, "stream": True, "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False}}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    f0, n0 = vm("pgmajfault"), nvme(); t0 = time.perf_counter(); t1 = tl = None; n = 0; text = ""
    with urllib.request.urlopen(req, timeout=600) as r:
        for roh in r:
            z = roh.decode().strip()
            if not z.startswith("data:") or z[5:].strip() == "[DONE]": continue
            b = json.loads(z[5:])
            if b.get("usage"): n = b["usage"]["completion_tokens"]
            for c in b.get("choices", []):
                d = (c.get("delta") or {}).get("content")
                if d:
                    t = time.perf_counter() - t0; t1 = t1 or t; tl = t; text += d
    return {"tok": n, "decode_tok_s": round((n - 1) / (tl - t1), 2) if n > 1 and tl and tl > t1 else None,
            "majfault": vm("pgmajfault") - f0, "nvme_mib": round(nvme() - n0, 1),
            "majfault_je_token": round((vm("pgmajfault") - f0) / max(n, 1), 1), "text_hash": hash(text) & 0xffffffff}

P1 = ("Schreibe einen sachlichen Bericht von etwa 350 Woertern ueber die Geschichte der Eisenbahn in der "
      "Schweiz, mit Jahreszahlen, Strecken und technischen Details. Kein Markdown.")
P2 = ("Schreibe einen sachlichen Bericht von etwa 350 Woertern ueber die Entwicklung der Wasserkraft in "
      "Norwegen, mit Jahreszahlen, Anlagen und technischen Details. Kein Markdown.")
erg = {"P1": [lauf(P1) for _ in range(3)], "P2_kontrolle": [lauf(P2)]}
print(json.dumps(erg, indent=1))
