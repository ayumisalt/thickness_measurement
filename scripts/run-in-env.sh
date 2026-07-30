#!/usr/bin/env bash
#
# Run one command in the thickness-measurement micromamba environment while
# isolating it from site-wide Python, ROOT, compiler and pkg-config settings.

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: THICKNESS_MAMBA_EXE=/path/to/micromamba $0 COMMAND [ARG ...]" >&2
  exit 2
fi

environment_name="${THICKNESS_ENV_NAME:-thickness-measurement}"
mamba_root="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"

if [[ -n "${THICKNESS_MAMBA_EXE:-}" ]]; then
  mamba_executable="$THICKNESS_MAMBA_EXE"
elif [[ -x "$HOME/bin/micromamba" ]]; then
  mamba_executable="$HOME/bin/micromamba"
else
  echo "error: set THICKNESS_MAMBA_EXE to a micromamba executable" >&2
  exit 2
fi

if [[ ! -x "$mamba_executable" ]]; then
  echo "error: micromamba is not executable: $mamba_executable" >&2
  exit 2
fi

if [[ -L "$mamba_executable" ]]; then
  echo "error: micromamba 2.6 must be a real file, not a symlink" >&2
  exit 2
fi

case "$(basename "$mamba_executable")" in
micromamba | mamba) ;;
*)
  echo "error: micromamba filename must be 'micromamba' or 'mamba'" >&2
  exit 2
  ;;
esac

exec env \
  -u MAMBA_EXE \
  -u PYTHONPATH \
  -u PYTHONHOME \
  -u ROOTSYS \
  -u CMAKE_PREFIX_PATH \
  -u CPATH \
  -u C_INCLUDE_PATH \
  -u CPLUS_INCLUDE_PATH \
  -u LIBRARY_PATH \
  -u LD_LIBRARY_PATH \
  -u PKG_CONFIG_PATH \
  PYTHONNOUSERSITE=1 \
  MAMBA_ROOT_PREFIX="$mamba_root" \
  "$mamba_executable" \
  --root-prefix "$mamba_root" \
  run --name "$environment_name" \
  "$@"
