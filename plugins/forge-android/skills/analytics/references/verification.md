# 验证与采集

## 先确定场景预期

以需求表为依据，列每个场景预期的 event name、content_type、item_id、次数和顺序。点击、实际处理、重试、保存、取消和历史恢复只覆盖相关项，不以一个场景通过推导全部链路通过。

应用侧事件验证是默认验收层级；若需求明确包含 SDK 或服务端，则补对应证据。业务唯一次数须按生命周期核对，不能把两种日志来源合并后当一次，也不能沿用查看器的时间去重规则。

## 复用公共采集 CLI

使用 [同包发版检查提供的 CLI](../../check-release/scripts/release_tracking_check.py)，它只输出选定 content_type 的允许字段，不维护第二份解析器。当前格式支持 VideoGuru 的既有应用日志和 Firebase 日志，不承诺自动适配所有项目；其他项目先核对样本格式。

离线日志解析不访问设备：

```bash
python3 -I -B "<技能目录>/../check-release/scripts/release_tracking_check.py" \
  --input "<可信本地日志>" --content denoise \
  --output "<本轮外部证据目录>/events.json"
```

已获采集授权、目标应用已在运行时：

```bash
python3 -I -B "<技能目录>/../check-release/scripts/release_tracking_check.py" \
  --capture --serial "$ANDROID_SERIAL" --package "<已核对的包名>" \
  --seconds 60 --content denoise --content denoise_menu \
  --output "<本轮外部证据目录>/events.json"
```

输出父目录须已存在，文件须全新且位于插件之外。采集仅使用当前绑定并检查可用性，不安装/启动应用、不清日志、不修改 Debug 属性。限时采集可后台运行，再串行执行已授权 Maestro 场景；同设备不并行跑多个业务 flow。

content_type 只选择已批准的固定业务枚举，不能包含用户输入或动态个人标识；字符过滤不是完整隐私检测。原始日志若含敏感内容，不向外部服务上传。

## 结果边界

- 输出分别保留应用/旧应用/SDK来源、每条事件、次数和出现顺序，不跨来源去重。
- 退出 0 仅说明取得允许事件，不自动断言参数、次数、顺序或业务正确。
- 退出 2 可表示零事件、采集错误或进程变化；读取具体错误与报告，不统一认定产品漏埋。
- PID 只约束目标主进程，不涵盖独立 FA-SVC。应用重启或 PID 变化会使本轮采集不完整，需新产物。
- 应用侧日志可能早于过滤器；SDK 侧日志缺失不是服务端失败证据。明确需求范围，不擅自开启调试属性、重复重启或扩大排障。
