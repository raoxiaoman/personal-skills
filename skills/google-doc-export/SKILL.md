---
name: google-doc-export
description: 从 Google Docs 获取需求文档，并在项目内生成需求文档、需求进度评估文档，必要时同步覆盖更新 Google Sheets 云端排期表。仅当用户明确给出 Google Docs / Google Sheets 链接，明确说要从 Google Docs 导出，或明确说要同步、覆盖、回写云端 Google Sheets 排期表时触发。不要因为用户只提到普通“需求文档”“排期”“schedule”“同步一下”就触发；如果只是修改本地 markdown / 本地文档，默认不走本 skill。
metadata:
  type: instruction
---

# Google Doc 需求导出与排期同步 skill

## 适用场景

当用户有以下任一目标时触发：

1. 给出 Google Docs 链接，要求生成项目内需求文档。
2. 给出 Google Docs 链接，要求顺带生成本地排期 / 进度评估文档。
3. 要求把本地需求进度文档同步到 Google Sheets 云端排期表。
4. 要求用本地文档内容覆盖更新某个版本的 Google Sheets 排期 sheet。
5. 提到“Google Doc + 排期 + 云端表格”这类串联流程时。

不要只在“导出需求文档”时触发；只要用户要做这一整条链路中的任一环节，都应该先进入本 skill 再判断执行到哪一步。

## 能力边界

本 skill 负责一条固定流程的编排：

- 从 Google Docs 拉需求
- 生成项目内需求文档
- 生成本地需求进度评估文档
- 同步覆盖 Google Sheets 云端排期表
- 统一云端表格格式

本 skill 默认面向**固定模板**：

- 需求来源是 Google Docs
- 项目内版本文档位于 `docs/<版本号>/`
- 需求文档命名为 `docs/<版本号>/<功能名>.requirement.md`
- 排期文档命名为 `docs/<版本号>/schedule.md`
- 素材目录位于 `docs/<版本号>/assets/`
- 云端目标是固定列结构的 Google Sheets 排期表

如果用户要处理完全不同模板、完全不同列结构、或任意 Google Sheets，自行先说明风险，不要假设现有脚本可以直接通用。

## 执行模式

根据用户请求，选择以下 4 种模式之一。

### 模式 A：仅导出需求文档

触发示例：
- “这个 Google Doc 帮我生成项目内需求文档”
- “导出成 docs 里的需求文档”

输出：
- `docs/<版本号>/<功能名>.requirement.md`
- `docs/<版本号>/assets/`

### 模式 B：导出需求文档 + 生成本地排期

触发示例：
- “从这个 Google Doc 顺手生成排期”
- “帮我把需求和进度评估文档都产出来”

输出：
- `docs/<版本号>/<功能名>.requirement.md`
- `docs/<版本号>/schedule.md`
- `docs/<版本号>/assets/`

### 模式 C：导出需求文档 + 本地排期 + 云端同步

触发示例：
- “从 Google Doc 拉需求并同步到云端排期表”
- “这版需求从 Google 上拉下来，生成排期并更新到表格”

输出：
- 项目内需求文档
- 本地排期文档
- 云端 Google Sheets 已覆盖更新

### 模式 D：仅同步已有本地排期到云端

触发示例：
- “把 docs/V1.650 需求进度评估.md 同步到云端”
- “用本地排期覆盖 Google Sheets”

输出：
- 云端 Google Sheets 已覆盖更新

## 推荐实现原则

优先把稳定逻辑放进脚本，不要把复杂解析和页面操作都堆在 skill 文本里。

分层建议：

- **Skill**：判断模式、收集参数、选择脚本、汇报结果
- **脚本**：做确定性的提取、转换、同步、格式化
- **Playwright**：仅在需要打开 Google 页面、沿用用户登录态、或临时补救时使用

长期建议：

- Google Sheets 同步能力尽量迁移到 API 脚本
- Playwright 仅保留为兜底方案，不作为长期主写入手段

## 默认输入

执行前尽量补齐这些信息：

- Google Docs 链接（模式 A/B/C）
- Google Sheets 链接（模式 C/D）
- 版本号，如 `V1.650`
- 功能名，如 `AI Trim`
- 是否需要生成本地排期文档
- 是否需要同步云端

若版本号或功能名能从文档标题、现有 docs 文件名、sheet 名中稳定推断，可直接推断，不必反复确认。

## 绑定脚本

### 1. 需求导出脚本

已有脚本：

```bash
python3 ~/.claude/skills/google-doc-export/scripts/gdoc_export.py \
  --txt ".playwright-mcp/<导出文件>.txt" \
  --docx ".playwright-mcp/<导出文件>.docx" \
  --out docs/<版本号>/assets
```

职责：
- 读取 txt 完整文本
- 从 docx 提取嵌入图片
- 输出段落与图片位置映射

### 2. 排期生成脚本（已落地骨架）

脚本名：`~/.claude/skills/google-doc-export/scripts/schedule_generate.py`

职责：
- 从固定格式的本地排期文档提取 `## 一、总览` 表格
- 生成结构化 JSON，供后续同步云端使用
- 可同步生成一个 markdown 镜像文件，便于人工检查

### 2.1 排期联动刷新脚本（最小可用）

脚本名：`~/.claude/skills/google-doc-export/scripts/schedule_refresh.py`

职责：
- 以 `docs/<版本号>/schedule.md` 的 `## 一、总览` 为唯一主数据源
- 按开始日期、跳过周末规则、开发负责人、开发预估周期，联动刷新 `开发排期`
- 基于总览表重建 `## 三、开发排期总览`
- 默认保持 Android Studio / JetBrains 偏好的整列对齐 Markdown 表格格式

当前建议边界：
- Markdown 本身不负责“改一处自动联动”，联动逻辑应下沉到脚本
- `## 一、总览` 允许手工维护
- `开发排期` 与 `## 三、开发排期总览` 默认视为可刷新派生内容，必要时由脚本覆盖更新

当前可用输入示例：

```bash
# 仅按总览表现有“开发排期”刷新第三节
python3 ~/.claude/skills/google-doc-export/scripts/schedule_refresh.py \
  --input "docs/<版本号>/schedule.md" \
  --write

# 重新按开始日期 / 跳过周末 / 开发预估周期重算“开发排期”，并刷新第三节
python3 ~/.claude/skills/google-doc-export/scripts/schedule_refresh.py \
  --input "docs/<版本号>/schedule.md" \
  --recalculate-overview-dates \
  --write
```

推荐使用约定：
- 日常维护时，优先手工更新 `## 一、总览`，然后执行不带 `--recalculate-overview-dates` 的刷新命令
- 只有当用户明确希望“按工期自动推导完成日”时，才使用 `--recalculate-overview-dates`
- 若当前文档中的 `开发排期` 与“开始日期 + 工期 + 跳过周末”口径不一致，不要静默重算，先说明差异再执行

当前约束：
- 现阶段优先支持从 `docs/<版本号>/schedule.md` 提取总览表
- 不尝试自动理解任意需求文档全文
- 这是刻意的最小实现，不做泛化解析

当前可用输入示例：

```bash
python3 ~/.claude/skills/google-doc-export/scripts/schedule_generate.py \
  --input-doc "docs/<版本号>/schedule.md" \
  --version "<版本号>" \
  --feature "<功能名>" \
  --output-md "/tmp/google-doc-export/<版本号>/schedule.generated.md" \
  --output-json "/tmp/google-doc-export/<版本号>/schedule.json"
```

当前 JSON 输出结构：

```json
{
  "version": "V1.650",
  "feature": "AI Trim",
  "sheet_name": "新版本V1.650 AI Trim",
  "start_cell": "A3",
  "rows": [
    {
      "version_label": "新版本",
      "priority": "P1",
      "task": "AI Trim — 功能展开页（入口判断、时长显示、会员/广告解锁逻辑）",
      "product_owner": "韩庆芝",
      "product_progress": "",
      "dev_owner": "饶辉",
      "dev_estimate": "1.5天",
      "qa_owner": "陈诗琪",
      "qa_progress": "",
      "release_time": "",
      "remark": "预计完成 5/28"
    }
  ]
}
```

### 3. 云端同步脚本（已落地载荷生成层）

脚本名：`~/.claude/skills/google-doc-export/scripts/sheet_sync.py`

职责分层：
- **当前已实现**：把结构化排期 JSON 转成 TSV 载荷、目标范围和 sync plan
- **当前未下沉到脚本**：真正的浏览器页面点击、粘贴、格式操作

这意味着：
- Python 脚本负责稳定的数据处理
- 实际页面写入由上层 skill 通过 Playwright MCP 执行
- 后续如果接 Google Sheets API，可继续复用同一份 sync plan

当前可用输入示例：

```bash
python3 ~/.claude/skills/google-doc-export/scripts/sheet_sync.py \
  --sheet-url "<Google Sheets 链接>" \
  --input-json "/tmp/google-doc-export/<版本号>/schedule.json" \
  --replace \
  --format center \
  --output-tsv "/tmp/google-doc-export/<版本号>/schedule.tsv" \
  --output-plan "/tmp/google-doc-export/<版本号>/sync_plan.json"
```

当前支持的关键参数：
- `--sheet-url`
- `--sheet-name`
- `--start-cell`
- `--input-json`
- `--replace`
- `--format {none,center,full}`
- `--output-tsv`
- `--output-plan`
- `--execution-mode {dry-run,handoff}`

当前 sync plan 输出示例：

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/.../edit?gid=1230050221",
  "sheet_name": "新版本V1.650 AI Trim",
  "start_cell": "A3",
  "target_range": "A3:K14",
  "replace": true,
  "format_level": "center",
  "row_count": 12,
  "preserve_footer_notes": true,
  "tsv": "..."
}
```

当前建议能力边界：
- 清空旧区域并整块覆盖 → 由上层 Playwright MCP 执行
- 自动按 rows 数量扩展范围 → 已在脚本内完成计算
- 统一水平/垂直居中 → 由上层 Playwright MCP 执行
- 自动换行、列宽 / 行高 → 暂由上层处理，后续可迁移到 API

## 各模式执行流程

## 模式 A：仅导出需求文档

1. 用户提供 Google Docs 链接。
2. 用 Playwright 打开链接，引导用户在浏览器会话中完成登录。
3. 通过导出地址获取 txt 与 docx：

```text
https://docs.google.com/document/d/{doc_id}/export?format=txt
https://docs.google.com/document/d/{doc_id}/export?format=docx
```

4. 运行 `~/.claude/skills/google-doc-export/scripts/gdoc_export.py` 提取文本与图片。
5. 对齐 `docs/<版本号>/` 下现有文档风格，生成功能级需求文档 `<功能名>.requirement.md`。
6. 清理 `.playwright-mcp/` 导出文件。
7. 汇报生成路径、图片数量、待补充项。

## 模式 B：导出需求文档 + 生成本地排期

在模式 A 的基础上继续：

1. 基于需求文档生成 `docs/<版本号>/schedule.md`。
2. 排期文档至少包含：
   - 总览
   - 详细拆解
   - 开发排期总览
   - 相关文档
3. 若项目已有同类模板，优先对齐已有风格。
4. 生成 `docs/<版本号>/schedule.md` 中的 Markdown 表格时，默认对齐 Android Studio / JetBrains Markdown 的格式偏好：
   - 使用完整对齐版表格，不要只写“最短合法”的紧凑分隔行。
   - 表头、分隔行、数据行都按同一列宽补齐，保持整列视觉对齐。
   - 单元格统一使用 `| 内容 |` 风格，列数必须严格一致，空单元格也保留占位。
   - 若某个单元格内容过长，优先缩短表格内表述，把补充说明挪到表格下方注释，不要把超长自然语言硬塞进表格单元格。
   - 目标不是只让 Markdown 语法合法，而是尽量避免 Android Studio 报 `Table is not correctly formatted`。
5. 若排期生成逻辑已经脚本化，优先调用 `~/.claude/skills/google-doc-export/scripts/schedule_generate.py`；未脚本化时可先手工生成，但要提醒后续沉淀脚本。

## 模式 C：导出需求文档 + 本地排期 + 云端同步

在模式 B 的基础上继续：

1. 确定目标 Google Sheets 链接与 sheet 名。
2. 优先调用 `~/.claude/skills/google-doc-export/scripts/schedule_generate.py` 生成结构化 JSON，默认输出到 `/tmp/google-doc-export/<版本号>/schedule.json`。
3. 调用 `~/.claude/skills/google-doc-export/scripts/sheet_sync.py` 生成：
   - `/tmp/google-doc-export/<版本号>/schedule.tsv` 同步载荷
   - `/tmp/google-doc-export/<版本号>/sync_plan.json`
4. 读取 sync plan 后，用 Playwright MCP 执行真实页面写入。优先遵循以下顺序：
   - 打开 `sheet_url`
   - 确认当前 tab 名与 `sheet_name` 一致；不一致时先切换 tab，再继续
   - 通过名称框或等价稳定方式选中 `target_range`，不要优先依赖手动拖拽选区
   - 将 TSV 作为整块覆盖粘贴，不逐单元格填写
   - 粘贴后先确认行数与 `row_count` 一致，再处理格式
   - 若 `format_level=center`，执行水平居中、垂直居中；自动换行按可读性需要补做
5. 如果当前环境无法在 Python 脚本中直接复用浏览器登录态，不要把浏览器自动化硬塞进 `sheet_sync.py`；保持脚本只负责数据和执行计划，实际页面动作交给 MCP。
6. 失败兜底顺序：
   - 优先保住“数据覆盖成功”，格式整理放在第二优先级
   - 如果工具栏按钮或菜单文案不稳定，改用已经验证过的稳定交互路径，不要无休止重试同一选择器
   - 如果无法稳定完成格式化，至少保留已覆盖的数据，并明确告知用户格式未完全收口
7. 汇报覆盖范围、写入行数、是否做了格式化。

## 模式 D：仅同步已有本地排期到云端

1. 读取 `docs/<版本号>/schedule.md`。
2. 优先调用 `~/.claude/skills/google-doc-export/scripts/schedule_generate.py`，只提取 `## 一、总览` 表格并生成 JSON，不搬运详细拆解全文；默认输出到 `/tmp/google-doc-export/<版本号>/schedule.json`。
3. 调用 `~/.claude/skills/google-doc-export/scripts/sheet_sync.py` 生成 `/tmp/google-doc-export/<版本号>/schedule.tsv` 与 `/tmp/google-doc-export/<版本号>/sync_plan.json`。
4. 按 sync plan 通过 Playwright MCP 执行页面覆盖写入。推荐动作顺序与模式 C 相同：
   - 先校验目标 tab
   - 再通过名称框或等价稳定方式选中目标范围
   - 使用 TSV 做整块覆盖
   - 若目标区域已有旧值，优先先清空整个任务区，再执行整块粘贴，避免新旧内容错位拼接
   - 不要把整段 TSV 填进单元格编辑框或公式栏；要确保粘贴目标是当前选区本身，而不是某个单独输入框
   - 最后再处理居中/换行等格式
5. 如用户明确要求“完全替换”，应允许新增 / 删除行，以本地文档为准，但默认只覆盖任务区，不要顺手抹掉 sheet 底部已有的说明区。
6. 若远程表中存在“需求文档 / 原始 Google Docs 链接 / 相关说明”区域，默认视为需要保留；如果本次覆盖导致其丢失，必须在同步结束前按最新内容回填。
7. 统一格式后汇报结果。

## 云端同步前检查清单

在模式 C / D 执行云端同步前，先快速自检以下 4 项：

1. **本地文档一致性**：确认 `docs/<版本号>/schedule.md` 中“总览 / 任务拆分 / 排期表”没有明显冲突；若有冲突，先修正文档源数据。
2. **脚本产物是否最新**：确认已经重新生成当前版本对应的 `.json`、`.tsv`、`sync_plan.json`，不要拿旧产物继续同步。若 `sheet_name`、目标范围或其他推导逻辑有调整，必须先重新运行 `schedule_generate.py` 再继续，不要复用旧的 `schedule.json`。
3. **目标范围是否匹配**：确认 `sync_plan.json` 中的 `sheet_name`、`target_range`、`row_count` 与当前本地文档一致。
4. **Google 登录态是否可用**：确认当前 Playwright 浏览器会话已经可打开目标 Google Sheets；如果还没登录，先让用户补登录，再继续同步。

这一步只求快速排雷，不要把它扩写成冗长流程。目的是在真正写云端前，先避免最常见的同步错位和旧数据覆盖问题。

## 需求文档生成格式要求

生成项目内需求文档时，默认使用以下结构：

- 需求概述
- 功能目标
- 功能流程（含原始流程图引用）
- 功能入口与作用范围
- 各页面需求（展开页、处理页、操作页）
- 特殊拦截与异常处理
- 版本升级与运营展示
- 验收要点
- 待补充项

图片引用格式：

- Android Studio Markdown 渲染器不支持 `<img>` 标签
- 使用纯链接：`> [图片说明](assets-dir/image.png)`

默认命名：

- 需求文档：`docs/<版本号>/<功能名>.requirement.md`
- 排期文档：`docs/<版本号>/schedule.md`
- 图片目录：`docs/<版本号>/assets/`

## 异常与兜底

### Google 登录

- Google 登录需要用户手动在 Playwright 浏览器中完成，无法完全自动化。

### 导出质量

- txt 导出可能丢失表格结构和格式，需要人工确认关键信息。
- docx 中流程图若导出质量差，需要提醒用户从原始文档手动补图。

### 云端同步异常

- 如果页面结构不稳定或 Playwright 点击格式菜单失败，不要无休止重试同一条点击路径。
- 若同步逻辑已脚本化，优先切回脚本方案。
- 若当前只有 Playwright 方案，先完成数据覆盖，再把格式整理视为次级步骤。
- 任务区覆盖后，要额外检查 sheet 底部的“需求文档 / 原始 Google Docs 链接 / 相关说明区”是否仍在；若被覆盖，需在本次会话内补回。

### 数据边界

- 非本人负责项的开发预估周期是否留空，按本地文档为准，不要自行脑补。
- 若本地文档存在“总览 / 详细拆解 / 排期表”不一致，先修正文档源数据，再同步云端。

## 最终汇报模板

完成后简要汇报：

- 执行模式（A / B / C / D）
- 生成的本地文件路径
- 提取的图片数量
- 是否生成本地排期文档
- 是否同步云端排期
- 云端覆盖的 sheet 与范围
- 是否做了格式统一
- 仍需人工补充的项

## 后续演进建议

如果用户明确想把这套能力长期沉淀下来，应建议继续补齐：

1. `scripts/schedule_generate.py`
2. `scripts/sheet_sync.py`
3. 项目级列映射配置
4. Google Sheets API 认证方案

目标是让 skill 只负责编排，脚本负责稳定执行。