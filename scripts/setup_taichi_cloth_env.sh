#!/usr/bin/env bash
set -euo pipefail

workspace="${SIM_HARNESS_WORKSPACE:-${HOME}/SimulatorWorkspace/physics_aware_harness}"
python_bin="${PYTHON_BIN:-python3.11}"
env_dir="${workspace}/envs/taichi"

if ! command -v "${python_bin}" >/dev/null 2>&1; then
  echo "Missing ${python_bin}. Install Python 3.11, then rerun with PYTHON_BIN=/absolute/path/to/python3.11." >&2
  exit 2
fi

"${python_bin}" - <<'PY'
import sys
if sys.version_info[:2] != (3, 11):
    raise SystemExit(f"Taichi cloth env requires Python 3.11; got {sys.version.split()[0]}")
PY

"${python_bin}" -m venv "${env_dir}"
"${env_dir}/bin/python" -m pip install --upgrade pip
"${env_dir}/bin/python" -m pip install "taichi==1.7.4"
"${env_dir}/bin/python" -c 'import taichi as ti; print(f"Taichi {ti.__version__} ready")'
echo "Set SIM_TAICHI_PYTHON=${env_dir}/bin/python when using a non-default workspace."
