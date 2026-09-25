# GoldVllm installieren

Ziel: auf einem GB10-System (DGX Spark, ASUS Ascent GX10 o. ä.) exakt die Konfiguration starten, die hier gemessen wurde.
Dauer: rund 1 h, davon das meiste für den Modell-Download (135 GB).

## 0 Voraussetzungen

| | getestet mit |
|---|---|
| Hardware | 1× NVIDIA GB10, 128 GB Unified Memory, NVMe mit ≥ 200 GB frei (Modell 135 GB) |
| OS | Ubuntu 24.04 (DGX-OS-Basis), Kernel `7.0.0-1019-nvidia` |
| Treiber / CUDA | `nvidia-driver-580-open 580.178.04`, CUDA 13.0 |
| Docker | 29.1.3 mit nvidia-container-toolkit 1.20.0 (`--gpus all` muss gehen) |
| Swap | 16 GB empfohlen (gemessen: bis ~7 GB belegt) |

```bash
docker run --rm --gpus all --entrypoint nvidia-smi vllm/vllm-openai:v0.29.0   # GPU im Container sichtbar?
```

## 1 Image bauen

Der offizielle Weg des Patch-Repos: `Dockerfile.v0.29` auf genau dem getesteten Commit.

```bash
git clone https://github.com/blazux/qwen3.8-Flash-DGX.git && cd qwen3.8-Flash-DGX
git checkout d542745        # GoldVllm-Stand ("Merge pull request #22 ... v029-backport-vllm-55513")
DOCKER_BUILDKIT=1 docker build -f Dockerfile.v0.29 -t gx10-vllm:goldvllm .
```

- Basis ist `vllm/vllm-openai:v0.29.0`. Das Dockerfile lädt zusätzlich den deterministischen Kernel `jschmied/qwen38-flash-next-gb10@e0ef69d`
  mit SHA256-Prüfsummen. Der Kernel ist in GoldVllm ausgeschaltet.
- **BuildKit verwenden.** Der Legacy-Builder las auf dem GX10 je Schritt ~30 GB und hätte ~2 h gebraucht. Unser Image entstand deshalb als
  wörtliche 1-Container-Übertragung desselben Dockerfiles (`build/baue_b_inner.sh`, 100 s, Dokumentation). Beide Wege sollen dieselben
  Dateien ins Image bringen (wörtliche Übertragung, Kernel-Dateien per SHA256 geprüft). Einen Datei-für-Datei-Vergleich der beiden Wege haben wir nicht gemacht. **Byte-gleich** mit unserem Image (`sha256:c4a75dcb…`) wird ein Neubau trotzdem nicht, weil Zeitstempel einfliessen.
- Prüfen:

```bash
docker run --rm --entrypoint python3 gx10-vllm:goldvllm -c "import vllm;print(vllm.__version__)"   # 0.29.0
```

## 2 Modell laden (genau diese Revision)

```bash
pip install -U "huggingface_hub[cli]"
hf download RadixArk/Qwen3.8-Flash-Next-NVFP4 --revision 7b719225242aacd3dbd3f9407468c2ee9a9d2594
# landet in ~/.cache/huggingface/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/7b71922…
```

Das ergibt 419 Dateien mit zusammen 135.3 GB. Darunter sind 10 × `model-plefp8-*.safetensors`, das ist die PLE-Tabelle (48 GB), die vLLM per mmap liest.
Kontrolle aller Dateien und Grössen: Manifest `daten/model-snapshot-7b719225.tsv` (Spalten Datei, Blob, Bytes; bei Safetensors ist der Blob-Name der SHA256).

## 3 Draft-Vokabular und API-Key

```bash
sudo install -D -m 0444 draftvocab/draft_vocab_de_65536.npy /opt/gx10/draftvocab/draft_vocab_de_65536.npy
sha256sum /opt/gx10/draftvocab/draft_vocab_de_65536.npy   # a864739485e0804049fe3481eff53770157f4b76cd6d91f556ff91ce454a23a1
python3 -c 'import secrets;print(secrets.token_hex(32))' > ~/.config/vllm.key && chmod 600 ~/.config/vllm.key
```

Für englische oder andere Arbeitslasten: eigenes Vokabular bauen, siehe `draftvocab/README.md`.

## 4 Starten

```bash
VOCAB=/opt/gx10/draftvocab/draft_vocab_de_65536.npy KEYFILE=~/.config/vllm.key ./config/run-goldvllm.sh
docker logs -f qwen38-flash     # "Application startup complete" nach ~14-15 min
```

`config/run-goldvllm.sh` erzeugt dieselbe Startzeile wie die laufende Produktion: 35/35 vLLM-Argumente und alle projektspezifischen
Umgebungsvariablen identisch, geprüft am 25.09.2026 mit einer `docker`-Attrappe. Jedes Argument ist in [KONFIGURATION.md](KONFIGURATION.md) erklärt.

## 5 Prüfen, nicht nur /health

`/health 200` heisst nur, dass der Server läuft. Er kann trotzdem **falsch rechnen**, etwa bei stiller Output-Korruption durch Kernel- oder Spekulationsfehler.
Deshalb gibt es die Gates aus dem Mess-Kit:

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/health                                   # 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/v1/models                                # 401 (Key Pflicht)
cd bench && VLLM_API_KEY=$(cat ~/.config/vllm.key) KORPUS_DIR=/pfad/zu/txt-dateien \
  python3 gates.py --url http://127.0.0.1:8000 --label test --ausgabe gates.json                 # "GATES OK"
```

`gates.py` prüft: das Qualitätsset mit 12 Aufgaben (Tool-Calls, Rechnen, Logik, Mehrschritt, Fehlerfall, Nadel), 6 exakte Rechnungen,
Retrieval in 30k- und 80k-Dokumenten, Wiederholbarkeit und Kollaps-Erkennung sowie einen Tool-Rundlauf.
`KORPUS_DIR` zeigt auf beliebige `*.txt` (Handbücher o. ä.), daraus entstehen die Langkontext-Dokumente.

## 6 Dauerbetrieb

systemd-Unit, RAM-Wächter und Recovery: [BETRIEB.md](BETRIEB.md). **Den RAM-Wächter nicht weglassen.** Auf Unified Memory
reisst ein vollgelaufener Speicher sonst das ganze System mit.

## 7 Messen

```bash
cd bench
export VLLM_BASIS_URL=http://127.0.0.1:8000 VLLM_API_KEY=$(cat ~/.config/vllm.key) VLLM_CONTAINER=qwen38-flash KORPUS_DIR=/pfad/zu/txt
python3 aufwaermen.py --container qwen38-flash --hoechstdauer 900
python3 benchmark_gx10.py --nur-schnell --agent-schritte 30 --ausgabe g30.json     # G30, TTUA, TP1/2/4
python3 nacht_bench.py --url $VLLM_BASIS_URL --label mein-lauf --ausgabe nacht.json  # Decode, TTFT 30k/80k/110k, Agent 30k/80k, Qualität
```

Methodik und Vergleichswerte: [ERGEBNISSE.md](ERGEBNISSE.md).
