---
name: mantis
description: >
  MantisBT 问题追踪系统 CLI 工具，通过 REST API Token 访问 mantis.inshot.com。
  仅当用户明确提到 Mantis / mantis.inshot.com / Mantis 工单 / 工单号，或明确要求查看、筛选、评论、更新 MantisBT 记录时触发。
  不要因为用户只提到普通“bug / 问题 / 列表”就触发；代码排障、需求讨论、缺陷分析默认不走本 skill。
---

# MantisBT CLI Tool

通过 MantisBT REST API 稳定访问 `mantis.inshot.com`，所有操作以 API Token 对应用户身份进行，不依赖浏览器 Cookie。

可单独调用 `forge-bugs:mantis`；其他 Agent 可直接读取本文件。CLI 实现在本技能的 `scripts/mantis.sh`，从其他目录加载时使用实际技能目录。Token 保持用户配置目录，不打包进插件。只整理或补充 Bug 描述时转 `forge-bugs:clarify`（其他 Agent 读取相邻 `../clarify/SKILL.md`），不因此自动查询或写入工单。

## 工具与服务

```text
CLI:      ~/.agents/plugins/forge-bugs/skills/mantis/scripts/mantis.sh
Token:    ~/.config/mantis/api-token
API Base: https://mantis.inshot.com/api/rest/index.php
```

公司 MantisBT 为 2.20.0，Apache 未启用 REST URL Rewrite，所以 API 地址必须保留 `/index.php`。

## 首次使用

首次使用或 Token 失效时，先运行：

```bash
mantis check
```

根据结果处理：

- 输出 `✅ API Token 有效`：直接执行用户请求。
- 输出 `API Token 未配置`：运行 `mantis setup <token-file>`，或运行 `mantis setup` 后从标准输入粘贴。
- 输出 HTTP 401/403：Token 无效、已撤销或权限不足，需要用户在 MantisBT 重新创建 Token。
- 命令不存在：确认 `~/.agents/plugins/forge-bugs/skills/mantis/scripts/mantis.sh` 已加入 PATH 或配置别名。

配置示例：

```bash
mantis setup '/path/to/token.txt'
mantis token-status
mantis check
```

Token 文件自动以 `0600` 权限保存。不要输出、回显或把 Token 放进命令行参数；只传 Token 文件路径。

## 推荐查询方式

版本字段必须明确区分：

- `--version`：产品版本
- `--target-version`：目标版本
- `--fixed-version`：修正版本
- `--project`：项目 ID，建议显式传入

当前常用项目：

| 项目 | project id |
|---|---:|
| Captune | 232 |
| Utool Android | 217 |
| Video Maker | 52 |
| YouCut Android | 22 |

默认规则：

- 用户明确写了版本：按用户指定版本查。
- 用户没写版本但写了项目：先取该项目时间戳最新的非废弃版本。
- 用户没写项目和版本：结合当前上下文判断；仍不明确时再追问。

```bash
mantis latest-version --project <project-id>
mantis list --project <project-id> --target-version '<目标版本名>' -m
mantis list --project <project-id> --version '<产品版本名>' -m
mantis list --project <project-id> --fixed-version '<修正版本名>' -m
```

这个默认流程是 Claude 的协作约定，不是 `mantis list` 的隐式行为。用户已明确版本时不要再调用 `latest-version`。

## 常用命令

```bash
# 列表与筛选
mantis list --project 22 -m
mantis list --project 22 --status 50 --assignee 298 -m
mantis list --project 22 --page 2 --page-size 20

# 详情和搜索
mantis view 198148
mantis search 'ANR' --project 22

# 版本
mantis latest-version --project 22

# 写操作
mantis note 198148 '描述修改内容'
mantis update 198148 --status resolved --note '已修复，请测试验证'
```

`list` 支持：

```text
--status / --severity / --category / --assignee / --reporter
--version / --target-version / --fixed-version
--hide-status / --search / --page / --page-size / --markdown / --all / --json
```

REST `issues` 接口使用项目与分页参数，其余条件由 CLI 本地筛选。筛选前遍历全部服务端页，再按 `--page/--page-size` 展示；`--all` 返回完整筛选结果。`MANTIS_FILTER_FETCH_SIZE`（默认 1000）是抓取页大小，不是总量上限；`MANTIS_MAX_PAGES`（默认 1000）限制抓取页数。分页失败、重复页或达到上限会失败退出，不把部分结果报告为完整总数。

机器消费者使用 `mantis list ... --all --json`，不要解析人读表格。成功响应包含 `ok`、原始 `issues`、`count` 和 `pagination`；只有 `pagination.complete=true` 且 `all=true` 才能用于完整统计。失败非零退出，JSON 模式输出 `ok=false/error`，诊断写 stderr。`--json` 也支持 `search/note/update`。

## 写操作规则

`note`、`update`、创建和删除都属于外部写操作：

- 用户明确要求并给出具体 Bug ID、状态或注释内容时，可以执行。
- 信息不完整或语义可能影响多个问题时，先确认。
- 状态更新后 CLI 会回读问题状态，避免接口假成功。
- 状态与注释是两个非原子步骤；`update --json` 的 `steps.status/note` 分别报告 `completed/not_requested/not_attempted/unverified/unknown`。注释失败不回滚已确认的状态，失败退出并报告部分成功；网络失败可能已写入，先回读状态与注释，再决定只补未完成步骤，不能自动重试整个 update 或 POST。
- 查询授权不包含注释或状态写入，代码修复也不默认同步工单。
- 不提供默认删除命令；删除问题必须另行人工确认。

## 负责人 ID

| ID | 人员 |
|---:|---|
| 298 | 饶辉 |
| 177 | 刘宇飞 |
| 217 | 钟杰明 |
| 232 | 周子欣 |

## 状态 ID

| ID | 名称 |
|---:|---|
| 10 | 新建 |
| 20 | 反馈 |
| 30 | 认可 |
| 40 | 已修改 |
| 50 | 已分配 |
| 80 | 已解决 |
| 90 | 已关闭 |

## API 对应关系

| CLI | REST API |
|---|---|
| `check` | `GET /users/me` |
| `list` | `GET /issues` |
| `view` | `GET /issues?id=<id>` |
| `latest-version` | `GET /projects` |
| `note` | `POST /issues/<id>/notes` |
| `update --status` | `PATCH /issues/<id>` |

## 故障处理

- 401：Token 无效或已撤销，重新创建并运行 `mantis setup <token-file>`。
- 403：当前用户没有目标项目、问题或操作权限。
- 404：先确认 API 地址包含 `/api/rest/index.php`，再确认问题或路由存在。
- CLI 与网页结果不一致：检查项目、版本字段和分页；必要时用网页做只读核对，不回退到 Cookie 认证。

## 全部命令

```bash
mantis help
```
