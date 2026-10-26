---
name: check-release
description: 跨项目 Android 发版前检查、发布准备与灰度后收尾。用户要求检查待发版本、上一发布 tag 到候选的差异、发版清单、草稿兼容、购买实验 label、正式配置、Baseline Profile 或发版时新旧 APK 大小变化时使用。统一输出15项证据与缺口，不把静态检查当全量放行；不是普通编译修复、单个埋点实现或实际商店发布工具。
compatibility: Python 3.10+ 标准库、Git；可选离线 Gradle、已绑定 root AVD、同包 analyze-apk-size 入口。
---

# Android 发版检查

## 默认体验：交互检查，报告后再修复

用户发起“要发版，开始检查”时，执行 [交互式编排](references/interactive-run.md)，不要只返回CLI命令或一份纯静态报告就结束。Agent负责连续完成已授权的脚本检查和代码核对；只有范围、权限、业务决策或人工操作确实需要用户输入时才使用结构化选项。已回答的不重复问，阶段失败不阻塞独立检查。

本轮范围、权限、选择、阶段证据和稳定问题编号按 [本轮记录格式](references/session-format.md) 保存到仓库及Skill之外的专属目录，最终交付一份统一report.md。历史暂缓不等于本轮确认。检查阶段只记录、定位和建议，不修业务代码；用户看完报告指定R编号后才进入修复与复查。

以下是执行边界及脚本入口；交互编排不扩展这些权限。

## 先固定范围

1. 读取目标仓库规则；确认项目、渠道、上一**真实发布 tag**、候选 commit 或当前工作区。不从目录名或最近 tag 猜发布身份。只有用户明确认可才把列出的 tag 当基线；无确认只作候选静态演示。
2. 看 [项目能力与接入](references/projects.md)，使用 `projects/<id>/project.json`；CLI 要求显式 `--project`，交叉验证 settings 模块和 applicationId，不回退其他项目配置。unsupported/pending 一律未执行。
3. 使用本技能的脚本，工具不复制进业务仓库。所有报告保存在仓库和整个插件以外的全新目录；当前仅显式适配 VideoGuru 和 YouCut，不因填入配置就承诺支持任意项目。示例中的 `<技能目录>` 是本 SKILL.md 所属目录，`<项目id>` 来自适配清单。

```bash
python3 -I "<技能目录>/scripts/release-check.py" \
  --repo "<仓库>" --project <项目id> --base <上一发布tag> \
  --worktree --output-dir "<全新外部目录>"
```

默认纯静态，不联网、不执行 Gradle、不访问设备。省略 `--worktree` 是提交端点快照，默认目标 HEAD；不混入未提交源码。base=HEAD 时两套端点仍独立。外置契约始终是当前工具数据，不伪称历史提交自带契约。

## 15项顺序，不省略未实现项

| 项 | 事项 | 证据边界 |
|---|---|---|
| 1 | 频道 AAR、mapping、版本信息 | 开始灰度后提醒，人工发送 |
| 2 | 发布 tag 存档与下一开发版本 | 确认实际包对应提交；单独授权 Git，下一版本与 SNAPSHOT 手改 |
| 3 | 新增埋点、本地日志 | 先看版本需求截图/识别文档，复用适配的埋点技能，不靠新增调用反推漏埋 |
| 4 | 鉴权挂接 | 静态 apply、任务定义、preBuild；不触发上传 |
| 5 | 草稿属性兼容 | 跨模块字段候选、Gson/迁移登记及生产契约测试；不自动判断业务默认值 |
| 6 | VersionName、VersionCode | 与显式发布基线对比；手工修改 |
| 7 | 测试服务器 | DI静态参数与调试门控，不代表运行时开关/远端状态 |
| 8 | AI访问标识 | 人工核对 accessFlags、实际最终依赖 taskName 映射、businessCode 及请求链；缺映射不能放行 |
| 9 | 新增 getOrThrow | 正式源码增量；注释排除、移动与继承歧义待确认 |
| 10 | 购买实验 label | 契约常量、碰撞、空参数与调用候选；默认参数不等于漏传，不发起支付 |
| 11 | Baseline Profile | 静态盘点；显式生成仅候选，不写源码，完整冷启动性能另验 |
| 12 | YUV SNAPSHOT | 正式变体最终选中依赖；外部报告来源待确认 |
| 13 | RemoteConfig差异与影响提醒 | Firebase以提醒为主：列样本差异、消费位置和行为影响；地域/条件/实验不同不判错或阻断，不要求值一致 |
| 14 | 包内JSON | 显式只读GET，双正式来源、正文与版本索引、同版本漂移；先差异后确认更新 |
| 15 | 新旧APK大小 | 调用现有APK技能，缺产物未执行，不自动构建下载 |

## 权限和阶段

- 普通“检查”只授权静态。`--resolve-dependencies` 授权离线Gradle依赖解析；`--run-draft-tests` / `--run-purchase-tests` 授权已登记契约单测。三者要求 `--worktree --output-dir`，不等于安装/上传许可。Gradle配置和buildSrc会执行、缓存会写，offline不等于系统只读。
- `--check-configs` 明确授权正式HTTPS只读GET；要求新输出目录。拒绝未登记对象路径/重定向，gzip按解压后16MiB限制。403、镜像差异、本地维护或暂缓例外保留待确认，不提权、不更新文件/云端。Firebase模板未自动接入，不能混为包内JSON。
- `baseline-profile.py check` 默认纯静态；`--inspect-device` 才只读查询绑定AVD。`dry-run` 会执行Gradle配置/任务图；`generate` 额外授权该指定AVD的启动、root、目标测试APK安装及生成器，不等于任意设备安装。先确认用户明确允许，不以普通检查推导生成授权。详见 [候选Profile](references/baseline-profile.md)。
- APK需同时提供 `--analyze-apk --old-apk <旧包> --new-apk <新包>`。先核实上次发布与本次候选身份及渠道、ABI、split/universal、debug/release。调用同一技能源的 相邻 `../analyze-apk-size/scripts/apk_size_analysis.py`，不复制实现。未提供mapping匹配证据就不用mapping归因。完整测量不等于增长合理，无用户预算不擅设阻断阈值。详见 [命令和结果](references/release-check.md)。

## 设备页面操作使用 Maestro

已获授权的设备验证中，Maestro能完成的页面操作统一使用Maestro：进入页面、点击、滑动、输入、返回、等待、断言和截图。先复用项目现有flow与编排；缺少场景时补最小flow，不改用手工ADB坐标操作。ADB仅用于安装/进程管理、设备与日志/文件查询等非页面操作；Maestro确实无法完成时记录具体限制，再在原授权内降级或请求必要人工操作。详见[交互编排](references/interactive-run.md)的设备操作约定。

## 输出与后续

所有15项保留通过、异常、待确认、未执行、不涉及及supported/manual/pending能力。报告区分脚本结果、人工待核对、用户暂缓、未执行；脚本不替用户暂缓任何项目，用户明确暂缓时另记原因且不转成通过。生产契约测试仍留业务仓库；脚本测试仅在本技能。零用例、任何跳过、缺类、超时或来源不明不能通过。源码/HEAD或当前工具契约变化使本轮过期。

用户明确说开始灰度后才提醒 AAR/mapping/频道发送、发布tag及下一开发版本；不自行监控商店、不冒充已发送/发布。用户要求提交时独立运行 `~/.claude/bin/safe-git-submit` 只读检查，先列staged清单，遵守现场分支、提交信息与人工确认规则；不自动提交、push、合并或清理。个人技能安装不进入项目Git收尾。

## 本地自检

```bash
python3 -I -B -m unittest discover -s "<技能目录>/tests" -v
python3 -I -B "<技能目录>/../analyze-apk-size/tests/test_apk_size_analysis.py"
```

测试用临时fixture和mock，不启动真实Gradle、设备、云端、支付。七个行为场景在 [evals](evals/evals.json)，未运行agent触发率/性能评估不能声称通过。

验证层级及仍未覆盖的边界见 [验证状态](references/verification-status.md)。不要把离线自检通过扩展为真实设备、云端或完整发版通过。
