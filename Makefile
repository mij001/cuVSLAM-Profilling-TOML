# cuVSLAM wheel build + verification (Podman, CUDA 13, Python 3.10).
# See build_wheel.sh (build) and cuvslam_runner/setup_env.sh (host install/check).

.PHONY: help wheel verify check clean all
.DEFAULT_GOAL := help

RUNNER := cuvslam_runner
# Config used by `verify`/`check`; override on the CLI: make verify TOML=configs/euroc_v1_eval.toml
TOML := configs/kitti_eval.toml

help:
	@echo "make wheel   - build the cuVSLAM wheel into dist/ (Podman, no RealSense)"
	@echo "make verify  - install the built wheel via setup_env and run $(TOML)"
	@echo "make check   - install the built wheel and validate $(TOML) (no dataset needed to import)"
	@echo "make clean   - remove the runner venv"
	@echo "make all     - wheel + verify"

# Build libcuvslam (cmake) and the scikit-build-core wheel -> dist/.
wheel:
	./build_wheel.sh

# Install the newest dist/ wheel into the runner venv (setup_env verifies the
# import) and run a TOML config to confirm tracking works on the host.
verify:
	cd $(RUNNER) && ./setup_env.sh
	cd $(RUNNER) && ./cuvslam_venv/bin/python run.py $(TOML)

# Same install, but only validate the config.
check:
	cd $(RUNNER) && ./setup_env.sh
	cd $(RUNNER) && ./cuvslam_venv/bin/python run.py $(TOML) --check

# Remove the runner venv.
clean:
	cd $(RUNNER) && ./cleanup_env.sh

all: wheel verify
