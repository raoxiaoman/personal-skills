# shell 编排

## 使用条件

常见用途包括跨调用保持状态、阶段间固定时间窗、设备状态切换和多阶段组合，不是穷尽分类。普通页面加载先使用 Maestro 状态等待；外部编排应减少复杂度，而非把所有 flow 再包一层。

页面操作仍由 Maestro 执行。ADB 用于已授权的设备状态、进程或文件操作；高频时间窗等降级须有当前工具限制与测量证据。

## 最小结构

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib-device.sh"
FLOW="$SCRIPT_DIR/../<功能>/<场景>.yaml"
SERIAL="$(resolve_serial "${1:-}")" || exit 1

restore_wifi_on_exit "$SERIAL"
maestro_phase "$SERIAL" "$FLOW" prepare
device_wifi "$SERIAL" off
maestro_phase "$SERIAL" "$FLOW" wifi_disabled
```

`resolve_serial` 仅接受当前 `ANDROID_SERIAL` 的目标，拒绝显式冲突并检查 `get-state`；未绑定不自动选机。flow 绝对路径从脚本位置推导，不依赖调用目录。

这里只控制 Wi-Fi，不保证设备离线。若场景需要完全断网，先确认其他承载网络及连通性；缺少安全、已授权的构造方式就记录限制，不擅自关蜂窝或 VPN。

跨调用用 `PHASE` 分支时，保持分支互斥，显式传所需参数，并确认前阶段留下的页面状态仍存在：

```yaml
- runFlow:
    when:
      true: ${PHASE === 'prepare'}
    commands: [...]
- runFlow:
    when:
      true: ${PHASE === 'wifi_disabled'}
    commands: [...]
```

## 原状态恢复

`restore_wifi_on_exit "$SERIAL"` 在切换前读取并保存 Wi-Fi 原值，退出时恢复原值并回读；初始关闭就恢复关闭，不是一律开网。业务成功但恢复失败也须非零，业务原本失败则保留失败结论并报告恢复结果。

该 helper 面向单一 Wi-Fi 恢复；已有 EXIT、INT 或 TERM trap 不可静默覆盖。需要多项清理时，显式将原 cleanup 与状态恢复组合到一个 EXIT 处理器，保存原退出码，逐项尝试必要恢复，最后汇总失败。读取原值失败时不要进入状态变更阶段。

trap 负责退出恢复，不隐藏正常路径的状态设置。修改设备状态先有授权；开关 `CONFIRM=yes` 只能证明脚本门槛满足，不能代替用户对购买、权益、额度或数据操作的授权。

## shell 与参数边界

- 兼容 macOS bash 3.2 时不用 `mapfile` 等较新功能；数组可用 `while IFS= read -r` 收集。
- 路径和参数始终引用，必传 `-e` 在编排层列全，不把未定义值交给坐标计算。
- 中文紧跟变量时使用 `${VAR}`，避免裸变量名的多字节解析问题。
- `set -euo pipefail` 不是完整错误处理：条件调用、子 shell 和管道有例外。需要保留退出码时显式接住并区分失败，不用 `|| true` 抹去错误。
- 页面分支、状态探测和恢复错误要保留可定位的诊断；阶段结果分别记录，不以最后一步成功覆盖之前失败。

## 长跑与产物

同一设备串行；每场景独立保存日志、参数和 Maestro 产物，避免后场景覆盖前场景。失败先核对前置、参数和恢复结果，再判断产品缺陷。

运行中不要编辑脚本或它正在读取的输入表。shell 可能增量读取脚本，编辑会导致后续执行偏移；数据表重开也不保证本轮输入一致。先停止或完成当前运行，再固定新版本重跑；将“跑什么”与“怎么跑”分开有助维护，但不是热修改安全保证。
