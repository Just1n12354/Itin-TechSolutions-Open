# Ben/Hermes-Test 2026-09-25T15:12:26+02:00

| Prüfung | Ergebnis | Detail |
|---|---|---|
| /health | OK | HTTP 200 |
| API ohne Key abgewiesen | OK | HTTP 401 |
| API mit Key | OK | HTTP 200 |
| Tool-Call-Rundlauf (API) | OK | {"ok": true, "tool": "lagerbestand", "args": "{\"artikel\": \"FI-Schalter 40A/30mA\"}", "antwort": "37", "dauer_s": 8.3} |
| Ben normale Anfrage (hermes -z) | OK | 19s, Antwort: 391  |
| Ben mit echtem Tool (Terminal) | OK | 6s, Antwort: gx10  |
| Hermes-Session hat Tool-Call registriert | OK | tool_call_count=1 |
| Xid seit Start | OK | 0 |
| Linux-OOM-Kill seit Start | OK | 0 |
| CUDA-OOM/Engine-Fehler (vLLM-Log) | OK | 0 |
| Watchdog-Eingriffe seit Start | OK | 0 |
| NV_ERR-Einzelmeldungen (Info) | – | 1 |

MemAvailable 15467 MiB (Abstand Watchdog 7208 MiB), Swap belegt 7227 MiB

**BEN/HERMES-TEST: BESTANDEN**
