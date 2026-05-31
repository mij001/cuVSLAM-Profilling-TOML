#!/usr/bin/env bash
#
# Self-contained setup -> run -> teardown for cuvslam_runner.
#
# Creates a throwaway Python 3.10 venv, installs the runner dependencies and the
# locally built cuVSLAM wheel, verifies the install, runs the smoke tests, and
# (optionally) runs any configs you pass — then removes the venv on exit.
#
# Usage:
#   ./setup_and_run.sh                                  # install + verify + smoke tests
#   ./setup_and_run.sh configs/euroc_v1_eval.toml [...] # also run these configs
#
# Environment overrides:
#   PYBIN=python3.10   interpreter used to create the venv (must match the wheel)
#   WHEEL=/path/...whl  explicit wheel (default: newest ../dist/cuvslam-*.whl)
#   KEEP_VENV=1         skip teardown (keep cuvslam_venv for reuse)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PYBIN="${PYBIN:-python3.10}"
VENV="$HERE/cuvslam_venv"
WHEEL="${WHEEL:-$(ls -t "$HERE"/../dist/cuvslam-*.whl 2>/dev/null | head -1 || true)}"

cleanup() {
    # Always runs (success or failure): drop out of the venv and remove it.
    type deactivate >/dev/null 2>&1 && deactivate || true
    if [ "${KEEP_VENV:-0}" = "1" ]; then
        echo "[cleanup] KEEP_VENV=1 -> leaving $VENV in place"
    else
        rm -rf "$VENV"
        echo "[cleanup] removed $VENV"
    fi
}
trap cleanup EXIT

# --- setup ---------------------------------------------------------------- #
echo "[setup] creating venv with $PYBIN ..."
"$PYBIN" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install --upgrade pip >/dev/null || true
echo "[setup] installing runner requirements ..."
pip install -r requirements.txt

if [ -n "$WHEEL" ] && [ -f "$WHEEL" ]; then
    echo "[setup] installing cuVSLAM wheel: $WHEEL"
    pip install "$WHEEL"
else
    echo "[setup] WARNING: no cuVSLAM wheel found in ../dist (set WHEEL=...);" \
         "tracking will be unavailable, only validation will work." >&2
fi

# --- verify --------------------------------------------------------------- #
echo "[verify] importing cuvslam ..."
if python -c "import cuvslam; print('  cuvslam', cuvslam.get_version()[0])"; then
    HAVE_CUVSLAM=1
else
    echo "  cuvslam not importable; skipping tracking steps." >&2
    HAVE_CUVSLAM=0
fi

echo "[test] running smoke tests ..."
python tests/test_smoke.py

# --- run ------------------------------------------------------------------ #
if [ "$#" -gt 0 ]; then
    if [ "$HAVE_CUVSLAM" = "1" ]; then
        for cfg in "$@"; do
            echo "[run] $cfg"
            python run.py "$cfg"
        done
    else
        echo "[run] skipped (cuvslam unavailable); validating instead:"
        for cfg in "$@"; do python run.py "$cfg" --check; done
    fi
else
    echo "[run] no configs given. Validating all bundled configs:"
    # --check exits non-zero if a config's dataset/hardware is absent; that is
    # expected here, so don't let it abort the script.
    python run_all.py --check --log-dir "" || true
    echo "[run] tip: pass a config to actually track, e.g.:"
    echo "      ./setup_and_run.sh configs/euroc_v1_eval.toml"
fi

echo "[done] completed"
