# 后台采集与边界

## 调用

替换 `<logging-root>` 为已加载技能根目录，确认当前绑定和 applicationId 后启动：

```bash
python3 "<logging-root>/scripts/watch_android_logcat.py" \
  --task BUG-12345 --package com.example.app
```

脚本读取当前 `ANDROID_SERIAL`。只有没有环境绑定且用户已确认目标时，才用 `--serial` 显式指定；与当前绑定不同会拒绝。脚本先执行该序列号的 `get-state` 验证，不调用 `adb devices` 自动挑机。所有 adb 子命令固定 `-s`，不可用时失败，不重新枚举或切换。

使用宿主实际支持的持续后台工具，先核对工具 schema；记录 task id 与 READY 文件，再通知用户复现。没有持续通知能力时不要承诺主动自动分析。停止该任务后读取收尾文件，不能终止全局 adb。

`--output` 指定日志父目录，每次创建私有的独立会话子目录和 0600 文件；默认使用 `XDG_CACHE_HOME`（若为绝对路径）或 `~/.cache` 下的 `forge-android/logcat`。不会更改已有父目录权限，不复制旧采集日志进插件。`--max-bytes` 默认 50 MiB，达到上限明确失败停止。

## 筛选与证据

- 获取实际包 UID，验证设备支持 `logcat --uid`，记录设备当前时间并从该时间开始；不 `logcat -c`，不把历史缓冲当本次复现。
- UID 过滤覆盖同 UID 多进程和进程重启；本地只存精确 TEMP 标记和脚本支持的 AndroidRuntime/native 崩溃行。共享 UID 可能包含其他包崩溃，不能证明每条都是目标应用。
- 不捕获系统 UID 的全部 ANR/tombstone，也不保证隔离进程/native 栈完整。卸载重装导致 UID 改变后必须重新启动采集。不能为收更多证据偷偷退回全设备日志。
- 不支持 UID、权限/连接失败、启动失败、意外退出和容量上限均明确报告。READY 只是进程已启动，不证明业务路径已触发或能捕获所有故障。
- stdout 只批量通知，不逐行刷屏；完整筛选行保存在本地。读取实际文件确认错误；不把无日志当成功。
- 本地私有权限不是脱敏。目标 UID 崩溃堆栈和 TEMP 内容仍可能含敏感信息，禁止自动上传和未经核对分享。

采集前另核对 logger 在已安装构建中的输出开关；脚本不替代安装、启动、业务复现或功能验收。
