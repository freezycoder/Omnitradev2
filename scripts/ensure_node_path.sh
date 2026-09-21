#!/usr/bin/env bash
# Double-clicked .command files do not load shell profiles, so nvm and Homebrew
# Node are often missing from PATH. Source this file, then call ensure_node_on_path.

ensure_node_on_path() {
  if command -v npm >/dev/null 2>&1; then
    return 0
  fi

  local candidates=()
  candidates+=(
    /opt/homebrew/bin
    /usr/local/bin
    "${HOME}/.local/bin"
    /opt/local/bin
    "${HOME}/.volta/bin"
  )

  local nvm_root="${NVM_DIR:-${HOME}/.nvm}/versions/node"
  local best=""
  local best_key=""
  local dir ver major minor patch key
  if [[ -d "$nvm_root" ]]; then
    for dir in "$nvm_root"/v*; do
      [[ -x "${dir}/bin/npm" ]] || continue
      ver="${dir##*/v}"
      ver="${ver%%-*}"
      IFS=. read -r major minor patch <<<"$ver"
      key="$(printf '%05d%05d%05d' "${major:-0}" "${minor:-0}" "${patch:-0}")"
      if [[ -z "$best_key" || "$key" > "$best_key" ]]; then
        best_key="$key"
        best="$dir"
      fi
    done
    if [[ -n "$best" ]]; then
      candidates+=("${best}/bin")
    fi
  fi

  for dir in "${candidates[@]}"; do
    if [[ -x "${dir}/npm" ]]; then
      export PATH="${dir}:${PATH}"
      hash -r 2>/dev/null || true
      return 0
    fi
  done

  local nvm_sh="${NVM_DIR:-${HOME}/.nvm}/nvm.sh"
  if [[ -s "$nvm_sh" ]]; then
    # shellcheck disable=SC1090
    source "$nvm_sh"
    if command -v npm >/dev/null 2>&1; then
      return 0
    fi
  fi

  return 1
}
