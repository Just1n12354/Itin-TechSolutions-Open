#!/usr/bin/env bash
# run-goldvllm.sh - startet GoldVllm (Qwen3.8-Flash-Next-NVFP4 auf einem GB10 / DGX Spark / ASUS Ascent GX10).
# Exakt die Startzeile der verifizierten Produktion vom 25.09.2026, nur Pfade und Key als Variablen.
#
#   HF_CACHE=~/.cache/huggingface  VOCAB=/opt/gx10/draftvocab/draft_vocab_de_65536.npy  KEYFILE=~/.config/vllm.key \
#   ./run-goldvllm.sh
#
# Voraussetzungen: siehe ../INSTALL.md (Image gebaut, Modell-Revision geladen, KEYFILE mit einem Schluessel).
# Bereit nach ~14-15 min ("Application startup complete"). Pruefen: curl -H "Authorization: Bearer $(cat $KEYFILE)" localhost:8000/v1/models
set -euo pipefail
IMAGE="${IMAGE:-gx10-vllm:goldvllm}"
NAME="${NAME:-qwen38-flash}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
VOCAB="${VOCAB:-$(cd "$(dirname "$0")/../draftvocab" && pwd)/draft_vocab_de_65536.npy}"
KEYFILE="${KEYFILE:-$HOME/.config/vllm.key}"
PORT="${PORT:-8000}"
REV=7b719225242aacd3dbd3f9407468c2ee9a9d2594
SNAP=/hf/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/$REV

[ -s "$KEYFILE" ] || { echo "KEYFILE fehlt: $KEYFILE  (z. B. python3 -c 'import secrets;print(secrets.token_hex(32))' > $KEYFILE; chmod 600 $KEYFILE)"; exit 2; }
[ -d "$HF_CACHE/hub/models--RadixArk--Qwen3.8-Flash-Next-NVFP4/snapshots/$REV" ] || { echo "Modell-Revision $REV fehlt in $HF_CACHE (siehe INSTALL.md)"; exit 3; }
echo "a864739485e0804049fe3481eff53770157f4b76cd6d91f556ff91ce454a23a1  $VOCAB" | sha256sum -c --quiet || { echo "Draft-Vokabular fehlt oder SHA falsch: $VOCAB"; exit 4; }
[ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ] || { echo "GPU ist belegt - nie zwei Engines gleichzeitig"; exit 5; }

SPLIT='["vllm::unified_attention_with_output","vllm::unified_mla_attention_with_output","vllm::mamba_mixer2","vllm::mamba_mixer","vllm::short_conv","vllm::qwen4_exp_compute_ple_ngram_ids","vllm::qwen4_exp_ple_short_conv","vllm::qwen4_exp_qsa_with_output","vllm::linear_attention","vllm::qwen_gdn_attention_core","vllm::qwen_gdn_attention_core_fused_norm_packed","vllm::sparse_attn_indexer","vllm::ple_mmap_lookup_ids"]'

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart no \
  --gpus all --ipc=host --shm-size 16g -p "127.0.0.1:$PORT:8000" \
  -v "$HF_CACHE:/hf" -v "$VOCAB:/opt/llm/draft_vocab_custom.npy:ro" \
  -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
  -e VLLM_PLE_MMAP=1 -e VLLM_PLE_MMAP_WORKERS=32 -e VLLM_PLE_MMAP_PREWARM=0 -e VLLM_PLE_MMAP_MADVISE=random \
  -e VLLM_QSA_EXACT_TOPK=0 -e VLLM_FP8_PAD_M4=0 -e VLLM_USE_FLASHINFER_SAMPLER=1 -e VLLM_ALLOW_LONG_MAX_MODEL_LEN=0 \
  -e VLLM_MTP_DRAFT_VOCAB=/opt/llm/draft_vocab_custom.npy \
  "$IMAGE" "$SNAP" \
  --served-model-name qwen3.8-flash-next --host 0.0.0.0 --port 8000 --load-format safetensors \
  --max-model-len 262144 --max-num-seqs 16 --gpu-memory-utilization 0.80 \
  --enable-prefix-caching --enable-chunked-prefill --max-num-batched-tokens 8192 \
  -cc.cudagraph_mode=PIECEWISE "-cc.splitting_ops=$SPLIT" \
  --no-enable-flashinfer-autotune --kv-cache-dtype auto --kv-cache-memory-bytes 12884901888 \
  --api-key "$(tr -d '\n' < "$KEYFILE")" \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
  --speculative-config '{"method":"mtp","num_speculative_tokens":2}'
echo "gestartet: $NAME ($IMAGE). Log: docker logs -f $NAME"
