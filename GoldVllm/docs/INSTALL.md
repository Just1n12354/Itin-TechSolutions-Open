# Install GoldVllm

Goal: on a GB10 system (DGX Spark, ASUS Ascent GX10 or similar), start exactly the configuration that was measured here.
About 1 h, most of it for the model download (135 GB).

## 0 Prerequisites

| | tested with |
|---|---|
| Hardware | 1× NVIDIA GB10, 128 GB unified memory, NVMe with ≥ 200 GB free (model 135 GB) |
| OS | Ubuntu 24.04 (DGX OS base), kernel `7.0.0-1019-nvidia` |
| Driver / CUDA | `nvidia-driver-580-open 580.178.04`, CUDA 13.0 |
| Docker | 29.1.3 with nvidia-container-toolkit 1.20.0 (`--gpus all` must work) |
| Swap | 16 GB recommended (up to ~7 GB used in operation) |

```bash
docker run --rm --gpus all --entrypoint nvidia-smi vllm/vllm-openai:v0.29.0   # GPU visible inside a container?
```

## 1 Build the image

This is the official route of the patch repo: `Dockerfile.v0.29` at exactly the tested commit.

```bash
git clone https://github.com/blazux/qwen3.8-Flash-DGX.git && cd qwen3.8-Flash-DGX
git checkout d542745        # "Merge pull request #22 ... v029-backport-vllm-55513"
DOCKER_BUILDKIT=1 docker build -f Dockerfile.v0.29 -t gx10-vllm:goldvllm .
```

- The base is `vllm/vllm-openai:v0.29.0`. The Dockerfile also fetches the deterministic kernel `jschmied/qwen38-flash-next-gb10@e0ef69d`
  with SHA256 checks. The kernel is present but switched off in GoldVllm.
- **Use BuildKit.** On the GX10 the legacy builder read ~30 GB per step and would have taken ~2 h. Our image was therefore built as a
  literal 1-container transcript of the same Dockerfile (`build/baue_b_inner.sh`, 100 s; kept for documentation).
  Both routes are meant to put the same files into the image. We did not compare the two file by file.
  A rebuild will **not** be byte-identical to our image (`sha256:c4a75dcb…`), because timestamps differ.
- Check:

```bash
docker run --rm --entrypoint python3 gx10-vllm:goldvllm -c "import vllm;print(vllm.__version__)"   # 0.29.0
```

## 2 Download the model (this exact revision)

```bash
pip install -U "huggingface_hub[cli]"
hf download RadixArk/Qwen3.8-Flash-Next-NVFP4 --revision 7b719225242aacd3dbd3f9407468c2ee9a9d2594
# -> ~/.cache/huggingface/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/7b71922…
```

That is 419 files, 135.3 GB. Among them are 10 × `model-plefp8-*.safetensors`, which make up the PLE table (48 GB). vLLM memory-maps it.
Check all files and sizes against `data/model-snapshot-7b719225.tsv` (columns: file, blob, bytes; for safetensors the blob name is the SHA256).

## 3 Draft vocabulary and API key

```bash
sudo install -D -m 0444 draftvocab/draft_vocab_de_65536.npy /opt/gx10/draftvocab/draft_vocab_de_65536.npy
sha256sum /opt/gx10/draftvocab/draft_vocab_de_65536.npy   # a864739485e0804049fe3481eff53770157f4b76cd6d91f556ff91ce454a23a1
python3 -c 'import secrets;print(secrets.token_hex(32))' > ~/.config/vllm.key && chmod 600 ~/.config/vllm.key
```

For English or other workloads, build your own vocabulary. See `draftvocab/README.md`.

## 4 Start

```bash
VOCAB=/opt/gx10/draftvocab/draft_vocab_de_65536.npy KEYFILE=~/.config/vllm.key ./config/run-goldvllm.sh
docker logs -f qwen38-flash     # "Application startup complete" after ~14-15 min
```

`config/run-goldvllm.sh` produces the same launch line as our production container. We checked this on 25 Sep 2026 with a `docker` stub:
35/35 vLLM arguments and all project-specific env vars are identical. Every argument is explained in [CONFIGURATION.md](CONFIGURATION.md).

## 5 Verify correctness, not just /health

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/health        # 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/v1/models     # 401 (key required)
cd bench && VLLM_API_KEY=$(cat ~/.config/vllm.key) KORPUS_DIR=/path/to/txt \
  python3 gates.py --url http://127.0.0.1:8000 --label test --ausgabe gates.json   # "GATES OK"
```

The gates check:
- the 12-task quality set (tool calls, math, logic, multi-step, error case, needle),
- 6 exact calculations,
- retrieval from 30k and 80k documents,
- repeatability and collapse detection,
- a tool round trip.

`KORPUS_DIR` points to any `*.txt` files (manuals etc.); the long-context documents are cut from them.
Use real text: the built-in fallback is a repeated sentence, and with prefix caching that would flatter the numbers.

## 6 Run it 24/7

systemd unit, RAM watchdog, recovery: [OPERATIONS.md](OPERATIONS.md). **Do not skip the watchdog.** On unified memory, running out of
memory takes the whole system down, not just the engine.

## 7 Measure

[BENCHMARKING.md](BENCHMARKING.md).
