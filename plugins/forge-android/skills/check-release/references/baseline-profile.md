# Baseline Profile候选

入口相对技能根为`scripts/baseline-profile.py`。默认check纯静态，不找SDK、不访问ADB。

```bash
python3 -I "<技能目录>/scripts/baseline-profile.py" check --repo "<仓库>" --project <项目id>
# 以下需要单独明确授权
python3 -I "<技能目录>/scripts/baseline-profile.py" check --repo "<仓库>" --project <项目id> --inspect-device --avd <已有AVD> --serial emulator-5554
python3 -I "<技能目录>/scripts/baseline-profile.py" dry-run --repo "<仓库>" --project <项目id> --output "<新外部目录>"
python3 -I "<技能目录>/scripts/baseline-profile.py" generate --repo "<仓库>" --project <项目id> --avd <已有AVD> --serial emulator-5554 --output "<新外部目录>" --timeout 900
```

可选`--machine-config <文件>`为schema_version=1、avd、sdk_root数据；不登记serial。serial取当前ANDROID_SERIAL或显式参数，冲突即停。AVD不是跨项目默认授权，不创建下载、不自动选设备。只允许API28+ emulator偶数console端口5554..5682，核实AVD身份、端口占用、开机、包管理器及adb root重连。生成可能启动已登记AVD、安装生成器/目标APK；不是普通“检查”许可。

先运行固定白名单任务图，拒绝上传/发布、copy Profile入源码、托管设备；通过本轮init脚本把已登记项目的连接设备任务启用、managed列表清空并保留插件要求的saveInSrc=true、关闭automaticGenerationDuringBuild，仅调用并重定向merge候选；源码写回通过不调用copy任务及任务图拒绝copy保证。插件DSL变化、路径不符则失败，不改源码配置绕过。VideoGuru已在获授权演练中实际生成候选，证据边界见[验证状态](verification-status.md)；YouCut生成仍pending。新项目或DSL变化后仍须独立核对任务图，不继承历史设备授权。

产物必须是本轮新鲜且非空的baseline/startup文本与唯一生成器JUnit（1用例，无失败/跳过）。缓存/旧XML/旧Profile不能通过。本轮源码、HEAD、工具契约摘要及原Profile哈希必须保持一致；不自动恢复并发修改。结果保存在新目录manifest.json、任务图/Gradle日志、profiles/。check/dry-run退出2明确生成未完成，generate成功0只代表候选生成，不代表源码更新或性能改善。无apply、无自动copy、无全局构建目录清理。

统一发版报告不自动导入过去候选；第11项保留未执行并提供静态Profile盘点，人工关联本轮候选与冷启动真实验证。

机器配置必须为对象，字段avd/sdk_root须为非空字符串，重复键拒绝。显式指定sdk_root时只使用该SDK；不存在或缺工具即停止，不静默切换到其他安装。未指定时才按环境与本机默认路径发现。
