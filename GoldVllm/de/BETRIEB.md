# GoldVllm — Dauerbetrieb

## Lebenszyklus

- **systemd besitzt den Container.** `config/systemd/llm-server.service` ist `oneshot` mit `RemainAfterExit`. Der Start wartet auf den
  Treiber, startet über `run-goldvllm.sh` und gilt erst als fertig, wenn die API antwortet. Docker selbst startet nichts neu (`--restart no`).
- Nach einem Kaltstart ist das Modell nach **14–15 min** bereit (gemessen 852–902 s). So lange sind die Clients ohne Backend.
- **Nie zwei Engines gleichzeitig.** Auf Unified Memory teilen sich GPU und System denselben Speicher. Eine zweite Engine
  (Test, Benchmark, anderer Server) drückt beide in den Swap. `run-goldvllm.sh` bricht ab, wenn die GPU belegt ist.

## RAM-Wächter (Pflicht)

`config/schutz/llm-memory-guard.{sh,service,timer}`: prüft alle 10 s. Ab **122 GB belegtem RAM** stoppt er alle LLM-Container
(`vllm|sglang|ollama|llama|text-generation` im Image- oder Containernamen) und native Server.

Warum 122 und nicht höher: Mit 126 GB brach bei uns cuBLAS mit `CUBLAS_STATUS_INTERNAL_ERROR` ab statt sauber zu stoppen.
Begrenzt wird der Speicher deshalb über den festen KV-Cache, nicht über den Wächter.

## Recovery nach einem Wächter-Stopp

`config/schutz/llm-recovery.{sh,service,timer}` (jede Minute). Die Recovery holt den Server **nur** zurück, wenn:
1. der Wächter gestoppt hat und das Ereignis noch nicht behandelt ist,
2. der Produktionscontainer nicht läuft und kein Test (`bench-*`) und kein Start läuft,
3. der Speicher sich stabil erholt hat (3× in Folge ≥ 114'000 MiB frei),
4. die GPU antwortet und seit dem Ereignis kein Xid kam,
5. das Budget reicht (max. 2 Versuche je 6 h, 10 min Abstand), sonst Zustand FAILED bis `--reset`.

Stilllegen ohne Deinstallation: `touch /etc/llm-recovery.disabled`.
Einrichten: `llm-recovery.sh` nach `/usr/local/sbin/`, `.service`/`.timer` nach `/etc/systemd/system/`, und
`config/schutz/llm-recovery.default` als `/etc/default/llm-recovery` ablegen. Dort **muss** `LLMR_KEYFILE` stehen, sonst bleibt die
Recovery inaktiv und meldet das im Journal. „Gesund“ heisst: `/health` 200 und `/v1/models` mit Key 200. Optional prüft
`LLMR_HEALTH_CMD` zusätzlich, etwa mit `bench/gates.py`. Zustand ansehen: `llm-recovery.sh --status`.
Auf dem gx10 des Autors läuft eine erweiterte Fassung, die zusätzlich gegen das versiegelte Backup prüft.

> **Stolperstein (am 25.09.2026 gefunden und behoben):** Die Recovery läuft als root und ruft die Prüfung mit `sudo -u <nutzer>` auf.
> Dort scheitert `systemctl --user` („Failed to connect to bus“), wenn `XDG_RUNTIME_DIR` fehlt. Die Folge: Ein gesundes vLLM galt als krank.
> Lösung: `XDG_RUNTIME_DIR=/run/user/<uid>` setzen. Die Repo-Fassung macht das selbst, wenn `LLMR_HEALTH_USER` gesetzt ist.

## Prüfen

- `/health 200` reicht **nicht**. Vor jeder Messung und nach jeder Änderung laufen `bench/gates.py`
  (Qualität 12/12, exakte Rechnungen, Retrieval, Kollaps) und ein echter Tool-Call.
- Auf dem gx10 des Autors vergleicht ein Verify-Skript (nicht im öffentlichen Repo) den Ist-Zustand mit dem versiegelten Backup:
  30 Dateien mit SHA256, Besitzer und Rechten, dazu Image-ID, Modell-Snapshot, Kernel, Treiber, Docker und Units.
  Ergebnis ist `GOLDVLLM OK` oder `GOLDVLLM DRIFT`.

## Restore Point

Auf dem gx10 ist dieser Stand eingefroren: Backup mit `chattr +i`, das Image zusätzlich als `gx10-vllm:goldvllm` getaggt.
Der Rückweg aus jedem Experiment ist ein Befehl, `restore-goldvllm.sh --ausfuehren`. Am 25.09.2026 nach dem SGLang-Test real
ausgeführt: 814 s, keine Datei abweichend, danach alles grün. Das Prinzip lässt sich übertragen.

## Stolpersteine aus dem Betrieb

| Befund | Folge | Gegenmittel |
|---|---|---|
| Kein DKMS für die NVIDIA-Module | Nach einem Kernel-Update fehlen GPU und Desktop | Kernel-Updates halten, `nvidia-module-guard` prüft beim Boot |
| `NV_ERR_NO_MEMORY`-Infozeilen im Kernel-Log beim Laden | harmlos, kein Xid | nicht mit echten Fehlern verwechseln |
| Katalogwerte in Startskripten | Ein Reboot setzte den KV-Wert still zurück | Werte an **einer** Stelle pflegen, nach jedem Reboot prüfen |
| Produktionsskripte mit festen Pfaden in ein Git-Repo | eine Ordner-Umbenennung legt die Recovery lahm | Betriebsskripte ausserhalb des Repos installieren (`/opt/...`) |
