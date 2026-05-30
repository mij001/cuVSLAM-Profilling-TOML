#!/bin/bash
set -e

# Build the minimalist docker image
echo "Building docker image..."
docker build -f Dockerfile.wheel -t cuvslam-wheel-builder .

echo "Running build inside the container..."
# Run as your current user to avoid creating root-owned files on your host
docker run --rm \
    -u $(id -u):$(id -g) \
    -v "$(pwd):/cuvslam" \
    -w /cuvslam \
    cuvslam-wheel-builder bash -c "
        export CUVSLAM_SRC_DIR=/cuvslam
        export CUVSLAM_DST_DIR=/cuvslam/build
        
        # 1. Build libcuvslam using their official script
        ./build_release.sh
        
        # 2. Build the python wheel
        echo 'Building Python wheel...'
        export CUVSLAM_BUILD_DIR=/cuvslam/build
        export HOME=/tmp
        pip3 wheel ./python/ -w /cuvslam/dist/ --no-deps
    "

echo "Success! The Python wheel is located in the dist/ directory and owned by your user."
