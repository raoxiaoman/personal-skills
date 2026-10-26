# 受管临时块与清理

## 创建契约

在完整独立语句边界使用同文件、同任务配对的独立行：

```kotlin
// TEMP-LOG-BEGIN BUG-12345
private const val LOG_TASK = "BUG-12345"
// TEMP-LOG-END BUG-12345

fun enqueue() {
    // TEMP-LOG-BEGIN BUG-12345
    logger.debug("[TEMP:$LOG_TASK] [export.enqueue] entered")
    // TEMP-LOG-END BUG-12345
    enqueueWork()
}
```

示例 logger 需换为项目真实 API。BEGIN/END 块不得嵌套、放在字符串/多行注释中，或包含业务动作、控制流与长期日志；日志参数也不得改变业务状态。任务专用 import、常量同样独立标记，不能被块外业务或其他任务使用。

标记是作者保证的删除契约，不是语法/语义解析器。添加时必须检查；后续不得混入业务代码。删除无花括号分支里的唯一日志会改变后续语句归属，因此不能这样创建块。

## 命令

先把 `<logging-root>` 替换成当前已加载技能目录的绝对路径，不硬编码开发者机器或插件缓存版本。从目标 worktree 执行，或明确给 `--root`：

```bash
python3 "<logging-root>/scripts/temp_logs.py" list --root "/absolute/source/root"
python3 "<logging-root>/scripts/temp_logs.py" clean BUG-12345 --root "/absolute/source/root"
python3 "<logging-root>/scripts/temp_logs.py" clean BUG-12345 --root "/absolute/source/root" --apply
python3 "<logging-root>/scripts/temp_logs.py" verify BUG-12345 --root "/absolute/source/root"
```

`clean` 默认预览；核对实际目标根、任务和 diff 后，在清理授权范围内使用 `--apply`。提供给用户独立运行的命令须展开为真实绝对路径，不留占位符。未指定 root 时取执行命令所在 Git worktree 根，而非会话初始目录。

## 能力与限制

- 扫描未跟踪源码，但不跟随符号链接，跳过 `.git`、构建和依赖目录；打印实际范围与跳过项。
- 清理前预检所有候选；标记错配/嵌套/未闭合、编码/读取错误或块外任务引用时拒绝写入。只有 tag 没有标记的旧日志不自动删除。
- 精确匹配任务，`BUG-1` 不匹配 `BUG-10`。保留块外字节、CRLF/LF 与权限，不格式化文件。
- 逐文件并发检查与原子替换，不是跨文件事务；失败报告已应用文件，不自动覆盖别人改动来回滚。
- `verify` 返回 0 表示所报告扫描范围无残留，1 表示受管残留，2 表示错误或未受管引用。源码扫描不等于编译验证，不覆盖资源、其他语言或运行设备。
