# Running GoldVllm 24/7

## Lifecycle

- **systemd owns the container.** `config/systemd/llm-server.service` is `oneshot` with `RemainAfterExit`. It waits for the driver,
  starts via `run-goldvllm.sh` and only counts as started once the API answers. Docker restarts nothing (`--restart no`).
- After a cold start the model is ready in **14–15 min** (measured 852–902 s). Clients have no backend until then.
- **Never two engines at once.** `run-goldvllm.sh` refuses to start when the GPU is busy.

## RAM watchdog (mandatory)

`config/schutz/llm-memory-guard.{sh,service,timer}` runs every 10 s. At **122 GB of used RAM** it stops every LLM container
(image or container name containing `vllm|sglang|ollama|llama|text-generation`) and any native server.

Why 122 and not higher: at 126 GB, cuBLAS aborted with `CUBLAS_STATUS_INTERNAL_ERROR` instead of stopping cleanly.
Memory is therefore bounded by the fixed KV cache, not by the watchdog.

## Recovery after a watchdog stop

`config/schutz/llm-recovery.{sh,service,timer}` runs every minute. It brings the server back **only** if:
1. the watchdog stopped it and the event has not been handled yet;
2. the production container is not running, and no test (`bench-*`) or start is in progress;
3. memory has recovered stably (3 checks in a row with ≥ 114,000 MiB free);
4. the GPU answers and no Xid has occurred since the event;
5. the budget allows it (max. 2 attempts per 6 h, 10 min apart); otherwise it stays FAILED until `--reset`.

To disable it without uninstalling: `touch /etc/llm-recovery.disabled`.
The file is the author's version. Its health check calls device-specific verify scripts, so adapt that part.

> **Pitfall (found and fixed on 25 Sep 2026):** the recovery runs as root and calls the check via `sudo -u <user>`.
> There, `systemctl --user` fails ("Failed to connect to bus") unless `XDG_RUNTIME_DIR` is set. As a result a healthy vLLM
> would have been judged broken and restarted twice. Fix: set `XDG_RUNTIME_DIR=/run/user/<uid>`. Our simulated tests had not caught it.

## Checking

- `/health 200` is **not** enough. Run `bench/gates.py` and one real tool call before any benchmark and after any change.
- The author's machine has a frozen restore point: a write-protected backup (`chattr +i`) of 30 files (units, scripts, key files,
  draft vocabulary) with SHA256, owner and mode, the image tar, and the model manifest. A verify script compares the live
  system against it, and a restore script brings it back in one command. After the SGLang test it ran for real: 814 s,
  0 of 30 files differing, all checks green afterwards. Worth copying as a pattern.

## Pitfalls we hit

| Finding | Effect | Countermeasure |
|---|---|---|
| no DKMS for the NVIDIA modules | after a kernel update, GPU and desktop are gone | hold kernel updates; check the modules at boot |
| `NV_ERR_NO_MEMORY` info lines in the kernel log during load | harmless, not an Xid | don't mistake them for real errors |
| settings duplicated in start scripts | a reboot silently reset the KV size | keep each value in **one** place; verify after every reboot |
| production scripts with fixed paths into a git repo | renaming a folder disabled the recovery | install operational scripts outside the repo (`/opt/...`) |
| `unless-stopped` restart policy | did not survive a reboot | let systemd own the lifecycle |
