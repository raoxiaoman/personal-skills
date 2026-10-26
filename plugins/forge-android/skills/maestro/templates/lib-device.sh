#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/device-android.sh"

maestro_phase() {
  local serial flow="$2" phase="$3"
  serial="$(resolve_serial "$1")" || return 1
  shift 3
  maestro --device "$serial" test -e PHASE="$phase" "$@" "$flow"
}

# 不覆盖调用方清理逻辑；已有 trap 时由项目显式组合恢复步骤。
restore_wifi_on_exit() {
  local serial original existing signal
  for signal in EXIT INT TERM; do
    existing="$(trap -p "$signal")"
    if [[ -n "$existing" ]]; then
      printf '已有 %s trap，请显式组合 Wi-Fi 恢复步骤\n' "$signal" >&2
      return 1
    fi
  done
  serial="$(resolve_serial "$1")" || return 1
  original="$(device_wifi_state "$serial")" || return 1
  FORGE_WIFI_SERIAL="$serial"
  case "$original" in
    0) FORGE_WIFI_ORIGINAL=off ;;
    1) FORGE_WIFI_ORIGINAL=on ;;
    *) return 1 ;;
  esac
  trap 'code=$?; trap - EXIT; if ! device_wifi "$FORGE_WIFI_SERIAL" "$FORGE_WIFI_ORIGINAL"; then printf "%s\n" "Wi-Fi 恢复失败，请人工核对原状态" >&2; if [[ $code -eq 0 ]]; then code=1; fi; fi; exit "$code"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

require_confirm() {
  local what="$1"
  if [[ "${CONFIRM:-}" != yes ]]; then
    printf '未执行。%s\n确认副作用和当前目标后，使用 CONFIRM=yes 重跑。\n' "$what" >&2
    return 1
  fi
}
