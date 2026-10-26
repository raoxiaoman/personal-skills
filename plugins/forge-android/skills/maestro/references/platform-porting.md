# 设备层契约与平台移植

设备原语与 flow 编排分开，避免厂商命令变化散落到场景中。当前模板仅覆盖 Android；分层降低移植成本，不保证更换实现后场景无需修改。

## Android 模板契约

| 函数 | 语义 |
|---|---|
| `resolve_serial [给定值]` | 使用当前 `ANDROID_SERIAL`，拒绝冲突参数；`get-state` 不可用则失败，不枚举自动选机 |
| `device_info <serial>` | 输出型号、SDK、语言、屏幕、密度与 Wi-Fi 等契约快照，供人工核对 |
| `device_wifi_state <serial>` | 输出 `0` 或 `1`；读取失败或未知值非零 |
| `device_wifi <serial> <on\|off>` | 只切 Wi-Fi 并回读；不控制蜂窝或保证完全断网 |
| `device_screen_size <serial>` | 输出 `"宽 高"`；识别正常 Physical/Override，接受方形；未知或歧义输出失败，不代表应用窗口 |
| `device_tap_pct <serial> <x%> <y%>` | 在已确认全屏与显示状态下按屏幕百分比点击，仅用于有证据的降级 |
| `device_ui_dump <serial>` | 输出本次成功采集的层级；失败非零，不读取旧 dump |
| `app_restart_home <serial>` | 已获启动授权后冷启动并等待项目定义的首页标识，不替代完整业务验收 |
| `device_repeat_tap <serial> <x> <y> <次数>` | 单条设备命令循环；用于经确认的高频场景，不承诺精确点击间隔 |

`lib-device.sh` 另提供 `maestro_phase` 和 `restore_wifi_on_exit`。后者在切换前捕获 Wi-Fi 原值，退出时恢复并回读；恢复失败返回非零。已有 EXIT trap 不得覆盖，应将原有清理与恢复显式收进同一个 cleanup。

除解析绑定的 `resolve_serial` 外，设备原语以 serial 为首参；调用方使用解析后的同一绑定。stdout 仅放可解析结果，诊断到 stderr，失败非零。状态变更需要用户授权，先记录原值再执行与回读，不用 `|| true` 伪装成功。具体实现只维护在模板，不在文档复制另一套逻辑。

## 其他平台

若另行支持 iOS、云真机或其他设备实现，先确认支持范围，再补设备层和对应测试。必须重新核对：

- 应用标识、设备绑定和命令权限。
- 无障碍层级、选择器、弹窗与 Toast 的实际暴露方式。
- 网络开关与原值恢复能力。
- 冷启动、首页就绪和后台行为。
- 坐标系统、显示/窗口与高频操作时序。
- 所用 Maestro 版本的参数、嵌套 flow、等待和循环行为。

Android 上的历史观察不能直接证明 iOS 成立；无法提供等价原语或证据时保留能力缺口，不宣称移植完成。
