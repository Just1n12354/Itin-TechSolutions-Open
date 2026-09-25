#!/usr/bin/env python3
"""Vorkonditionierung eines frisch gestarteten vLLM-Containers vor einer Messung.

WARUM DAS NOETIG IST (GEMESSEN, 21.09.2026)
Methodik 1.3 bricht ab, sobald der Swap waehrend eines Laufs um mehr als 2048 MB
waechst. Ein frisch gestarteter Container reisst diese Grenze: die 48-GiB-PLE-
Tabelle wird per mmap von der Platte gelesen, der Page-Cache ist kalt, und der
wachsende Cache drueckt anonyme Seiten in den Swap. Im ersten Versuch wuchs der
Swap waehrend C_lang und D_prefix_kalt um 3298 MB (8117 -> 11440 MB); alle Tests
ab D_prefix_warm lieferten deshalb keinen Wert.

Der Step-2-Lauf von Kandidat A traf die Grenze nicht - nicht weil er besser war,
sondern weil er gegen einen 9 Stunden warmen Produktionscontainer lief, dessen
Swap sich laengst eingependelt hatte (10254 -> 11285 MB, also +1031 MB).

Dieses Werkzeug stellt denselben eingependelten Zustand her, bevor gemessen wird.
Es aendert NICHTS an der Methodik 1.3: gleiches Messwerkzeug, gleiche Prompts,
gleiche Schwellen. Es stellt nur die Ausgangsbedingung her, die der Step-2-Lauf
von sich aus hatte - und zwar fuer jeden Arm des Vergleichs gleich.

KEINE VERUNREINIGUNG DES PREFIX-CACHES
Der Benchmark zieht seine Prompts aus sources/text/DGX_Spark_User_Guide.txt.
Dieses Werkzeug nimmt bewusst eine ANDERE Datei des Korpus, damit kein einziger
Prefix, den der Benchmark spaeter als "kalt" misst, hier schon warmgelaufen ist.
Jede Runde nimmt einen anderen Versatz, sonst antwortet der Prefix-Cache und es
wird gar nicht geprefillt - dann wandert auch die PLE-Tabelle nicht durch.

Der API-Key wird nie ausgegeben.

    tools/aufwaermen.py --container bench-flash-nomtp
"""
import argparse, json, os, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

DOMAENE = Path(__file__).resolve().parents[2]     # Domaene "Nvidia Gx10" (Korpus in sources/)
# Bewusst NICHT die Datei, aus der benchmark_gx10.py seine Prompts zieht.
QUELLE = Path(os.environ.get("AUFWAERMTEXT", str(DOMAENE / "sources" / "text" / "DGX_Spark_Playbook_vLLM.txt")))  # optional, sonst Platzhaltertext
BASIS_URL = os.environ.get("VLLM_BASIS_URL", "http://127.0.0.1:8000")


def swap_mb() -> int:
    m = {}
    for z in open("/proc/meminfo"):
        k, v = z.split(":")
        m[k] = int(v.split()[0]) // 1024
    return m["SwapTotal"] - m["SwapFree"]


def ram_mb() -> int:
    for z in open("/proc/meminfo"):
        if z.startswith("MemAvailable:"):
            return int(z.split()[1]) // 1024
    return 0


def schluessel(container: str) -> str:
    roh = subprocess.run(["docker", "inspect", container, "--format",
                          "{{range .Config.Cmd}}{{println .}}{{end}}"],
                         capture_output=True, text=True).stdout
    z = [x for x in roh.splitlines() if x.strip()]
    return z[z.index("--api-key") + 1].strip() if "--api-key" in z else ""


def text(zeichen: int, versatz: int) -> str:
    roh = QUELLE.read_text(encoding="utf-8", errors="ignore") if QUELLE.is_file() \
        else "GB10 Grace Blackwell NVLink-C2C. " * 4000
    if len(roh) < zeichen + versatz:
        roh = roh * ((zeichen + versatz) // max(len(roh), 1) + 2)
    return roh[versatz:versatz + zeichen]


def anfrage(key: str, modell: str, prompt: str, max_tokens: int = 16) -> bool:
    last = json.dumps({"model": modell,
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "temperature": 0.0,
                       "stream": False}).encode()
    req = urllib.request.Request(f"{BASIS_URL}/v1/chat/completions", data=last,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as a:
            a.read()
        return True
    except Exception as f:
        print(f"   Anfrage fehlgeschlagen: {type(f).__name__}", flush=True)
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--container", required=True)
    p.add_argument("--hoechstdauer", type=int, default=1200, help="Sekunden (Standard 1200)")
    p.add_argument("--ruhe-mb", type=int, default=200,
                   help="erlaubter Swap-Zuwachs je Ruhefenster")
    p.add_argument("--ruhe-ram-mb", type=int, default=1500,
                   help="erlaubte RAM-Schwankung je Ruhefenster")
    p.add_argument("--fenster", type=int, default=6, help="Runden je Ruhefenster")
    p.add_argument("--min-runden", type=int, default=12,
                   help="so viele Runden mindestens, egal wie ruhig es aussieht")
    p.add_argument("--min-dauer", type=int, default=300,
                   help="so viele Sekunden mindestens")
    p.add_argument("--zeichen", type=int, default=64_000,
                   help="Promptlaenge je Runde (Standard 64000, wie Test C_lang)")
    a = p.parse_args()

    key = schluessel(a.container)
    if not key:
        print("kein Key im Container gefunden - Abbruch"); return 1
    req = urllib.request.Request(f"{BASIS_URL}/v1/models",
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        modell = json.loads(r.read())["data"][0]["id"]

    print(f"Vorkonditionierung {a.container}, Modell {modell}")
    print(f"Quelle: {QUELLE.name} (bewusst nicht die Benchmarkquelle)")
    print(f"Start: Swap {swap_mb()} MB, RAM verfuegbar {ram_mb()} MB", flush=True)

    # Abbruchkriterium bewusst streng: der erste Entwurf brach schon nach 26 s ab,
    # weil der Swap zwischen zwei Prefills kurz flach liegt. Das Gleichgewicht auf
    # dieser Maschine liegt bei rund 11 GB Swap; von 8 GB aus sind das etwa 3 GB,
    # die wandern muessen - waehrend der Messung reissen sie jede Grenze. Deshalb:
    # Mindestrundenzahl, Mindestdauer, langes Ruhefenster und RAM als zweites
    # Kriterium (der erste Paarlauf war im Swap symmetrisch und im RAM um 5.5 GB
    # auseinander - genau daran ist der MTP-Arm gescheitert).
    begonnen = time.time()
    swapverlauf = [swap_mb()]
    ramverlauf = [ram_mb()]
    runde = 0
    ruhig = False
    while time.time() - begonnen < a.hoechstdauer:
        runde += 1
        # Jede Runde ein anderer Versatz: erzwingt echtes Prefill statt Cache-Treffer.
        anfrage(key, modell, text(a.zeichen, versatz=runde * 7_919) +
                "\n\nNenne ein Stichwort.", 16)
        sw, r = swap_mb(), ram_mb()
        swapverlauf.append(sw); ramverlauf.append(r)
        print(f"   Runde {runde:2d}  t={int(time.time()-begonnen):4d}s  "
              f"Swap {sw} MB  RAM {r} MB", flush=True)
        if runde < a.min_runden or time.time() - begonnen < a.min_dauer:
            continue
        if len(swapverlauf) <= a.fenster:
            continue
        ds = swapverlauf[-1] - swapverlauf[-1 - a.fenster]
        dr = max(ramverlauf[-a.fenster:]) - min(ramverlauf[-a.fenster:])
        if abs(ds) <= a.ruhe_mb and dr <= a.ruhe_ram_mb:
            print(f"   eingependelt nach {runde} Runden: Swap {ds:+d} MB, "
                  f"RAM-Spanne {dr} MB ueber {a.fenster} Runden")
            ruhig = True
            break
    if not ruhig:
        print("   Hoechstdauer erreicht, ohne dass sich Swap und RAM eingependelt haben")

    print(f"Ende:  Swap {swap_mb()} MB, RAM verfuegbar {ram_mb()} MB, "
          f"{runde} Runden, {int(time.time()-begonnen)} s")
    print(f"Swap-Verlauf: {swapverlauf}")
    print(f"RAM-Verlauf:  {ramverlauf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
