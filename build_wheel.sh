#!/bin/bash
#
# Build the cuVSLAM Python wheel with Podman.
#
# Adapted from the official docker/ build steps (cmake build of libcuvslam, then
# the scikit-build-core Python wheel). It does NOT use build_release.sh and has
# no RealSense. Python 3.10 / CUDA 13 (Ubuntu 22.04 base) -> a +cu13-cp310 wheel.
# The wheel is written to ./dist and verified on the host with
# cuvslam_runner/setup_env.sh + a TOML config (see the end of this script).
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
IMAGE="${IMAGE:-cuvslam-wheel-builder}"

echo "[1/2] Building the builder image with Podman ..."
podman build -f Dockerfile.wheel -t "$IMAGE" .

echo "[2/2] Building the wheel inside the container ..."
mkdir -p dist
podman run --rm \
    --userns=keep-id \
    --network host \
    -v "$(pwd):/cuvslam:Z" \
    -w /cuvslam \
    "$IMAGE" bash -c '
        set -e
        export CUDA_HOME=/usr/local/cuda
        export HOME=/tmp

        # 1) Build libcuvslam.so directly via cmake (NOT build_release.sh).
        #    CMAKE_CUDA_ARCHITECTURES=OFF: CUDA 13 dropped Maxwell/Pascal/Volta, so
        #    suppress CMake-injected gencode (its 52 default) and let the kernels
        #    target use its own "-arch=all" (the GPU-agnostic, CUDA-13-supported set).
        rm -rf /cuvslam/build
        cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=OFF \
              -S /cuvslam -B /cuvslam/build
        make -j"$(nproc)" -C /cuvslam/build cuvslam

        # 2) Build the Python wheel (scikit-build-core) into dist/.
        export CUVSLAM_BUILD_DIR=/cuvslam/build
        rm -f /cuvslam/dist/cuvslam-*.whl
        python3 -m build --wheel --no-isolation --outdir /cuvslam/dist /cuvslam/python

        # 3) In-container import smoke test (CUDA 13 runtime is present here).
        python3 -m pip install --force-reinstall /cuvslam/dist/cuvslam-*.whl
        python3 -c "import cuvslam; print(\"in-container import OK:\", cuvslam.get_version()[0])"
    '

echo
echo "Wheel built:"
ls -1 dist/cuvslam-*.whl
cat <<'EOF'

Verify on the host with the TOML runner (Python 3.10, no Docker):
  cd cuvslam_runner
  WHEEL="$(ls ../dist/cuvslam-*.whl)" ./setup_env.sh
  ./cuvslam_venv/bin/python run.py configs/kitti_slam.toml --check   # or a full run
  ./cleanup_env.sh
EOF
