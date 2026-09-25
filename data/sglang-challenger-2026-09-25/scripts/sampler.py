#!/usr/bin/env python3
"""1-s-Systemprotokoll + Zusatzwaechter fuer den Nachtlauf.

Schreibt CSV: RAM, Swap, pswpin/out, Major-Faults, NVMe-Lesesektoren, CPU gesamt
und heissester Kern, GPU util/power/temp/SM-Takt/Throttle-Gruende.

Waechter (ERGAENZT llm-memory-guard, ersetzt ihn nicht - der laeuft unveraendert):
  - neuer NVRM-Xid; NVRM NV_ERR_* nur als Schub (>=3 in 60 s) - einzelne NV_ERR_NO_MEMORY sind auf
    gx10 im Normalbetrieb von A belegt (34-3576 je Boot seit 29.08.), sie werden in <ereignisse>.hinweise gezaehlt; OOM-Kill ("Killed process") im Kernel-Log
    (bis 22:40 falsch als "Kernel-OOM" etikettiert, wenn nur eine NVRM-Meldung "Out of memory" enthielt)
  - MemAvailable < --guard-mb (Standard 9500 MiB, also ~1.2 GiB ueber der
    Watchdog-Grenze von 8260 MiB)
  - pswpout-Zuwachs > --max-swapout-mb innerhalb von 60 s, NUR wenn MemAvailable < 12 GiB (ab 00:50; vorher 25 GiB, Fehlalarm A_ctrl F5)
    (beim Laden eines Modells lagert der Kernel bei 30+ GiB freiem RAM regulaer aus - auch A selbst:
    +3.1 GiB pswpout beim Start 21.09. 20:53 - das ist kein Druck; Fehlalarm B_v029_r2 22:58)
Bei Ausloesung: Ereigniszeile nach --ereignisse, und NUR wenn --stoppe gesetzt
ist und der Name mit "bench-" beginnt: docker stop dieses Containers.
Die Produktion (qwen38-flash) wird nie angefasst.
Ende: Datei --stopdatei existiert, oder SIGTERM.
"""
import argparse, os, signal, subprocess, sys, time

def mem():
    d = {}
    for z in open("/proc/meminfo"):
        k, v = z.split(":", 1); d[k] = int(v.split()[0])
    return d

def vm():
    d = {}
    for z in open("/proc/vmstat"):
        k, v = z.split(); d[k] = int(v)
    return d

def cpu():
    zeilen = [z.split() for z in open("/proc/stat") if z.startswith("cpu")]
    return {z[0]: (sum(map(int, z[1:])), int(z[4]) + int(z[5])) for z in zeilen}

def nvme_sektoren():
    for z in open("/proc/diskstats"):
        f = z.split()
        if f[2] == "nvme0n1":
            return int(f[5])
    return 0

def zaehle(cmd, muster):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
        return sum(1 for z in out.splitlines() if muster in z)
    except Exception:
        return -1

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True); p.add_argument("--ereignisse", required=True)
    p.add_argument("--stopdatei", required=True); p.add_argument("--stoppe", default="")
    p.add_argument("--guard-mb", type=int, default=9500)
    p.add_argument("--max-swapout-mb", type=int, default=3072)
    a = p.parse_args()
    lauf = [True]
    signal.signal(signal.SIGTERM, lambda *_: lauf.__setitem__(0, False))
    smi = subprocess.Popen(["nvidia-smi", "--query-gpu=utilization.gpu,power.draw,temperature.gpu,clocks.sm,"
                            "clocks_event_reasons.active", "--format=csv,noheader,nounits", "-lms", "1000"],
                           stdout=subprocess.PIPE, text=True)
    xid0 = zaehle(["sudo", "-n", "dmesg"], "NVRM: Xid")
    oom0 = zaehle(["journalctl", "-k", "-b", "--no-pager", "-o", "cat"], "Killed process")
    nvrm0 = zaehle(["sudo", "-n", "dmesg"], "NV_ERR_")
    fcsv = open(a.csv, "w"); fev = open(a.ereignisse, "a")
    fcsv.write("t,memavail_mib,swap_used_mib,pswpin,pswpout,pgmajfault,nvme_read_mib,cpu_pct,cpu_max_core_pct,"
               "gpu_util,gpu_w,gpu_c,sm_mhz,throttle\n")
    c_alt = cpu(); s_alt = nvme_sektoren(); hist = []; nvhist = []; ausgeloest = False; n = 0
    def ereignis(text):
        nonlocal ausgeloest
        fev.write(f"{time.strftime('%H:%M:%S')} {text}\n"); fev.flush()
        if a.stoppe.startswith("bench-") and not ausgeloest:
            subprocess.run(["docker", "stop", "-t", "10", a.stoppe], capture_output=True)
            fev.write(f"{time.strftime('%H:%M:%S')} WAECHTER: docker stop {a.stoppe}\n"); fev.flush()
        ausgeloest = True
    while lauf[0] and not os.path.exists(a.stopdatei):
        zeile = smi.stdout.readline().strip()
        if not zeile:
            time.sleep(1); continue
        m = mem(); v = vm(); c = cpu(); s = nvme_sektoren()
        busy = []
        for k, (tot, idle) in c.items():
            dt = tot - c_alt[k][0]; di = idle - c_alt[k][1]
            busy.append((k, 100.0 * (dt - di) / dt if dt else 0.0))
        gesamt = [b for k, b in busy if k == "cpu"][0]; kerne = max(b for k, b in busy if k != "cpu")
        c_alt = c
        ma = m["MemAvailable"] // 1024; sw = (m["SwapTotal"] - m["SwapFree"]) // 1024
        fcsv.write(f"{time.strftime('%H:%M:%S')},{ma},{sw},{v['pswpin']},{v['pswpout']},{v['pgmajfault']},"
                   f"{(s - s_alt) * 512 / 1048576:.1f},{gesamt:.1f},{kerne:.1f},{zeile.replace(' ', '')}\n")
        s_alt = s; fcsv.flush()
        hist.append((time.time(), v["pswpout"])); hist = [h for h in hist if h[0] > time.time() - 60]
        if ma < a.guard_mb:
            ereignis(f"GUARD MemAvailable {ma} MiB < {a.guard_mb}")
        if ma < 12288 and (hist[-1][1] - hist[0][1]) * 4 / 1024 > a.max_swapout_mb:
            ereignis(f"GUARD pswpout +{(hist[-1][1]-hist[0][1])*4//1024} MiB in 60 s")
        n += 1
        if n % 5 == 0:
            x = zaehle(["sudo", "-n", "dmesg"], "NVRM: Xid")
            if x > xid0:
                ereignis(f"GUARD neuer NVIDIA Xid ({x - xid0})"); xid0 = x
            o = zaehle(["journalctl", "-k", "-b", "--no-pager", "-o", "cat"], "Killed process")
            if o > oom0:
                ereignis(f"GUARD Kernel-OOM-Kill ({o - oom0})"); oom0 = o
            nv = zaehle(["sudo", "-n", "dmesg"], "NV_ERR_")
            if nv > nvrm0:
                nvhist.extend([time.time()] * (nv - nvrm0)); nvrm0 = nv
                nvhist[:] = [t for t in nvhist if t > time.time() - 60]
                open(a.ereignisse + ".hinweise", "a").write(f"{time.strftime('%H:%M:%S')} NV_ERR_* +1 (60-s-Fenster: {len(nvhist)})\n")
                if len(nvhist) >= 3:
                    ereignis(f"GUARD NVRM NV_ERR_*-Schub: {len(nvhist)} in 60 s")
    smi.terminate(); fcsv.close(); fev.close()

if __name__ == "__main__":
    sys.exit(main())
