# 本轮记录与汇总格式

这是Agent维护的本地编排记录，不是新增CLI参数，也不是可执行权限文件。脚本原始report.json保持不变；Agent把用户回答及代码复核记录到session.json，合并解释写report.md。不自动执行记录中的命令或路径。

## session.json

根对象固定包含以下字段；未知值用null/空列表，禁止编造：

| 字段 | 内容 |
|---|---|
| schema_version | 1 |
| session_id | 本轮唯一标识 |
| phase | checking / reported / fixing / rechecked |
| project、repo、variant | 已核对的项目身份 |
| scope | base_tag、base_commit、base_confirmed、target_commit、mode（commit/worktree）、head、input_digest、tool_config_digest |
| permissions | 各阶段的本轮授权记录：action、decision、scope、answered_at；没有授权就是未授权 |
| answers | question_id、question、answer、reason、answered_at、applies_to（本轮scope）、source（用户选择/用户自述） |
| stages | id、kind、status、report_path、started_at、finished_at、base_commit、input_digest、tool_config_digest、error；未生成报告则report_path=null |
| checks | 恰好15项，number=1..15且不重复；name、timing（pre-release/post-rollout）、status、script_evidence、agent_review、user_confirmation、gaps、stale |
| issues | id（R01起递增）、check_numbers、title、impact、evidence、recommendation、state（open/accepted-risk/fixed-pending-verification/verified-fixed）、resolution |
| exceptions | check_number、path、historical_reason、current_decision、reason、applies_to、reconfirm_next_release |
| final_report | 初版统一汇总路径 |
| latest_report | 存在修订时指向最新汇总；无修订则与final_report一致 |
| maintenance_reminders | 非缺陷提醒及依据、影响、适用范围；不占用问题编号 |
| revisions | 修订报告路径及时间，初版不覆盖 |
| release_approved | 始终false；工具不替用户授权发布 |

checks.status沿用通过/异常/待确认/未执行/不涉及；灰度后事项在timing中区分，不把“尚未开始灰度”作为发版前异常。

证据列表每条包含source、path（无文件可为null）、summary、verified_scope、timestamp。代码依据须给文件与行号；测试须给本轮结果来源。通过必须说明通过的是哪一层；只有用户自述时明确标注，不升级为工具验证。

session.json只保存决策所需摘要；不复制完整日志、签名、token、账号标识。恢复时验证路径属于本轮或已确认的输入，不把其他目录的同名报告自动接入。

## report.md

```markdown
# <项目> <版本> 发版检查报告

## 本次范围与结论
- 基线及用户确认、候选commit/工作区摘要、渠道、产物身份
- 已完成/待确认/未执行数量（前置检查与灰度后待办分开）
- 是否存在过期证据；不能把“流程跑完”写成“允许发布”

## 已确认问题
| 编号 | 检查项 | 问题与影响 | 证据 | 建议 | 处理状态 |

## 仍需确认
| 检查项 | 未确定内容 | 已做核对 | 还缺什么 |

## 暂缓或未执行
| 检查项 | 原因 | 本轮用户决定 | 风险或恢复条件 |

## 已完成检查
区分静态、Agent代码核对、契约测试、运行验证和用户确认。

## 全部15项
| 项 | 事项 | 时点 | 状态 | 证据范围 | 来源与缺口 |

## 灰度后待办
仅在用户告知开始灰度后提醒发送、存档及下一开发版本，不擅自执行。

## 输入与原始报告
列阶段报告、摘要及采集时间；冲突/过期证据明确标出。
```

报告前核对：15项齐全；所有异常有问题ID；没有用最后一阶段的未执行抹掉此前证据；没有把暂缓变通过；历史例外与本轮选择可区分；问题与缺口没有因阶段失败而消失。
