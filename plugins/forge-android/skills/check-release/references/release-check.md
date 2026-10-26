# 命令、报告及边界

工具使用 Python 3.10+ 标准库，无公共环境安装依赖。统一入口 `scripts/release-check.py`（相对于本技能根）。

```bash
# 提交端点与工作区分开；以下标签必须由用户确认
python3 -I "<技能目录>/scripts/release-check.py" --repo "<仓库>" --project <项目id> --base <发布tag> --target <候选commit> --output-dir "<新目录>"
python3 -I "<技能目录>/scripts/release-check.py" --repo "<仓库>" --project <项目id> --base <发布tag> --worktree --output-dir "<新目录>"
# 以下均需各阶段明确授权，不是普通静态检查的必要步骤
python3 -I "<技能目录>/scripts/release-check.py" --repo "<仓库>" --project <项目id> --base <发布tag> --worktree --resolve-dependencies --run-draft-tests --run-purchase-tests --output-dir "<新目录>"
python3 -I "<技能目录>/scripts/release-check.py" --repo "<仓库>" --project <项目id> --base <发布tag> --check-configs --output-dir "<新目录>"
python3 -I "<技能目录>/scripts/release-check.py" --repo "<仓库>" --project <项目id> --base <发布tag> --analyze-apk --old-apk "<旧APK>" --new-apk "<新APK>" --output-dir "<新目录>"
```

用户明确暂缓某未执行项时可用`--defer "8=等待任务映射确认"`记录；只有未执行项可暂缓，不能抹掉已执行检查或把暂缓当通过。

## 交互入口与原始报告

用户正常发起发版检查时按 [交互式编排](interactive-run.md) 执行，不要求用户自行选择CLI参数。此处report.md/report.json指每个阶段的原始脚本报告；本轮根目录report.md是Agent结合人工核对与用户选择生成的统一汇总。阶段目录必须全新，原始报告不覆盖。session.json是编排记录，当前CLI不读取它，也不从中自动取得权限。

## 来源与结果

- `report.md` 与 `report.json`，包含全部15项。`checks` 为底层检查，`checklist` 为15项总表，`capabilities` 为适配状态。退出0仅已执行检查无异常且完整，1存在异常，2有待确认/未执行或输入错误；全量放行字段始终false。人工项未完成时正常退出2。
- `input_digest/base_digest` 是目标/基线业务输入摘要，覆盖各模块正式源码、测试、资源及构建输入（工作区包含未跟踪源码，不包含无关外部环境）。`tool_config_digest` 独立覆盖当前脚本与该项目JSON，不能证明它们属于历史提交。不包含所有全局Gradle环境，不能声称完全可复现。
- 外部`--dependency-report`只证明读取了该文本，记录摘要，不当成本轮现场解析。无最终完整YUV集合、解析失败、未知替换均待确认。
- `dependency_log.txt`、`draft_log.txt`、`purchase_log.txt`仅实际执行时产生；配置快照在`configs/`并附时间/来源/摘要。报告/日志可能含内部信息，只留本地，不自动上传。
- 独立新鲜JUnit目录、禁用缓存/增量；测试选择器必须完整类名。即使关联测试通过，草稿字段业务默认值和购买动态链路仍不自动通过。

## APK委托

明确旧新顺序，调用现有APK技能，输出在本轮`apk-analysis/report.md`、`report.json`，总表记录两份APK摘要、工具路径/摘要、报告摘要及链接、大小/百分比/分类/ZIP开销对账、主要增减项。不读取过往报告来冒充本轮；输入/工具并发改变则结果过期。

下游退出0=测量完整，1=执行错误，2=ZIP可用但DEX归因不完整；总表不把测量完整解释成合理增长。没有真实APK时明确未执行。包归组仅为未压缩DEX结构，不是SDK压缩贡献分摊。mapping只有最终backend=dex R8标记精确匹配才用于归因；当前适配层不接受mapping，需按APK技能另行核对，不能静默套用。

可选 `--apk-context <JSON>`登记用户确认的口径，结构为old/new各含channel、abi、package_kind、build_type、release_identity非空字符串；声明不能替代APK元数据。默认可比性未知，不凭文件名或tag源码认定APK身份。ABI/渠道等不等时标口径不一致。不自动构建/下载/安装/上传或执行APK内容。Python从可信技能目录以`-I`运行。

## 解析范围

这是保守词法检查，不是完整Groovy/Java/Kotlin编译器。构建动态表达式、同名模型、多类文件、Kotlin模型、复杂字段、调用移动/复制与多层继承都可能需人工核对。不得把“不涉及”扩展为整个业务无需回归。AI标识、需求埋点、Firebase默认模板及真实购买透传仍人工。

包内配置先报告差异再另行确认更新，索引/正文不一致、同版本漂移、403/404、镜像混用均保留。正式对象URL必须精确登记；响应最多16MiB，gzip解压后同限。项目例外写入configs.exceptions，保留未完成，不吞错。未适配项目不发网络请求。

无显式接收者的 `getOrThrow()` 新增调用也作为待确认候选报告（如 Kotlin with/apply 内调用）；不凭同名断言属于Result接口。Kotlin普通函数声明、注释和字符串排除，复杂声明及Java同名方法仍需人工核对。
