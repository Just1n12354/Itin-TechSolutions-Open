#!/usr/bin/env python3
"""PSI + Paging alle 5 s nach CSV (nur lesend). Ende: --stopdatei existiert.
Spalten: zeit, psi_mem_some_avg10, psi_mem_full_avg10, psi_io_some_avg10, psi_mem_some_total_us,
pgmajfault/s, pswpin/s, pswpout/s (Seiten), memavail_mib, swap_used_mib.
Beantwortet: Gibt es waehrend der Inferenz AKTIVES Paging bzw. Speicher-Stau (nicht nur belegten Swap)?"""
import argparse, os, time

def psi(r):
    d = {}
    for z in open(f"/proc/pressure/{r}"):
        art, *kv = z.split()
        d[art] = {k: float(v) for k, v in (x.split("=") for x in kv)}
    return d

def vm():
    return {a: int(b) for a, b in (z.split() for z in open("/proc/vmstat")) if a in ("pgmajfault", "pswpin", "pswpout")}

def mem():
    m = {z.split(":")[0]: int(z.split()[1]) for z in open("/proc/meminfo")}
    return m["MemAvailable"] // 1024, (m["SwapTotal"] - m["SwapFree"]) // 1024

ap = argparse.ArgumentParser(); ap.add_argument("--csv", required=True); ap.add_argument("--stopdatei", required=True)
ap.add_argument("--intervall", type=float, default=5.0); a = ap.parse_args()
with open(a.csv, "w") as f:
    f.write("zeit,psi_mem_some_avg10,psi_mem_full_avg10,psi_io_some_avg10,psi_mem_some_total_us,majfault_s,pswpin_s,pswpout_s,memavail_mib,swap_used_mib\n")
    alt, t_alt = vm(), time.time()
    while not os.path.exists(a.stopdatei):
        time.sleep(a.intervall)
        neu, t = vm(), time.time(); dt = t - t_alt
        pm, pi = psi("memory"), psi("io"); ma, sw = mem()
        f.write(f"{time.strftime('%H:%M:%S')},{pm['some']['avg10']},{pm['full']['avg10']},{pi['some']['avg10']},"
                f"{int(pm['some']['total'])},{(neu['pgmajfault']-alt['pgmajfault'])/dt:.1f},"
                f"{(neu['pswpin']-alt['pswpin'])/dt:.1f},{(neu['pswpout']-alt['pswpout'])/dt:.1f},{ma},{sw}\n")
        f.flush(); alt, t_alt = neu, t
