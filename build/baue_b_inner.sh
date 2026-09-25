#!/usr/bin/env bash
# Woertliche Uebertragung der RUN/COPY/ADD-Schritte aus Dockerfile.v0.29 (blazux/qwen3.8-Flash-DGX@d542745).
# Laeuft IM Container (Basis vllm/vllm-openai:v0.29.0); /bsrc = src/ des Repos (ro), /kdet = gepruefte Kernel-Dateien (ro).
set -euo pipefail
SP=/usr/local/lib/python3.12/dist-packages; PKG=${SP}/vllm/models/qwen4_exp/nvidia; PLE=${PKG}/ple_layer.py
# 1 PLE mmap
cp /bsrc/vllm_ple_mmap.py ${SP}/vllm_ple_mmap.py
cp ${PLE} ${PLE}.orig
printf '\n\n# --- qwen38-flash-dgx: serve the PLE n-gram table from disk (VLLM_PLE_MMAP=1) ---\nfrom vllm_ple_mmap import apply as _ple_mmap_apply\n_ple_mmap_apply(Qwen4ExpNGramEmbedding)\n' >> ${PLE}
python3 -c "import ast; ast.parse(open('${PLE}').read()); print('ple_layer.py patched OK')"
# 2 FLA
FLA_UTILS=${SP}/vllm/third_party/flash_linear_attention/ops/utils.py; FLA_CDH=${SP}/vllm/third_party/flash_linear_attention/ops/chunk_delta_h.py
sed -i 's|DEFAULT = 102400|DEFAULT = 101376  # spark-fla-shmem: GB10 99KiB, big GDN tiles fit|' ${FLA_UTILS}
grep -q "spark-fla-shmem" ${FLA_UTILS} && echo "fla shmem gate patched"
sed -i 's|for num_warps in \[2, 4\]|for num_warps in [2]  # spark-fla-warps: fla#953 Blackwell tl.dot race|' ${FLA_CDH}
grep -q "spark-fla-warps" ${FLA_CDH} && echo "fla num_warps pinned"
# 4 prefix caching block_size
python3 /bsrc/patch_mamba_block_size.py ${SP}
# 5 exact top-k
python3 /bsrc/patch_qsa_exact_topk.py ${PKG}/ops/qsa.py
# 6 hybrid
MO=${SP}/vllm/model_executor/layers/quantization/modelopt.py; QSA=${PKG}/qsa.py
cp /bsrc/vllm_fp8_hybrid_modelopt.py ${SP}/vllm_fp8_hybrid_modelopt.py
cp ${MO} ${MO}.orig
printf '\n\n# --- qwen38-flash-dgx: NVFP4 + blockwise-fp8 side layers (VLLM_FP8_HYBRID=1) ---\nfrom vllm_fp8_hybrid_modelopt import apply as _fp8_hybrid_apply\n_fp8_hybrid_apply()\n' >> ${MO}
python3 -c "import ast; ast.parse(open('${MO}').read()); print('modelopt.py hooked OK')"
cp ${QSA} ${QSA}.orig
sed -i 's/quant_config=model\.without_modelopt_fp4(quant_config)/quant_config=_fp8_hybrid_excluded(quant_config)/' ${QSA}
sed -i 's/^from \. import model$/from . import model\nfrom vllm_fp8_hybrid_modelopt import excluded_quant_config as _fp8_hybrid_excluded/' ${QSA}
grep -q "_fp8_hybrid_excluded(quant_config)" ${QSA} && grep -q "^from vllm_fp8_hybrid_modelopt import" ${QSA}
python3 -c "import ast; ast.parse(open('${QSA}').read()); print('qsa.py hooked OK')"
# 8 deterministic kernel
mkdir -p /opt/llm/kernel-det/src
cp /kdet/build_det.py /kdet/bindings_det.cpp /kdet/topk_det.cu /kdet/torch_utils.h /kdet/persistent_topk.cuh /opt/llm/kernel-det/src/
cp /kdet/qsadet_patch.py /tmp/qsadet_patch.py
cd /opt/llm/kernel-det/src && DET_BUILD_DIR=/opt/llm/kernel-det/build DET_ARCH=121a python3 build_det.py 2>&1 | tail -2
cp /opt/llm/kernel-det/build/_C_det.so /opt/llm/kernel-det/_C_det.so
VLLM_QSA_PY=${PKG}/ops/qsa.py python3 /tmp/qsadet_patch.py && rm /tmp/qsadet_patch.py
python3 -c "import ast; ast.parse(open('${PKG}/ops/qsa.py').read()); print('qsadet wired OK')"
# 10 draft vocab
cp /bsrc/draft_vocab_65536.npy /opt/llm/draft_vocab_65536.npy
python3 /bsrc/patch_mtp_draft_vocab.py ${PKG}/mtp.py
# 11 vllm#55513 backport
python3 /bsrc/patch_block_fp8_mtp.py ${SP}
echo "ALLE SCHRITTE OK"
