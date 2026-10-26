# personal-skills

个人维护的 Agent Skills 与 Claude Code 插件源码集合，覆盖 Android 开发、视频特效、Bug 处理、封面模板、工作报告和任务快捷入口。

本仓库保存源码与测试，不保存个人报告、凭据或业务运行数据。部分能力依赖个人工具和项目配置，不是安装后即可用于任意项目的通用工具包。

## 插件

| 插件 | 当前版本 | 职责 |
|---|---|---|
| [forge-android](plugins/forge-android/skills/develop/SKILL.md) | 0.4.0 | Android 开发、重构、迁移、大屏适配、日志、UI、埋点、回归与发版检查 |
| [forge-effects](plugins/forge-effects/skills/develop/SKILL.md) | 0.1.0 | 特效接入、帧参数、GLSL Shader 编写与渲染审查 |
| [forge-bugs](plugins/forge-bugs/skills/clarify/SKILL.md) | 0.1.0 | Bug 描述整理与 MantisBT 工单操作 |
| [forge-templates](plugins/forge-templates/skills/cover/SKILL.md) | 0.1.0 | 封面模板生成、App 导出合并、素材检查及打包 |
| [task-shortcuts](plugins/task-shortcuts/README.md) | 0.1.9 | 会话级 `/next`、`/changes`、`/commit` 快捷入口 |

### Android

以下入口均可按专项调用，无需每次先加载完整开发流程：

| 入口 | 用途 |
|---|---|
| `forge-android:develop` | 日常开发、构建排查和按风险选择验证 |
| `forge-android:refactor` | 职责拆分、公共代码及资源体系治理 |
| `forge-android:migrate-kotlin` | 通过 Android Studio 官方 J2K 将 Java 迁为 Kotlin |
| `forge-android:adapt-large-screen` | 大屏、窗口与布局适配 |
| `forge-android:logging` | 诊断日志、临时块清理与 logcat 采集 |
| `forge-android:maestro` | Maestro 设备回归与冒烟脚本 |
| `forge-android:check-release` | 发版检查、证据汇总及缺口报告 |
| `forge-android:analyze-apk-size` | 两个 APK 的体积对账与增量归因 |
| `forge-android:implement-ui` | 根据设计稿实现及校对 Android UI |
| `forge-android:analytics` | 业务埋点实现与核验 |

模块、变体、包名、设备及发布约束以目标项目实际规则为准，不套用其他项目配置。

### 特效、Bug 与封面

| 入口 | 用途 |
|---|---|
| `forge-effects:develop` | 按任务整理帧参数，或接入滤镜与素材 |
| `forge-effects:shader` | 依据宿主版本、纹理与接口编写 GLSL |
| `forge-effects:review` | 只读审查渲染正确性、线程、生命周期与性能 |
| `forge-bugs:clarify` | 整理 Bug，默认提供“直接处理 / 补充内容”并等待选择 |
| `forge-bugs:mantis` | 通过 REST API 查询、评论及更新 MantisBT 工单 |
| `forge-templates:cover` | 分阶段生成、合并、检查和打包封面模板 |

Bug 描述整理不自动查询或写入 Mantis。Mantis 使用个人 API Token；查询、注释和状态更新分别遵循用户授权。
封面本地校验不代表客户端兼容或视觉验收，制作不自动授权设备写入、上传或总配置更新。

## 独立技能

这些技能尚未封装为插件，不能通过 `/plugin install` 单独安装。

| 技能 | 用途 |
|---|---|
| [structured-expression](skills/structured-expression/SKILL.md) | 组织分析、总结、介绍和解释，保留事实与验证边界 |
| [work-report](skills/work-report/SKILL.md) | 起草与改写日报、月报和绩效材料 |
| [google-doc-export](skills/google-doc-export/SKILL.md) | 获取 Google Docs 需求，整理进度及按授权同步 Sheets |
| [netease-playlist-classify](skills/netease-playlist-classify/SKILL.md) | 按场景、情绪和曲风分类歌单，并按授权创建及填充目标歌单 |
| [next](skills/next/SKILL.md) | 旧独立续做入口源码 |
| [changes](skills/changes/SKILL.md) | 旧独立改动查看入口源码 |

`next`、`changes` 作为保留源码收录；当前入口优先使用 `task-shortcuts`，不要同时安装同名旧技能。
`prose-writing` 目前未迁入。其原目录带 MIT 许可声明，后续收录应保留版权和许可，不将声明本身当作禁止入库的理由。

## 安装插件

市场名为 `personal-skills`。从已有本地检出目录加载：

```text
/plugin marketplace add /你的路径/personal-skills
/plugin install forge-android@personal-skills
/plugin install forge-effects@personal-skills
/plugin install forge-bugs@personal-skills
/plugin install forge-templates@personal-skills
/plugin install task-shortcuts@personal-skills
```

GitHub 远端内容同步完成后，也可通过 SSH 添加市场：

```text
/plugin marketplace add git@github.com:raoxiaoman/personal-skills.git
```

上述命令是使用说明，不表示本轮已经安装或远端已经具备本地全部内容。需要已配置的 GitHub SSH 访问权限。
已通过其他市场安装同名插件时，应先明确来源切换方案，避免重复加载；本次源码迁入没有改变现有安装入口。

更新已安装的市场与插件：

```text
/plugin marketplace update personal-skills
```

随后按当前 Claude Code 版本的插件管理入口更新所需插件。源码更新时同步提升对应 `plugins/<名称>/.claude-plugin/plugin.json` 的版本，不把市场更新等同于所有安装缓存已更新。

## 环境与权限

- Python 脚本按各技能声明选择解释器；多数仅用标准库，不默认向公共 Python 环境安装依赖。
- Mantis 需要 Bash、curl、jq 和个人 Token；凭据不放入仓库。
- SVG 栅格化需要已有 `rsvg-convert`；Figma 阶段需要对应工具及会话能力。
- Java → Kotlin 迁移依赖可用的官方 J2K 接口；没有接口时不以手写转换冒充官方转换。
- Maestro、ADB、编译工具、项目 SDK 与签名按实际项目配置，不自动补齐敏感资源。
- `task-shortcuts` 依赖 Claude Code 对原生插件能力的支持，以及本机 `safe-git-submit`、Zed 等相应工具；详见插件 README。

技能文档不扩大授权：提交、推送、删除、覆盖数据、设备操作与外部写入仍遵守各自权限边界。

## 验证

在仓库根目录按改动范围选择检查。以下为可执行示例，不代表迁入后已全部重跑：

```bash
# 市场清单
claude plugin validate .claude-plugin/marketplace.json

# APK 分析的合成测试
python3 -I -B plugins/forge-android/skills/analyze-apk-size/tests/test_apk_size_analysis.py

# Mantis 隔离测试：临时 HOME、假 Token、替代 curl，不访问真实工单
python3 -I -B -m unittest discover -s plugins/forge-bugs/skills/mantis/tests -p 'test_*.py'

# 特效数学样例与插件契约
python3 -I -B -m unittest discover -s plugins/forge-effects/tests -p 'test_*.py'

# 封面模板本地回归
python3 -I -B -m unittest discover -s plugins/forge-templates/skills/cover/tests -p 'test_*.py'
```

本地测试不等于真实服务、GPU、设备、视觉或发布验收。部分测试需要 Node.js 或 `rsvg-convert`，缺少工具时应如实报告跳过项。

## 目录与维护

```text
personal-skills/
├── .claude-plugin/marketplace.json
├── plugins/
│   ├── forge-android/
│   ├── forge-effects/
│   ├── forge-bugs/
│   ├── forge-templates/
│   └── task-shortcuts/
├── skills/                    # 独立技能
├── migration-manifest.json    # 首次复制来源及排除清单
├── .gitignore
└── README.md
```

当前为源码副本，尚未接管原有本机源码和运行入口。部分文档仍使用本机绝对路径，迁换环境前需要核对；不应同时修改两份源码却不记录同步关系。

团队共享版本位于 `skill/dev-skill`。个人版与团队版可能有调用名、脚本路径和缓存配置差异，按明确范围同步，不直接整目录覆盖。

## 数据与许可

- 不入库 Token、Cookie、私钥、个人报告、绩效材料、真实工单导出、安装缓存、日志及临时产物。
- 本次迁入已排除 `work-report/reports/` 和网易云 `latest-*` 运行数据，详情见 `migration-manifest.json`。
- `work-report` 的数据仍在原位置，未完成数据外置前，不将其运行入口切到仓库内并自动归档。
- `.gitignore` 只是基础防护，提交前仍需逐项核对文件与内容。
- 不批量收录下载的第三方技能，也不重复收录已由 forge 插件替代的旧版本。
- 保留各文件和组件已有版权及许可声明；仓库沿用远端已有的 [MIT 许可证](LICENSE)；组件已有的版权和许可声明仍须保留，不将仓库许可证视为第三方素材的授权。字体、图片、模板及第三方内容需单独确认使用范围。
