#!/usr/bin/env python3
"""Start-Timeline eines vLLM-Containers aus dem (maskierten) Container-Log (nur lesend).
Ausgabe JSON: Sekunden je Phase, gemessen an den Log-Zeitstempeln (vLLM: 'MM-DD HH:MM:SS').
Aufruf: startzeit.py <container.log>"""
import json, re, sys, datetime as dt
MARKEN = [("api_start", r"version \d"), ("engine_init", r"Initializing a V1 LLM engine"),
          ("gewichte_start", r"Loading safetensors checkpoint shards:\s+0% "), ("ple_mmap", r"PLE mmap: layer"),
          ("gewichte_haupt_fertig", r"Loading weights took"), ("modell_fertig", r"Model loading took"),
          ("compile_fertig", r"torch.compile took"), ("profil_fertig", r"Initial profiling/warmup run took"),
          ("kv_fertig", r"GPU KV cache size"), ("graphen_fertig", r"Graph capturing finished"),
          ("engine_fertig", r"init engine .* took"), ("mm_warmup_fertig", r"Multi-modal warmup completed"),
          ("api_bereit", r"Application startup complete")]
txt = open(sys.argv[1], newline="").read().replace("\r", " ")
zeiten = {}
for name, muster in MARKEN:
    for z in txt.split("\n"):
        if re.search(muster, z):
            iso = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", z)   # docker logs -t (bevorzugt)
            m = re.search(r"(\d\d-\d\d \d\d:\d\d:\d\d)", z)
            if iso:
                zeiten.setdefault(name, dt.datetime.strptime(iso.group(1), "%Y-%m-%dT%H:%M:%S"))
            elif m:
                zeiten.setdefault(name, dt.datetime.strptime("2026-" + m.group(1), "%Y-%m-%d %H:%M:%S"))
                if name != "gewichte_haupt_fertig":
                    break
t0 = zeiten.get("api_start")
out = {k: (v - t0).total_seconds() for k, v in zeiten.items()} if t0 else {}
m = re.findall(r"Loading weights took ([\d.]+) seconds", txt); out["gewichte_s"] = [float(x) for x in m]
m = re.search(r"init engine .* took ([\d.]+) s", txt); out["init_engine_s"] = float(m.group(1)) if m else None
print(json.dumps(out, indent=1))
