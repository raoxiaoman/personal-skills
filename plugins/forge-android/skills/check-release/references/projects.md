# 项目能力与接入

## 已核对的适配

| 能力 | videoguru | youcut |
|---|---|---|
| 主模块/渠道 | Guru / googlePlayRelease | YouCut / googlePlayRelease |
| 身份 | settings模块 + 正式applicationId | settings模块 + 正式applicationId |
| 根版本与鉴权挂接 | supported | supported |
| 正式源码getOrThrow候选 | supported | supported |
| 正式YUV依赖解析/导入 | supported；执行须授权 | supported；执行须授权 |
| DI门控规则 | supported静态规则 | supported；按hookBuildUrl自身花括号边界检查 |
| 草稿字段/Gson/生产测试登记 | supported，登记降噪字段 | supported字段候选与Gson依据；无已登记生产契约测试 |
| 购买label与生产测试登记 | supported，retainA/B、UserA/B、pro2button/pro3button | supported，独立UserA/B契约；无已登记标签透传测试 |
| 包内JSON及远端索引 | supported，8 raw+4 assets+2索引 | supported，15 raw+3 assets+2索引；GET另行授权 |
| Baseline静态盘点/候选生成 | supported；候选不代表性能通过 | supported静态盘点；生成pending，当前为managedDevices模式 |
| APK委托 | supported，同源APK技能 | supported，同源APK技能 |
| 埋点需求/AI标识/RemoteConfig模板 | manual | manual |
| 灰度频道、tag、下一版本 | manual | manual |

supported表示工具有相应入口，不代表本版本已验证或已执行。YouCut已只读核对构建指纹、DI门控、草稿模型/Gson入口、购买label链路、包内配置及其消费入口、Baseline模块和生成器配置。尚未运行YouCut构建、设备或云端，也未修改其业务仓库。VideoGuru生产契约测试继续保存在原仓库：RetentionLabelContractTest、DenoiseDraftRoundTripTest等；项目登记只保存选择器与预期。

VideoGuru包内JSON映射从既有 `script/线上配置同步/sync_bundled_configs.py` 的字面数据抽取，运行时不再导入或执行该文件。该同步/上传工具保留，职责不属于本次迁移。原会话工具来源哈希在 [迁移清单](migration-manifest.json)。

## YouCut 适配边界

2026-10-16用户确认YouCut新版本尚未开发；当前仅完成工具适配准备，不存在本轮待发候选。此前tag只用于静态演示，不保存为未来默认发布基线。待用户发起实际发版检查时，重新确认版本需求、上一真实发布tag、候选范围与各阶段权限；不沿用Maker或演示的授权、设备样本和结果。不为完成适配而要求现在补业务测试、生成Profile或操作设备。

- 项目id为`youcut`。使用相同的交互编排、15项报告与问题编号，但不继承VideoGuru的更新菜单、滤镜、update2或历史暂缓决定；需要业务裁决时仍用选项确认。
- DI的版本识别依据位于`YouCut/src/main/java/com/camerasideas/utils/Utils.java`，不是`AppUtil.kt`。`hookBuildUrl`没有`hookBodyParams`后继，按自身方法体检查双调试门控；云资源配置另有JSON调试开关，静态结果不证明设备开关关闭。
- `VideoEngine`的`MediaClipInfo`没有继承`ClipInfo`，`PipClipInfo`继承`BorderItem`，因此显式登记两模型，不能只套Maker的继承根。Gson依据是`YouCut/.../workspace/config/MediaClipConfig.java`、`PipClipConfig.java`、`BaseProfileConfig.java`。无生产round-trip/旧草稿契约测试，登记`tests: []`；候选扫描不等于草稿兼容通过，变化涉及的嵌套字段、默认值和迁移仍需代码核对与设备样本。
- 购买`UserA/UserB`常量属于YouCut自己的`SubscribeProPolicy.kt`，实际分组经`ProPageAbTestLabel.kt`缓存；ViewModel显式传递benefitDetailLabel，旧Presenter的`getLabel()`固定返回UserA，UserManager无参默认也是UserA。这些是不同入口的现状，不因名字相同就认定一致，也不自行改默认。核对真实Billing profile参数，不以Analytics日志替代。现有`SubscribeProPolicyDecisionTest`只覆盖试用UI决策等，不登记为label契约测试；没有测试时不运行空选择器来伪造通过。
- 配置依据：`ConfigVersionFragment.kt`、`AppUrl.java`、包内两个索引及AiArt/AiTools/TTS Repository的实际resId。15份raw、3份assets分别按本项目索引键登记；模板匹配/Discover/解锁/热门/关键词/推荐词、社媒解锁和update使用项目级`root_version_keys`读取根version，不改变其他项目的解析口径。只维护索引中且有本地正文/消费依据的现役对象，不把索引中所有历史key猜成下载目标。GET权限与差异裁决沿用主Skill。
- Baseline可盘点源码Profile，但`managedDevices += "pixel6Api34"`、`useConnectedDevices = false`不兼容当前绑定AVD生成入口；`generation: pending`继续拒绝generate，不偷偷修改业务Gradle或启动托管设备。适配生成需独立核对任务图与设备授权。
- Firebase沿用主Skill的差异与影响提醒口径；埋点须使用YouCut版本需求和事件定义，不能复用Maker降噪场景。获授权设备操作仍优先项目已有Maestro flow；没有flow不代表该场景已验证。

## 新项目接入

以 [数据模板](../projects/template.json) 的结构建立独立 `projects/<新id>/project.json` 及空契约登记。模板为不可执行的示意，必须填入真实构建指纹；没有适配前能力全pending。不要替换整份Guru配置的字符串来串项目。

1. 只读核对settings、主模块、applicationId、渠道/源码集、版本/鉴权/DI入口、危险任务与Baseline实际配置。优先记录事实，不为未知项编造域名或task。
2. 按数据schema_version=1填入构建指纹。路径必须相对所属根，禁止绝对路径、`..`、符号链接逃逸，远端只允许正式HTTPS的已登记对象。测试只能登记完整类名，项目配置不含shell/eval或可执行回调。
3. 独立逐项登记模型/Gson/迁移依据、购买label/常量/policy/入口/测试、资源索引。先写fixture再改能力为supported；不复制其他项目的业务预期。生产测试放目标仓库而不是技能。
4. CLI当前固定支持googlePlayRelease与googlePlayDebug契约测试，其余渠道先扩充白名单、验证并说明范围，不能仅改JSON伪装支持。
5. 跑双项目隔离、路径、缺数据失败关闭测试及真实纯静态smoke。构建/设备/云端均单独授权再验证；外置配置不属于历史提交。

AVD/SDK是可选机器数据，示例见 [machine模板](../projects/machine.example.json)。不保存serial，也不保存历史设备授权。

## 保留的既有用户决定

VideoGuru 已将项目归档中的决定结构化登记在configs.exceptions：更新菜单、首页工具、update/update2、自有RemoteConfig暂缓；滤镜仅本地维护。显式配置GET阶段仍检查本地结构与索引，但不再向这些被暂缓对象发GET，不把例外当通过，恢复比较需另行确认并更新该登记。deferred_checks第13项仍保存2026-10-13暂缓模板比较的历史来源；后续用户已明确Firebase以差异与影响提醒为主，交互汇总按主Skill现役口径解释，不再把旧暂缓当作每版确认或模板必交要求。历史登记不是本轮授权，也不是当前远端验证结果。

## 更新菜单的长期提醒口径

2026-10-15用户明确：历史更新菜单在本轮及后续版本只输出维护提醒，不作为发版问题或阻断项，不每版重复确认。脚本原始结果可能仍显示索引缺项或待确认，交互汇总须解释为维护提醒，不生成问题编号，也不改称技术通过。保留原始证据，不补索引、不启用旧正文、不删除文件。将来用户明确要求恢复该功能时，再核对下载URL、索引、旧缓存与展示规则。消费端仍有引用，不能宣称功能已退役。

## VideoGuru 应用更新配置的提醒口径

2026-10-16用户确认：`update/update2`暂按维护提醒处理，不因文件名不同或`update_config_android2.json`远端404生成发版问题，不反复要求迁移下载地址。不是更新菜单，也不表示已验证线上正文一致。

- 正式远端正文：`update_config_android.json`；设备缓存及包内正文：`update_config_android2.json`；更新门控索引：`update2`。三者不要求同名。
- 实现依据：目标仓库`Guru/src/main/java/com/camerasideas/instashot/AppUrl.java`的`getUpdateConfigUrl()`注释，以及`store/client/OnlineStoreClient.java`的缓存名、`getBuiltInVersion()`与线上`update2`解析；后续核对先看当前代码，不凭工具登记的新文件名推断真实下载地址。
- 提醒发布配置时先更新实际远端正文及镜像，再提升线上`update2`，保持正文version与索引一致；旧客户端共用远端地址，需考虑字段和升级策略兼容。下载保存的JSON合法性校验不等于版本一致性验证。
- 不自动更名、切换URL、补索引、用旧正文覆盖新版或上传。若以后实际验证发现版本不一致、解析错误或升级策略缺陷，单独报告确证问题；目前的命名映射本身不是缺陷，也不把提醒标成技术通过。
