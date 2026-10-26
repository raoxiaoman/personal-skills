#!/usr/bin/env bash
# 由 lib-device.sh 引入；包名和首页标识须替换为项目实际值。
PKG="<APP_ID>"

resolve_serial() {
  local given="${1:-}" bound="${ANDROID_SERIAL:-}" state
  if [[ -z "$bound" || ( -n "$given" && "$given" != "$bound" ) ]]; then
    printf '%s\n' '设备未绑定或显式序列号与 ANDROID_SERIAL 冲突' >&2
    return 1
  fi
  state="$(adb -s "$bound" get-state)" || return 1
  if [[ "${state%$'\r'}" != device ]]; then
    printf '%s\n' '当前绑定设备不可用' >&2
    return 1
  fi
  printf '%s\n' "$bound"
}

device_wifi_state() {
  local serial state
  serial="$(resolve_serial "$1")" || return 1
  state="$(adb -s "$serial" shell settings get global wifi_on)" || return 1
  state="${state%$'\r'}"
  case "$state" in
    0|1) printf '%s\n' "$state" ;;
    *) printf '无法识别 Wi-Fi 开关状态：%s\n' "$state" >&2; return 1 ;;
  esac
}

# 只控制 Wi-Fi，不控制蜂窝、VPN 或以太网，不证明应用已经断网。
device_wifi() {
  local serial action="$2" want cmd svc got i
  serial="$(resolve_serial "$1")" || return 1
  case "$action" in
    on) want=1; cmd=enabled; svc=enable ;;
    off) want=0; cmd=disabled; svc=disable ;;
    *) printf '%s\n' 'device_wifi: action 必须是 on/off' >&2; return 1 ;;
  esac
  if ! adb -s "$serial" shell cmd wifi set-wifi-enabled "$cmd"; then
    adb -s "$serial" shell svc wifi "$svc" || return 1
  fi
  for ((i=0; i<10; i++)); do
    got="$(device_wifi_state "$serial")" || return 1
    [[ "$got" == "$want" ]] && return 0
    sleep 0.2
  done
  printf 'Wi-Fi 切换未生效：期望 %s，实际 %s\n' "$want" "$got" >&2
  return 1
}

device_info() {
  local serial p value
  serial="$(resolve_serial "$1")" || return 1
  printf 'serial %s\n' "$serial"
  for p in ro.product.model ro.build.version.sdk ro.build.version.release ro.product.manufacturer persist.sys.locale; do
    value="$(adb -s "$serial" shell getprop "$p")" || return 1
    printf '%s %s\n' "$p" "${value%$'\r'}"
  done
  adb -s "$serial" shell wm size || return 1
  adb -s "$serial" shell wm density || return 1
  value="$(device_wifi_state "$serial")" || return 1
  printf 'wifi_on %s\n' "$value"
}

# 这是显示尺寸，不是应用窗口或已旋转后的控件坐标系。
device_screen_size() {
  local serial raw line physical="" override="" size w h
  serial="$(resolve_serial "$1")" || return 1
  raw="$(adb -s "$serial" shell wm size)" || return 1
  while IFS= read -r line; do
    line="${line%$'\r'}"
    case "$line" in
      'Physical size: '*)
        [[ -z "$physical" ]] || return 1
        physical="${line#Physical size: }" ;;
      'Override size: '*)
        [[ -z "$override" ]] || return 1
        override="${line#Override size: }" ;;
      '') ;;
      *) printf '无法识别 wm size 输出：%s\n' "$line" >&2; return 1 ;;
    esac
  done <<< "$raw"
  size="${override:-$physical}"
  if [[ ! "$size" =~ ^[1-9][0-9]*x[1-9][0-9]*$ ]]; then
    printf '无法确定显示尺寸：%s\n' "$raw" >&2
    return 1
  fi
  w="${size%x*}"; h="${size#*x}"
  printf '%s %s\n' "$w" "$h"
}

# 仅用于已确认全屏、方向和当前坐标系的能力缺口场景。
device_tap_pct() {
  local serial xpct="$2" ypct="$3" dims w h
  serial="$(resolve_serial "$1")" || return 1
  if [[ ! "$xpct" =~ ^(100|[1-9]?[0-9])$ || ! "$ypct" =~ ^(100|[1-9]?[0-9])$ ]]; then
    printf '%s\n' '百分比必须是 0 到 100 的整数' >&2
    return 1
  fi
  dims="$(device_screen_size "$serial")" || return 1
  w="${dims% *}"; h="${dims#* }"
  adb -s "$serial" shell input tap "$(( (w - 1) * xpct / 100 ))" "$(( (h - 1) * ypct / 100 ))"
}

device_ui_dump() {
  local serial remote data status=0
  serial="$(resolve_serial "$1")" || return 1
  remote="$(adb -s "$serial" shell mktemp /data/local/tmp/forge-maestro-ui.XXXXXX)" || return 1
  remote="${remote%$'\r'}"
  if [[ ! "$remote" =~ ^/data/local/tmp/forge-maestro-ui\.[a-zA-Z0-9]+$ ]]; then
    printf '%s\n' '设备未返回有效的独立 dump 路径' >&2
    return 1
  fi
  if adb -s "$serial" shell uiautomator dump "$remote" >/dev/null; then
    data="$(adb -s "$serial" shell cat "$remote")" || status=1
    [[ "$data" == *'<hierarchy'* ]] || status=1
  else
    status=1
  fi
  adb -s "$serial" shell rm -f "$remote" || status=1
  [[ "$status" == 0 ]] || return 1
  printf '%s\n' "$data"
}

app_restart_home() {
  local serial i dump
  serial="$(resolve_serial "$1")" || return 1
  if [[ "$PKG" == '<APP_ID>' || -z "$PKG" ]]; then
    printf '%s\n' '先替换项目包名和首页标识；页面操作优先使用 Maestro flow' >&2
    return 1
  fi
  adb -s "$serial" shell am force-stop "$PKG" || return 1
  adb -s "$serial" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null || return 1
  for ((i=0; i<15; i++)); do
    dump="$(device_ui_dump "$serial")" || return 1
    [[ "$dump" == *'<HOME_MARKER>'* ]] && return 0
    sleep 1
  done
  printf '%s\n' '等待首页超时，不自动返回或关闭弹窗' >&2
  return 1
}

# 只有当前 Maestro 无法满足已确认时间窗时使用，次数不等于实际触达次数。
device_repeat_tap() {
  local serial x="$2" y="$3" count="$4"
  serial="$(resolve_serial "$1")" || return 1
  if [[ ! "$x" =~ ^(0|[1-9][0-9]*)$ || ! "$y" =~ ^(0|[1-9][0-9]*)$ || ! "$count" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s\n' '坐标须为非负整数，次数须为正整数' >&2
    return 1
  fi
  adb -s "$serial" shell "i=0; while [ \$i -lt $count ]; do input tap $x $y || exit; i=\$((i+1)); done"
}
