# -*- coding: utf-8 -*-
"""Reproduzierbare Leistungs-Baseline des lokalen vLLM auf DGX Spark / GB10.

Warum es das gibt: Bis zum 21.09.2026 gab es auf gx10 keinen Benchmark. Darum
fiel monatelang niemandem auf, dass die Maschine bei ~20 Token/s laeuft und
swappt. Wer ohne Baseline optimiert, misst hinterher gegen ein Gefuehl.

Dieses Werkzeug **aendert nichts**. Es liest, misst und schreibt genau eine
Datei: `messungen/baseline-gx10.json`. Keine Container, keine Units, keine Flags.

Der API-Key wird zur Laufzeit ermittelt (Umgebungsvariable VLLM_API_KEY, sonst
aus dem Container-Cmd) und **niemals ausgegeben, protokolliert oder gespeichert**.

    python tools/benchmark_gx10.py --nur-umgebung     # nur Inventar, keine Last
    python tools/benchmark_gx10.py --nur-schnell      # Tests A-E ohne Dauerlast
    python tools/benchmark_gx10.py                    # alles, inkl. 10 min Dauerlast
    python tools/benchmark_gx10.py --tabelle          # Baseline aus JSON neu drucken
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GX10 = Path(__file__).resolve().parent.parent      # GoldVllm (bzw. betrieb)
DOMAENE = GX10.parent                             # Domaene "Nvidia Gx10" (Korpus in sources/)
ZIEL = GX10 / "messungen" / "baseline-gx10.json"
# Fuelltext fuer lange Prompts: FUELLTEXT=<datei.txt> setzen (GoldVllm-Messungen: NVIDIA DGX Spark User Guide als Text,
# aus Lizenzgruenden nicht im Repo). Andere Texte ergeben vergleichbare, aber nicht identische Zahlen.
FUELLTEXT = Path(os.environ.get("FUELLTEXT", str(DOMAENE / "sources" / "text" / "DGX_Spark_User_Guide.txt")))

BASIS_URL = os.environ.get("VLLM_BASIS_URL", "http://127.0.0.1:8000")
CONTAINER = os.environ.get("VLLM_CONTAINER", "qwen38-flash")

# --- Sicherheitsgrenzen -----------------------------------------------------
# Die Maschine darf durch die Messung nicht in OOM laufen. Beide Werte werden
# vor jeder Anfragegruppe und waehrend der Dauerlast geprueft.
# Sicherheitsgrenzen. Die Standardwerte sind die der Fassung 1.3 und bleiben
# unveraendert; ohne gesetzte Umgebungsvariablen verhaelt sich das Werkzeug exakt
# wie in Step 2.
#
# WARUM UEBERSCHREIBBAR (GEMESSEN, 21.09.2026): Auf gx10 mappt der vLLM-Dienst eine
# 48-GiB-PLE-Tabelle. Ein frisch gestarteter Container erreicht sein Swap-Gleich-
# gewicht (rund 11 GB) erst nach laengerer Last; bis dahin waechst der Swap um etwa
# 3 GB und reisst die 2048-MB-Grenze, obwohl nichts gefaehrdet ist: der verfuegbare
# RAM STEIGT dabei auf 13-19 GB, die eigentliche Schutzgrenze MIN_VERFUEGBAR_MB
# wird nie beruehrt und der 122-GB-Watchdog loest nicht aus. Der Step-2-Lauf traf
# die Grenze nur deshalb nicht, weil er gegen einen 9 h warmen Produktionscontainer
# lief. Die Grenze entscheidet ausschliesslich, OB ein Test laeuft - sie veraendert
# keinen einzigen gemessenen Wert. Deshalb ist sie ueberschreibbar, waehrend
# MIN_VERFUEGBAR_MB als eigentliches Sicherheitsnetz unangetastet bleibt.
MIN_VERFUEGBAR_MB = int(os.environ.get("BENCH_MIN_VERFUEGBAR_MB", "2048"))
MAX_SWAP_ZUWACHS_MB = int(os.environ.get("BENCH_MAX_SWAP_ZUWACHS_MB", "2048"))

ZEITLIMIT = 900                # Sekunden je Einzelanfrage


# ============================================================================
# Systemzustand lesen
# ============================================================================

def _befehl(*teile: str) -> str:
    """Befehl ausfuehren, Ausgabe zurueck. Fehler ergeben einen leeren String."""
    try:
        fertig = subprocess.run(teile, capture_output=True, text=True, timeout=30)
        return fertig.stdout.strip()
    except Exception:
        return ""


def _meminfo() -> dict[str, int]:
    werte: dict[str, int] = {}
    try:
        for zeile in Path("/proc/meminfo").read_text().splitlines():
            teile = zeile.split()
            if len(teile) >= 2:
                werte[teile[0].rstrip(":")] = int(teile[1])      # kB
    except Exception:
        pass
    return werte


def _vmstat() -> dict[str, int]:
    """pswpin/pswpout: wie viele Seiten wirklich ein- und ausgelagert wurden.

    Warum das zaehlt: `SwapUsed > 0` heisst nur, dass irgendwann einmal etwas
    ausgelagert wurde - nicht, dass gerade geswappt wird. Erst die Differenz
    dieser Zaehler ueber ein Zeitfenster zeigt echte Swap-Aktivitaet.
    """
    werte: dict[str, int] = {}
    try:
        for zeile in Path("/proc/vmstat").read_text().splitlines():
            teile = zeile.split()
            if len(teile) == 2 and teile[0] in ("pswpin", "pswpout"):
                werte[teile[0]] = int(teile[1])
    except Exception:
        pass
    return werte


def systemzustand() -> dict:
    """Momentaufnahme: Speicher, Swap, Last, GPU. Guenstig genug zum Takten."""
    mi = _meminfo()
    zustand = {
        "zeit": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ram_verfuegbar_mb": mi.get("MemAvailable", 0) // 1024,
        "ram_frei_mb": mi.get("MemFree", 0) // 1024,
        "swap_belegt_mb": (mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) // 1024,
        **_vmstat(),
    }
    try:
        zustand["load_1min"] = float(Path("/proc/loadavg").read_text().split()[0])
    except Exception:
        zustand["load_1min"] = None

    # GPU: eine Abfrage, alle Werte. Fehlende Felder liefert nvidia-smi als [N/A].
    roh = _befehl("nvidia-smi",
                  "--query-gpu=utilization.gpu,temperature.gpu,clocks.sm,power.draw",
                  "--format=csv,noheader,nounits")
    if roh:
        teile = [t.strip() for t in roh.split(",")]
        namen = ["gpu_auslastung_prozent", "gpu_temperatur_c", "gpu_takt_mhz", "gpu_leistung_w"]
        for name, wert in zip(namen, teile):
            try:
                zustand[name] = float(wert)
            except ValueError:
                zustand[name] = None

    # Zusaetzliche Thermalzonen, soweit der Kernel welche meldet.
    zonen = {}
    for pfad in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            name = (pfad / "type").read_text().strip()
            grad = int((pfad / "temp").read_text().strip()) / 1000.0
            if 0 < grad < 150:                  # unplausible Zonen weglassen
                zonen[name] = round(grad, 1)
        except Exception:
            continue
    if zonen:
        zustand["thermalzonen_c"] = zonen
    return zustand


def sicherheitspruefung(start_swap_mb: int) -> str | None:
    """Gibt einen Grund zurueck, wenn abgebrochen werden muss - sonst None."""
    z = systemzustand()
    if z["ram_verfuegbar_mb"] < MIN_VERFUEGBAR_MB:
        return (f"verfuegbarer RAM {z['ram_verfuegbar_mb']} MB unter Grenze "
                f"{MIN_VERFUEGBAR_MB} MB")
    zuwachs = z["swap_belegt_mb"] - start_swap_mb
    if zuwachs > MAX_SWAP_ZUWACHS_MB:
        return (f"Swap um {zuwachs} MB gewachsen, Grenze {MAX_SWAP_ZUWACHS_MB} MB")
    return None


# ============================================================================
# Umgebung inventarisieren
# ============================================================================

def umgebung_system() -> dict:
    mi = _meminfo()
    seitengroesse = _befehl("getconf", "PAGESIZE")
    governor = ""
    pfad = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if pfad.is_file():
        governor = pfad.read_text().strip()

    # CPU-Modelle: aarch64 meldet mehrere "Model name"-Zeilen (big.LITTLE).
    modelle = []
    for zeile in _befehl("lscpu").splitlines():
        if re.match(r"^\s*(Model name|Modellname)\s*:", zeile):
            modelle.append(zeile.split(":", 1)[1].strip())

    treiber = _befehl("nvidia-smi", "--query-gpu=driver_version,name",
                      "--format=csv,noheader")
    cuda = ""
    for zeile in _befehl("nvcc", "--version").splitlines():
        if "release" in zeile:
            cuda = zeile.strip()
    if not cuda:
        # Ohne nvcc meldet nvidia-smi die vom Treiber unterstuetzte Version.
        kopf = _befehl("nvidia-smi")
        treffer = re.search(r"CUDA Version:\s*([0-9.]+)", kopf)
        cuda = f"laut nvidia-smi: {treffer.group(1)}" if treffer else ""

    return {
        "zeitpunkt_lokal": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": _befehl("hostname"),
        "hardware": _befehl("sh", "-c",
                            "cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || "
                            "hostnamectl 2>/dev/null | sed -n 's/.*Hardware Model: *//p'"),
        "os": _befehl("sh", "-c", "lsb_release -ds 2>/dev/null || cat /etc/os-release | "
                                  "sed -n 's/^PRETTY_NAME=//p' | tr -d '\"'"),
        "kernel": _befehl("uname", "-r"),
        "architektur": _befehl("uname", "-m"),
        "kernel_seitengroesse_byte": int(seitengroesse) if seitengroesse.isdigit() else None,
        "transparent_hugepages": _befehl("cat", "/sys/kernel/mm/transparent_hugepage/enabled"),
        "hugepages_total": _meminfo().get("HugePages_Total", 0),
        "cpu_modelle": modelle,
        "cpu_kerne": os.cpu_count(),
        "cpu_governor": governor,
        "ram_gesamt_mb": mi.get("MemTotal", 0) // 1024,
        "ram_verfuegbar_mb": mi.get("MemAvailable", 0) // 1024,
        "ram_frei_mb": mi.get("MemFree", 0) // 1024,
        "swap_gesamt_mb": mi.get("SwapTotal", 0) // 1024,
        "swap_belegt_mb": (mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) // 1024,
        "load": _befehl("cat", "/proc/loadavg"),
        "uptime": _befehl("uptime", "-p"),
        "boot_zeit": _befehl("uptime", "-s"),
        "nvidia_treiber": treiber,
        "cuda": cuda,
        "start_zustand": systemzustand(),
    }


def umgebung_vllm() -> dict:
    """Alles, was sich ueber den laufenden Dienst feststellen laesst - ohne Eingriff."""
    info: dict = {"container": CONTAINER, "api_port": BASIS_URL}

    cmd_roh = _befehl("docker", "inspect", CONTAINER,
                      "--format", "{{range .Config.Cmd}}{{println .}}{{end}}")
    argumente = [z for z in cmd_roh.splitlines() if z.strip()]

    # Den Key aus den Startparametern entfernen, BEVOR irgendetwas gespeichert wird.
    gefiltert: list[str] = []
    ueberspringen = False
    for teil in argumente:
        if ueberspringen:
            gefiltert.append("<entfernt>")
            ueberspringen = False
            continue
        if teil == "--api-key":
            gefiltert.append(teil)
            ueberspringen = True
            continue
        gefiltert.append(teil)
    info["startparameter"] = gefiltert
    info["api_key_gesetzt"] = "--api-key" in argumente

    def flag(name: str) -> str | None:
        if name in argumente:
            stelle = argumente.index(name)
            if stelle + 1 < len(argumente):
                return argumente[stelle + 1]
        return None

    info["modell_pfad"] = argumente[0] if argumente else None
    info["served_model_name"] = flag("--served-model-name")
    info["max_model_len"] = flag("--max-model-len")
    info["max_num_seqs"] = flag("--max-num-seqs")
    info["gpu_memory_utilization"] = flag("--gpu-memory-utilization")
    info["tool_call_parser"] = flag("--tool-call-parser")
    info["prefix_caching_flag"] = ("--enable-prefix-caching" in argumente) or \
                                  ("--no-enable-prefix-caching" not in argumente)
    info["image"] = _befehl("docker", "inspect", CONTAINER, "--format", "{{.Config.Image}}")
    info["gestartet_am"] = _befehl("docker", "inspect", CONTAINER, "--format", "{{.State.StartedAt}}")

    # --- Die entscheidende Pruefung: kv_cache_memory_bytes ------------------
    protokoll = _befehl("docker", "logs", CONTAINER)
    info["kv_cache_memory_bytes_gesetzt"] = False
    info["memory_profiling_uebersprungen"] = False
    info["gpu_memory_utilization_wirksam"] = True

    treffer = re.search(r"reserved ([\d.]+) GiB memory for KV Cache", protokoll)
    if treffer:
        info["kv_cache_reserviert_gib"] = float(treffer.group(1))
    if "kv_cache_memory_bytes config" in protokoll:
        info["kv_cache_memory_bytes_gesetzt"] = True
    if "skipped memory profiling" in protokoll:
        info["memory_profiling_uebersprungen"] = True
    if "does not respect the gpu_memory_utilization config" in protokoll:
        info["gpu_memory_utilization_wirksam"] = False
        info["warnung_vllm"] = (
            "vLLM meldet: KV-Cache wurde ueber kv_cache_memory_bytes fest gesetzt, "
            "Memory Profiling uebersprungen, gpu_memory_utilization wird NICHT "
            "respektiert. Der Wert --gpu-memory-utilization ist damit wirkungslos."
        )

    treffer = re.search(r"GPU KV cache size: ([\d,]+) tokens", protokoll)
    if treffer:
        info["kv_cache_kapazitaet_tokens"] = int(treffer.group(1).replace(",", ""))
    treffer = re.search(r"Maximum concurrency for ([\d,]+) tokens per request: ([\d.]+)x", protokoll)
    if treffer:
        info["max_nebenlaeufigkeit_bei_vollkontext"] = float(treffer.group(2))

    # Belegter Speicher des Engine-Prozesses, wie die GPU ihn meldet.
    apps = _befehl("nvidia-smi", "--query-compute-apps=process_name,used_memory",
                   "--format=csv,noheader,nounits")
    info["gpu_prozesse"] = [z.strip() for z in apps.splitlines() if z.strip()]

    # Modelle laut API (ohne Key nicht abrufbar - dann bleibt das Feld leer).
    modelle = api_modelle()
    if modelle:
        info["api_modelle"] = modelle
    return info


# ============================================================================
# API-Zugriff
# ============================================================================

_KEY_ZWISCHENSPEICHER: str | None = None


def api_key() -> str:
    """Key aus der Umgebung, sonst aus dem Container. Wird nie ausgegeben."""
    global _KEY_ZWISCHENSPEICHER
    if _KEY_ZWISCHENSPEICHER is not None:
        return _KEY_ZWISCHENSPEICHER
    key = os.environ.get("VLLM_API_KEY", "").strip()
    if not key:
        roh = _befehl("docker", "inspect", CONTAINER,
                      "--format", "{{range .Config.Cmd}}{{println .}}{{end}}")
        zeilen = [z for z in roh.splitlines() if z.strip()]
        if "--api-key" in zeilen:
            stelle = zeilen.index("--api-key")
            if stelle + 1 < len(zeilen):
                key = zeilen[stelle + 1].strip()
    _KEY_ZWISCHENSPEICHER = key
    return key


def api_modelle() -> list[dict]:
    key = api_key()
    if not key:
        return []
    try:
        anfrage = urllib.request.Request(
            f"{BASIS_URL}/v1/models",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(anfrage, timeout=20) as antwort:
            daten = json.loads(antwort.read())
        return [{"id": m.get("id"), "max_model_len": m.get("max_model_len")}
                for m in daten.get("data", [])]
    except Exception:
        return []


def anfrage(prompt: str, max_tokens: int, modell: str, temperatur: float = 0.0) -> dict:
    """Eine Anfrage im Streaming-Modus. Misst TTFT und liest die echten Tokenzahlen.

    Warum Streaming: ohne Stream gibt es kein TTFT, und TTFT ist bei einem
    Agenten die Zahl, die man spuert - nicht der Gesamtdurchsatz.
    """
    key = api_key()
    nutzlast = {
        "model": modell,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperatur,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    daten = json.dumps(nutzlast).encode("utf-8")
    req = urllib.request.Request(
        f"{BASIS_URL}/v1/chat/completions", data=daten,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    ergebnis: dict = {"fehler": None, "timeout": False, "ttft_s": None,
                      "input_tokens": None, "output_tokens": None,
                      "reasoning_stuecke": 0, "content_stuecke": 0}
    begonnen = time.perf_counter()
    stuecke = 0
    try:
        with urllib.request.urlopen(req, timeout=ZEITLIMIT) as antwort:
            for rohzeile in antwort:
                zeile = rohzeile.decode("utf-8", errors="ignore").strip()
                if not zeile.startswith("data:"):
                    continue
                inhalt = zeile[5:].strip()
                if inhalt == "[DONE]":
                    break
                try:
                    block = json.loads(inhalt)
                except json.JSONDecodeError:
                    continue
                auswahl = block.get("choices") or []
                if auswahl:
                    delta = auswahl[0].get("delta", {}) or {}
                    # Dieses Modell denkt zuerst und streamt das als `reasoning`
                    # bzw. `reasoning_content` - NICHT als `content`. Wer nur auf
                    # `content` wartet, misst bei kurzen Antworten gar kein TTFT,
                    # weil das Token-Budget schon beim Denken aufgebraucht ist.
                    for feld in ("content", "reasoning", "reasoning_content"):
                        if delta.get(feld):
                            stuecke += 1
                            if feld == "content":
                                ergebnis["content_stuecke"] += 1
                            else:
                                ergebnis["reasoning_stuecke"] += 1
                            if ergebnis["ttft_s"] is None:
                                ergebnis["ttft_s"] = time.perf_counter() - begonnen
                    if delta.get("tool_calls") and ergebnis["ttft_s"] is None:
                        ergebnis["ttft_s"] = time.perf_counter() - begonnen
                nutzung = block.get("usage")
                if nutzung:
                    ergebnis["input_tokens"] = nutzung.get("prompt_tokens")
                    ergebnis["output_tokens"] = nutzung.get("completion_tokens")
    except urllib.error.URLError as fehler:
        ergebnis["fehler"] = str(fehler.reason)
        if "timed out" in str(fehler.reason).lower():
            ergebnis["timeout"] = True
    except TimeoutError:
        ergebnis["fehler"] = "Zeitlimit"
        ergebnis["timeout"] = True
    except Exception as fehler:
        ergebnis["fehler"] = f"{type(fehler).__name__}: {fehler}"

    ergebnis["gesamtdauer_s"] = time.perf_counter() - begonnen
    ergebnis["stream_stuecke"] = stuecke

    # --- Abgeleitete Groessen (klar als solche gekennzeichnet) --------------
    et, it, ot = ergebnis["ttft_s"], ergebnis["input_tokens"], ergebnis["output_tokens"]
    ergebnis["prefill_tokens_s"] = round(it / et, 1) if (it and et and et > 0) else None
    if ot and et is not None and ergebnis["gesamtdauer_s"] > et:
        ergebnis["generation_tokens_s"] = round(ot / (ergebnis["gesamtdauer_s"] - et), 2)
    else:
        ergebnis["generation_tokens_s"] = None
    return ergebnis


# ============================================================================
# Prompts - reproduzierbar aus einer versionierten Datei
# ============================================================================

def fuelltext(zeichen: int, versatz: int = 0) -> str:
    """Deterministischer Prompttext aus dem Korpus dieser Domaene.

    Warum aus dem Repo und nicht zufaellig: die Datei ist versioniert, damit ist
    derselbe Prompt auf jedem Geraet und zu jeder Zeit derselbe. Zufallstext
    waere nicht vergleichbar.
    """
    if not FUELLTEXT.is_file():
        return ("Der NVIDIA GB10 Grace Blackwell Superchip verbindet eine Grace-CPU "
                "mit einer Blackwell-GPU ueber NVLink-C2C. ") * (zeichen // 110 + 1)
    roh = FUELLTEXT.read_text(encoding="utf-8", errors="ignore")
    if len(roh) < zeichen + versatz:
        roh = roh * (((zeichen + versatz) // max(len(roh), 1)) + 2)
    return roh[versatz:versatz + zeichen]


def pruefsumme(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ============================================================================
# Beobachter: taktet den Systemzustand waehrend einer Messung mit
# ============================================================================

class Beobachter:
    def __init__(self, takt: float = 5.0):
        self.takt = takt
        self.proben: list[dict] = []
        self._laeuft = False
        self._faden: threading.Thread | None = None

    def start(self):
        self._laeuft = True
        self._faden = threading.Thread(target=self._schleife, daemon=True)
        self._faden.start()

    def _schleife(self):
        while self._laeuft:
            self.proben.append(systemzustand())
            time.sleep(self.takt)

    def stop(self) -> list[dict]:
        self._laeuft = False
        if self._faden:
            self._faden.join(timeout=self.takt + 2)
        if not self.proben:
            self.proben.append(systemzustand())
        return self.proben

    def zusammenfassung(self) -> dict:
        def spanne(feld: str) -> dict | None:
            werte = [p[feld] for p in self.proben if p.get(feld) is not None]
            if not werte:
                return None
            return {"min": round(min(werte), 1), "max": round(max(werte), 1),
                    "mittel": round(statistics.fmean(werte), 1)}
        return {
            "proben": len(self.proben),
            "ram_verfuegbar_mb": spanne("ram_verfuegbar_mb"),
            "swap_belegt_mb": spanne("swap_belegt_mb"),
            "load_1min": spanne("load_1min"),
            "gpu_auslastung_prozent": spanne("gpu_auslastung_prozent"),
            "gpu_temperatur_c": spanne("gpu_temperatur_c"),
            "gpu_takt_mhz": spanne("gpu_takt_mhz"),
            "gpu_leistung_w": spanne("gpu_leistung_w"),
        }


# ============================================================================
# Die Tests
# ============================================================================

def einzeltest(name: str, prompt: str, max_tokens: int, modell: str,
               start_swap: int) -> dict:
    grund = sicherheitspruefung(start_swap)
    if grund:
        return {"test": name, "abgebrochen": True, "grund": grund}
    beob = Beobachter(takt=3.0)
    beob.start()
    messung = anfrage(prompt, max_tokens, modell)
    beob.stop()
    return {
        "test": name,
        "prompt_zeichen": len(prompt),
        "prompt_pruefsumme": pruefsumme(prompt),
        "max_tokens": max_tokens,
        **messung,
        "systemzustand": beob.zusammenfassung(),
    }


def paralleltest(anzahl: int, prompt_zeichen: int, max_tokens: int, modell: str,
                 start_swap: int) -> dict:
    """n gleichzeitige Anfragen mit je eigenem Prompt (kein geteilter Prefix)."""
    grund = sicherheitspruefung(start_swap)
    if grund:
        return {"test": f"E_parallel_{anzahl}", "abgebrochen": True, "grund": grund}

    ergebnisse: list[dict] = [None] * anzahl          # type: ignore[list-item]
    beob = Beobachter(takt=3.0)
    beob.start()
    begonnen = time.perf_counter()

    def arbeit(i: int):
        # Versatz je Anfrage, damit sich die Prompts nicht ueber den Prefix-Cache
        # gegenseitig beschleunigen - sonst misst man den Cache, nicht die Last.
        ergebnisse[i] = anfrage(fuelltext(prompt_zeichen, versatz=i * 20_000),
                                max_tokens, modell)

    faeden = [threading.Thread(target=arbeit, args=(i,)) for i in range(anzahl)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()
    dauer = time.perf_counter() - begonnen
    beob.stop()

    gut = [e for e in ergebnisse if e and not e.get("fehler")]
    ttfts = [e["ttft_s"] for e in gut if e.get("ttft_s")]
    gen = [e["generation_tokens_s"] for e in gut if e.get("generation_tokens_s")]
    ausgabe_summe = sum(e.get("output_tokens") or 0 for e in gut)
    return {
        "test": f"E_parallel_{anzahl}",
        "anfragen": anzahl,
        "erfolgreich": len(gut),
        "fehler": [e.get("fehler") for e in ergebnisse if e and e.get("fehler")],
        "timeouts": sum(1 for e in ergebnisse if e and e.get("timeout")),
        "gesamtdauer_s": round(dauer, 2),
        "requests_s": round(len(gut) / dauer, 3) if dauer > 0 else None,
        "ttft_s_median": round(statistics.median(ttfts), 3) if ttfts else None,
        "generation_tokens_s_je_anfrage_median": round(statistics.median(gen), 2) if gen else None,
        "generation_tokens_s_summe": round(ausgabe_summe / dauer, 2) if dauer > 0 else None,
        "ausgabe_tokens_summe": ausgabe_summe,
        "systemzustand": beob.zusammenfassung(),
    }


def dauerlast(sekunden: int, modell: str, start_swap: int, nebenlaeufig: int = 2) -> dict:
    """Dauerlauf, um Drosselung sichtbar zu machen.

    Bei 140 W SoC-TDP im kleinen Gehaeuse entscheidet Thermik ueber die Leistung
    nach zehn Minuten - nicht nach zehn Sekunden. Genau das wird hier gemessen:
    Durchsatz je Minute, dazu Temperatur und Takt.
    """
    beob = Beobachter(takt=10.0)
    beob.start()
    begonnen = time.perf_counter()
    fenster: list[dict] = []
    laufende: list[dict] = []
    abbruch = None
    runde = 0

    while time.perf_counter() - begonnen < sekunden:
        grund = sicherheitspruefung(start_swap)
        if grund:
            abbruch = grund
            break
        runde += 1
        ergebnisse: list[dict] = [None] * nebenlaeufig      # type: ignore[list-item]

        def arbeit(i: int, r: int):
            ergebnisse[i] = anfrage(
                fuelltext(6_000, versatz=(r * nebenlaeufig + i) * 7_919), 200, modell)

        faeden = [threading.Thread(target=arbeit, args=(i, runde)) for i in range(nebenlaeufig)]
        rundenstart = time.perf_counter()
        for f in faeden:
            f.start()
        for f in faeden:
            f.join()
        rundendauer = time.perf_counter() - rundenstart

        gut = [e for e in ergebnisse if e and not e.get("fehler")]
        z = systemzustand()
        laufende.append({
            "runde": runde,
            "sekunde": round(time.perf_counter() - begonnen, 1),
            "rundendauer_s": round(rundendauer, 2),
            "erfolgreich": len(gut),
            "generation_tokens_s_summe": round(
                sum(e.get("output_tokens") or 0 for e in gut) / rundendauer, 2)
                if rundendauer > 0 else None,
            "ttft_s_median": round(statistics.median(
                [e["ttft_s"] for e in gut if e.get("ttft_s")] or [0]), 3),
            "gpu_temperatur_c": z.get("gpu_temperatur_c"),
            "gpu_takt_mhz": z.get("gpu_takt_mhz"),
            "gpu_leistung_w": z.get("gpu_leistung_w"),
            "ram_verfuegbar_mb": z.get("ram_verfuegbar_mb"),
            "swap_belegt_mb": z.get("swap_belegt_mb"),
        })

    beob.stop()
    gesamt = time.perf_counter() - begonnen

    # Erstes gegen letztes Drittel: so wird Drosselung sichtbar.
    def mittel(teil: list[dict], feld: str) -> float | None:
        werte = [r[feld] for r in teil if r.get(feld) is not None]
        return round(statistics.fmean(werte), 2) if werte else None

    drittel = max(len(laufende) // 3, 1)
    anfang, ende = laufende[:drittel], laufende[-drittel:]
    fenster = [
        {"abschnitt": "erstes Drittel",
         "generation_tokens_s_summe": mittel(anfang, "generation_tokens_s_summe"),
         "gpu_temperatur_c": mittel(anfang, "gpu_temperatur_c"),
         "gpu_takt_mhz": mittel(anfang, "gpu_takt_mhz")},
        {"abschnitt": "letztes Drittel",
         "generation_tokens_s_summe": mittel(ende, "generation_tokens_s_summe"),
         "gpu_temperatur_c": mittel(ende, "gpu_temperatur_c"),
         "gpu_takt_mhz": mittel(ende, "gpu_takt_mhz")},
    ]
    anfangswert = fenster[0]["generation_tokens_s_summe"]
    endwert = fenster[1]["generation_tokens_s_summe"]
    abfall = None
    if anfangswert and endwert:
        abfall = round((endwert - anfangswert) / anfangswert * 100, 1)

    return {
        "test": "F_dauerlast",
        "geplant_s": sekunden,
        "tatsaechlich_s": round(gesamt, 1),
        "nebenlaeufig": nebenlaeufig,
        "runden": len(laufende),
        "abgebrochen": abbruch is not None,
        "grund": abbruch,
        "verlauf": laufende,
        "vergleich": fenster,
        "durchsatzaenderung_prozent": abfall,
        "systemzustand": beob.zusammenfassung(),
    }



# ============================================================================
# Agenten-Benchmark
# ============================================================================
#
# Warum getrennt von A-F: Ein Agent macht nicht eine lange Antwort, sondern
# viele kurze Schritte mit Werkzeugaufruf. Was er spuert, ist NICHT der
# Gesamtdurchsatz, sondern die Zeit bis zur ersten brauchbaren Handlung.
#
# Ein Modell, das schnell zu denken anfaengt, aber lange keinen Tool Call
# liefert, darf hier nicht gut aussehen. Darum werden drei Zeitpunkte getrennt
# gemessen: erster Reasoning-Token, erster sichtbarer Content, erster Tool Call.

AGENT_SYSTEM = (
    "Du bist ein Werkzeug-Agent. Beantworte die Frage ausschliesslich, indem du "
    "das bereitgestellte Werkzeug aufrufst. Denke kurz und rufe dann das Werkzeug auf."
)

AGENT_WERKZEUGE = [{
    "type": "function",
    "function": {
        "name": "datei_groesse",
        "description": "Gibt die Groesse einer Datei in Bytes zurueck.",
        "parameters": {
            "type": "object",
            "properties": {"pfad": {"type": "string", "description": "absoluter Pfad"}},
            "required": ["pfad"],
        },
    },
}]

# 30 feste Pfade - deterministisch, damit jeder Lauf und jedes Modell dieselbe
# Aufgabe bekommt. Verschiedene Pfade, damit nicht der Prefix-Cache die ganze
# Messung uebernimmt.
AGENT_PFADE = [
    "/etc/hostname", "/etc/hosts", "/etc/os-release", "/etc/fstab", "/etc/passwd",
    "/etc/group", "/etc/shells", "/etc/services", "/etc/protocols", "/etc/timezone",
    "/proc/cpuinfo", "/proc/meminfo", "/proc/version", "/proc/uptime", "/proc/stat",
    "/etc/nsswitch.conf", "/etc/resolv.conf", "/etc/profile", "/etc/environment",
    "/etc/crontab", "/etc/issue", "/etc/motd", "/etc/login.defs", "/etc/sysctl.conf",
    "/etc/locale.gen", "/etc/debian_version", "/etc/machine-id", "/etc/localtime",
    "/etc/inputrc", "/etc/bash.bashrc",
]


def agentenschritt(modell: str, pfad: str, max_tokens: int = 600,
                   temperatur: float = 0.0, top_p: float | None = None) -> dict:
    """Ein Agentenschritt: Frage -> Reasoning -> Tool Call. Misst alle drei Phasen."""
    key = api_key()
    nutzlast = {
        "model": modell,
        "messages": [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": f"Wie gross ist die Datei {pfad}? Nutze das Werkzeug."},
        ],
        "tools": AGENT_WERKZEUGE,
        "tool_choice": "auto",
        "max_tokens": max_tokens,
        "temperature": temperatur,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if top_p is not None:
        nutzlast["top_p"] = top_p
    daten = json.dumps(nutzlast).encode("utf-8")
    req = urllib.request.Request(
        f"{BASIS_URL}/v1/chat/completions", data=daten,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    e: dict = {
        "pfad": pfad, "fehler": None, "timeout": False,
        "t_erster_reasoning_s": None,     # Zeit bis erster Reasoning-Token
        "t_erster_content_s": None,       # Zeit bis erster sichtbarer Content
        "t_erster_tool_call_s": None,     # Zeit bis erster Tool Call
        "finish_reason": None,
        "tool_name": None, "tool_argumente": None,
        "tool_call_gueltig": False,
        "input_tokens": None, "output_tokens": None,
        "reasoning_tokens": None, "sichtbare_tokens": None,
    }
    tool_roh = ""
    begonnen = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=ZEITLIMIT) as antwort:
            for rohzeile in antwort:
                zeile = rohzeile.decode("utf-8", errors="ignore").strip()
                if not zeile.startswith("data:"):
                    continue
                rest = zeile[5:].strip()
                if rest == "[DONE]":
                    break
                try:
                    block = json.loads(rest)
                except json.JSONDecodeError:
                    continue
                jetzt = time.perf_counter() - begonnen
                auswahl = block.get("choices") or []
                if auswahl:
                    d = auswahl[0].get("delta", {}) or {}
                    if (d.get("reasoning") or d.get("reasoning_content")) \
                            and e["t_erster_reasoning_s"] is None:
                        e["t_erster_reasoning_s"] = jetzt
                    if d.get("content") and e["t_erster_content_s"] is None:
                        e["t_erster_content_s"] = jetzt
                    if d.get("tool_calls"):
                        if e["t_erster_tool_call_s"] is None:
                            e["t_erster_tool_call_s"] = jetzt
                        for tc in d["tool_calls"]:
                            fn = (tc or {}).get("function") or {}
                            if fn.get("name"):
                                e["tool_name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_roh += fn["arguments"]
                    if auswahl[0].get("finish_reason"):
                        e["finish_reason"] = auswahl[0]["finish_reason"]
                n = block.get("usage")
                if n:
                    e["input_tokens"] = n.get("prompt_tokens")
                    e["output_tokens"] = n.get("completion_tokens")
                    det = n.get("completion_tokens_details") or {}
                    e["reasoning_tokens"] = det.get("reasoning_tokens")
    except Exception as fehler:
        e["fehler"] = f"{type(fehler).__name__}: {fehler}"
        if "timed out" in str(fehler).lower():
            e["timeout"] = True

    e["gesamtdauer_s"] = time.perf_counter() - begonnen
    if e["output_tokens"] is not None and e["reasoning_tokens"] is not None:
        e["sichtbare_tokens"] = e["output_tokens"] - e["reasoning_tokens"]

    # Erfolg heisst: richtiger Werkzeugname UND gueltiges JSON UND der
    # verlangte Pfad steht drin. Ein Tool Call mit kaputten Argumenten ist
    # fuer einen Agenten wertlos und wird hier nicht als Erfolg gezaehlt.
    if e["tool_name"] == "datei_groesse" and tool_roh:
        try:
            arg = json.loads(tool_roh)
            e["tool_argumente"] = arg
            e["tool_call_gueltig"] = arg.get("pfad") == pfad
        except json.JSONDecodeError:
            e["tool_argumente"] = tool_roh[:200]

    # Die Kernzahl: Zeit bis zur ersten brauchbaren Handlung. Fuer einen Agenten
    # ist das der Tool Call; faellt keiner, zaehlt sichtbarer Content.
    e["time_to_useful_action_s"] = e["t_erster_tool_call_s"] or e["t_erster_content_s"]
    return e


def agentenbenchmark(modell: str, start_swap: int, schritte: int = 30,
                     temperatur: float = 0.0, top_p: float | None = None) -> dict:
    """`schritte` sequenzielle Agentenschritte - so arbeitet Ben wirklich."""
    grund = sicherheitspruefung(start_swap)
    if grund:
        return {"test": "G_agent", "abgebrochen": True, "grund": grund}

    beob = Beobachter(takt=5.0)
    beob.start()
    begonnen = time.perf_counter()
    ergebnisse: list[dict] = []
    for i in range(schritte):
        if i % 10 == 0 and i:
            g = sicherheitspruefung(start_swap)
            if g:
                ergebnisse.append({"abgebrochen": True, "grund": g})
                break
        ergebnisse.append(agentenschritt(modell, AGENT_PFADE[i % len(AGENT_PFADE)],
                                         temperatur=temperatur, top_p=top_p))
    gesamt = time.perf_counter() - begonnen
    beob.stop()

    gut = [r for r in ergebnisse if not r.get("fehler") and not r.get("abgebrochen")]

    def werte(feld: str) -> list[float]:
        return [r[feld] for r in gut if r.get(feld) is not None]

    def stat(feld: str) -> dict | None:
        w = sorted(werte(feld))
        if not w:
            return None
        return {
            "median": round(statistics.median(w), 3),
            "p95": round(w[min(int(len(w) * 0.95), len(w) - 1)], 3),
            "min": round(w[0], 3),
            "max": round(w[-1], 3),
            "mittel": round(statistics.fmean(w), 3),
        }

    erfolge = sum(1 for r in gut if r.get("tool_call_gueltig"))
    reas = werte("reasoning_tokens")
    sicht = werte("sichtbare_tokens")
    # Fehlerklassen getrennt zaehlen - "Tool Call fehlgeschlagen" ist keine
    # Diagnose, solange nicht klar ist, woran er scheiterte.
    falscher_name = sum(1 for r in gut if r.get("tool_name") and r["tool_name"] != "datei_groesse")
    kein_tool = sum(1 for r in gut if not r.get("tool_name"))
    ungueltiges_json = sum(1 for r in gut if r.get("tool_name") == "datei_groesse"
                           and not isinstance(r.get("tool_argumente"), dict))
    falscher_pfad = sum(1 for r in gut if isinstance(r.get("tool_argumente"), dict)
                        and r["tool_argumente"].get("pfad") != r.get("pfad"))
    ohne_aktion = sum(1 for r in gut if r.get("time_to_useful_action_s") is None)

    return {
        "test": "G_agent",
        "sampling": {"temperature": temperatur, "top_p": top_p},
        "fehlerklassen": {
            "kein_tool_call": kein_tool,
            "falscher_tool_name": falscher_name,
            "ungueltiges_json": ungueltiges_json,
            "falscher_pfad": falscher_pfad,
            "schritte_ohne_nutzbare_aktion": ohne_aktion,
        },
        "prompt_tokens_median": (round(statistics.median(werte("input_tokens")), 1)
                                 if werte("input_tokens") else None),
        "completion_tokens_median": (round(statistics.median(werte("output_tokens")), 1)
                                     if werte("output_tokens") else None),
        "schritte_geplant": schritte,
        "schritte_gelaufen": len(gut),
        "fehler": [r["fehler"] for r in ergebnisse if r.get("fehler")],
        "timeouts": sum(1 for r in ergebnisse if r.get("timeout")),
        "gesamtdauer_s": round(gesamt, 2),
        "schritte_pro_minute": round(len(gut) / gesamt * 60, 2) if gesamt > 0 else None,
        "time_to_useful_action_s": stat("time_to_useful_action_s"),
        "t_erster_reasoning_s": stat("t_erster_reasoning_s"),
        "t_erster_tool_call_s": stat("t_erster_tool_call_s"),
        "t_erster_content_s": stat("t_erster_content_s"),
        "gesamtdauer_je_schritt_s": stat("gesamtdauer_s"),
        "tool_call_erfolge": erfolge,
        "tool_call_erfolgsrate": round(erfolge / len(gut), 3) if gut else None,
        "finish_reasons": {fr: sum(1 for r in gut if r.get("finish_reason") == fr)
                           for fr in {r.get("finish_reason") for r in gut}},
        "reasoning_tokens_median": round(statistics.median(reas), 1) if reas else None,
        "sichtbare_tokens_median": round(statistics.median(sicht), 1) if sicht else None,
        "reasoning_anteil": (round(sum(reas) / (sum(reas) + sum(sicht)), 3)
                             if reas and sicht and (sum(reas) + sum(sicht)) else None),
        "systemzustand": beob.zusammenfassung(),
        "schritte": ergebnisse,
    }

# ============================================================================
# Ablauf
# ============================================================================

def lauf(nur_umgebung: bool, nur_schnell: bool, dauer_s: int,
         nur_agent: bool = False, agent_schritte: int = 30,
         temperatur: float = 0.0, top_p: float | None = None) -> dict:
    print("== Umgebung erfassen ==")
    bericht = {
        "werkzeug": "benchmark_gx10.py",
        "fassung": "1.3.1",
        "fassung_hinweis": ("Tests, Prompts, Messgroessen und Auswertung sind "
                            "identisch zu 1.3. Einziger Unterschied: die beiden "
                            "Abbruchgrenzen sind ueber Umgebungsvariablen "
                            "ueberschreibbar und werden im Bericht festgehalten. "
                            "Ohne gesetzte Variablen ist das Verhalten exakt 1.3."),
        "sicherheitsgrenzen": {
            "min_verfuegbar_mb": MIN_VERFUEGBAR_MB,
            "max_swap_zuwachs_mb": MAX_SWAP_ZUWACHS_MB,
            "standard_1_3": {"min_verfuegbar_mb": 2048, "max_swap_zuwachs_mb": 2048},
        },
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hinweis": ("Reine Messung. Es wurde nichts am laufenden System geaendert: "
                    "keine Flags, keine Units, kein Container, kein Modell."),
        "system": umgebung_system(),
        "vllm": umgebung_vllm(),
        "tests": [],
    }
    v = bericht["vllm"]
    print(f"   Modell:   {v.get('served_model_name')}")
    print(f"   KV-Cache: {v.get('kv_cache_reserviert_gib')} GiB "
          f"({v.get('kv_cache_kapazitaet_tokens')} Tokens)")
    if not v.get("gpu_memory_utilization_wirksam", True):
        print("   ACHTUNG:  gpu_memory_utilization ist wirkungslos "
              "(kv_cache_memory_bytes gesetzt)")
    if nur_umgebung:
        return bericht

    modelle = v.get("api_modelle") or []
    if not modelle:
        bericht["tests"].append({"test": "abbruch",
                                 "grund": "API nicht erreichbar oder kein Key gefunden"})
        return bericht
    modell = modelle[0]["id"]
    start_swap = bericht["system"]["swap_belegt_mb"]
    print(f"   API:      {modell} auf {BASIS_URL}")
    print(f"   Start-Swap {start_swap} MB, verfuegbarer RAM "
          f"{bericht['system']['ram_verfuegbar_mb']} MB\n")

    if nur_agent:
        print(f"== G: Agenten-Benchmark, {agent_schritte} Schritte ==")
        bericht["tests"].append(agentenbenchmark(modell, start_swap, agent_schritte,
                                                 temperatur, top_p))
        bericht["end_zustand"] = systemzustand()
        return bericht

    print("== A: kurze Anfrage ==")
    bericht["tests"].append(einzeltest(
        "A_kurz", "Nenne in einem Satz, was NVLink-C2C verbindet.", 128, modell, start_swap))

    print("== B: mittlerer Prompt (~8'000 Zeichen) ==")
    bericht["tests"].append(einzeltest(
        "B_mittel", fuelltext(8_000) + "\n\nFasse den Text in drei Saetzen zusammen.",
        256, modell, start_swap))

    print("== C: langer Prompt (~64'000 Zeichen) ==")
    bericht["tests"].append(einzeltest(
        "C_lang", fuelltext(64_000, versatz=100_000) + "\n\nNenne die drei wichtigsten Punkte.",
        256, modell, start_swap))

    print("== D: Prefix-Cache kalt und warm ==")
    # "Kalt" heisst hier: ein Prefix, der in dieser Sitzung noch nie gesendet
    # wurde. Ein echtes Leeren des Caches ginge nur ueber einen Neustart des
    # Dienstes - und der ist in diesem Schritt ausdruecklich verboten.
    d_prompt = fuelltext(16_000, versatz=250_000) + "\n\nWorum geht es hier?"
    kalt = einzeltest("D_prefix_kalt", d_prompt, 128, modell, start_swap)
    warm = einzeltest("D_prefix_warm", d_prompt, 128, modell, start_swap)
    if kalt.get("ttft_s") and warm.get("ttft_s"):
        warm["ttft_verbesserung_prozent"] = round(
            (kalt["ttft_s"] - warm["ttft_s"]) / kalt["ttft_s"] * 100, 1)
    bericht["tests"].extend([kalt, warm])

    print("== E: parallele Anfragen (1, 2, 4) ==")
    for anzahl in (1, 2, 4):
        print(f"   {anzahl} gleichzeitig ...")
        bericht["tests"].append(paralleltest(anzahl, 6_000, 200, modell, start_swap))

    print(f"== G: Agenten-Benchmark, {agent_schritte} Schritte ==")
    bericht["tests"].append(agentenbenchmark(modell, start_swap, agent_schritte,
                                                 temperatur, top_p))

    if not nur_schnell:
        print(f"== F: Dauerlast {dauer_s // 60} Minuten ==")
        bericht["tests"].append(dauerlast(dauer_s, modell, start_swap))

    bericht["end_zustand"] = systemzustand()
    return bericht


# ============================================================================
# Ausgabe
# ============================================================================

def tabelle(bericht: dict) -> str:
    """Die Baseline-Tabelle als Markdown - dieselbe Quelle wie gx10/MESSWERTE.md."""
    tests = {t.get("test"): t for t in bericht.get("tests", [])}
    sys_ = bericht.get("system", {})
    v = bericht.get("vllm", {})

    def hole(name: str, feld: str, ersatz="—"):
        wert = (tests.get(name) or {}).get(feld)
        return wert if wert is not None else ersatz

    zeilen = [
        "| Grösse | Wert | Art |",
        "|---|---|---|",
        f"| Modell | `{v.get('served_model_name', '—')}` | GEMESSEN |",
        f"| Kontext (max-model-len) | {v.get('max_model_len', '—')} | GEMESSEN |",
        f"| KV-Cache reserviert | {v.get('kv_cache_reserviert_gib', '—')} GiB | GEMESSEN |",
        f"| KV-Cache Kapazität | {v.get('kv_cache_kapazitaet_tokens', '—')} Tokens | GEMESSEN |",
        f"| TTFT kurz (A) | {hole('A_kurz', 'ttft_s')} s | GEMESSEN |",
        f"| TTFT mittel (B) | {hole('B_mittel', 'ttft_s')} s | GEMESSEN |",
        f"| TTFT lang (C) | {hole('C_lang', 'ttft_s')} s | GEMESSEN |",
        f"| Generation tok/s (A) | {hole('A_kurz', 'generation_tokens_s')} | ABGELEITET |",
        f"| Generation tok/s (B) | {hole('B_mittel', 'generation_tokens_s')} | ABGELEITET |",
        f"| Prefill tok/s (B) | {hole('B_mittel', 'prefill_tokens_s')} | ABGELEITET |",
        f"| Prefill tok/s (C) | {hole('C_lang', 'prefill_tokens_s')} | ABGELEITET |",
        f"| Durchsatz 1 parallel | {hole('E_parallel_1', 'generation_tokens_s_summe')} tok/s | ABGELEITET |",
        f"| Durchsatz 2 parallel | {hole('E_parallel_2', 'generation_tokens_s_summe')} tok/s | ABGELEITET |",
        f"| Durchsatz 4 parallel | {hole('E_parallel_4', 'generation_tokens_s_summe')} tok/s | ABGELEITET |",
        f"| RAM verfügbar (Start) | {sys_.get('ram_verfuegbar_mb', '—')} MB | GEMESSEN |",
        f"| Swap belegt (Start) | {sys_.get('swap_belegt_mb', '—')} MB | GEMESSEN |",
    ]
    ag = tests.get("G_agent")
    if ag:
        def s(feld, unter="median"):
            w = (ag.get(feld) or {})
            return w.get(unter, "—") if isinstance(w, dict) else "—"
        zeilen += [
            f"| **Time to Useful Action** Median | {s('time_to_useful_action_s')} s | GEMESSEN |",
            f"| Time to Useful Action p95 | {s('time_to_useful_action_s','p95')} s | GEMESSEN |",
            f"| Agent Schritt gesamt Median | {s('gesamtdauer_je_schritt_s')} s | GEMESSEN |",
            f"| Agent Schritt gesamt p95 | {s('gesamtdauer_je_schritt_s','p95')} s | GEMESSEN |",
            f"| Zeit bis erster Tool Call Median | {s('t_erster_tool_call_s')} s | GEMESSEN |",
            f"| **Tool-Call-Erfolgsrate** | {ag.get('tool_call_erfolgsrate','—')} | GEMESSEN |",
            f"| Reasoning-Tokens Median | {ag.get('reasoning_tokens_median','—')} | GEMESSEN |",
            f"| Sichtbare Tokens Median | {ag.get('sichtbare_tokens_median','—')} | GEMESSEN |",
            f"| Reasoning-Anteil | {ag.get('reasoning_anteil','—')} | ABGELEITET |",
        ]

    dl = tests.get("F_dauerlast")
    if dl:
        z = dl.get("systemzustand", {}) or {}
        temp = (z.get("gpu_temperatur_c") or {}).get("max", "—")
        zeilen += [
            f"| Temperatur max unter Dauerlast | {temp} °C | GEMESSEN |",
            f"| Durchsatzänderung über {dl.get('tatsaechlich_s', '—')} s | "
            f"{dl.get('durchsatzaenderung_prozent', '—')} % | ABGELEITET |",
        ]
    return "\n".join(zeilen)


def main() -> int:
    p = argparse.ArgumentParser(description="Leistungs-Baseline gx10 (reine Messung)")
    p.add_argument("--nur-umgebung", action="store_true", help="nur Inventar, keine Last")
    p.add_argument("--nur-schnell", action="store_true", help="Tests A-E ohne Dauerlast")
    p.add_argument("--dauerlast", type=int, default=600, help="Sekunden Dauerlast (Standard 600)")
    p.add_argument("--tabelle", action="store_true", help="Baseline aus vorhandenem JSON drucken")
    p.add_argument("--nur-agent", action="store_true", help="nur den Agenten-Benchmark (Test G)")
    p.add_argument("--agent-schritte", type=int, default=30, help="Anzahl Agentenschritte (Standard 30)")
    p.add_argument("--ausgabe", help="Zieldatei statt messungen/baseline-gx10.json")
    p.add_argument("--agent-temperatur", type=float, default=0.0,
                   help="Sampling-Temperatur im Agententest (Standard 0.0)")
    p.add_argument("--agent-top-p", type=float, default=None,
                   help="top_p im Agententest (Standard: nicht gesetzt)")
    p.add_argument("--ueberschreiben", action="store_true",
                   help="vorhandene Zieldatei ersetzen (fuer die Step-1-Baseline noetig)")
    a = p.parse_args()

    if a.tabelle:
        quelle = Path(a.ausgabe) if a.ausgabe else ZIEL
        if not quelle.is_absolute():
            quelle = GX10 / quelle
        print(tabelle(json.loads(quelle.read_text(encoding="utf-8"))))
        return 0

    if not shutil.which("docker"):
        print("docker nicht gefunden - ohne Container laesst sich vLLM nicht inventarisieren")

    ziel = Path(a.ausgabe) if a.ausgabe else ZIEL
    if not ziel.is_absolute():
        ziel = GX10 / ziel
    # Die Step-1-Baseline ist Referenz fuer jeden spaeteren Vergleich. Sie wird
    # nur auf ausdrueckliche Anweisung ueberschrieben.
    if ziel.is_file() and not a.ueberschreiben:
        print(f"ABBRUCH: {ziel} existiert bereits.")
        print("         Mit --ausgabe eine andere Datei waehlen, oder --ueberschreiben angeben.")
        return 1

    bericht = lauf(a.nur_umgebung, a.nur_schnell, a.dauerlast, a.nur_agent,
                   a.agent_schritte, a.agent_temperatur, a.agent_top_p)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(bericht, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nBericht: {ziel}")
    if not a.nur_umgebung:
        print()
        print(tabelle(bericht))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
