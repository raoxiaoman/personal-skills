# 按需工作流

只进入请求涉及的阶段。以下命令是接口用法，不表示已经执行或验证。把 `<技能目录>` 替换为本技能实际绝对路径，把 `$WORK` 设置为本次独立工作区，例如 `/tmp/forge-templates-cover/<任务>/`。输入和输出均使用明确路径，示例中的输出必须尚不存在。

## 准备与生成

### 1. 固定输入与归属

确认当前业务项目、模板用途、正式 `templateNum`、横竖屏画板和真实字体文件。编号从当前项目事实核对；查阅总配置不等于获准修改总配置。不把临时调试编号直接发布。

工作区按用途存放 `input/`、`svg/`、`fonts/`、`exports/`；生成、栅格化、合并和打包各用新输出路径。下载包和解压包分别放入新的空目录，脚本不放在这些目录中。不从素材或导出目录启动解释器，读取文件使用隔离模式 `-I`。

`meta.json` 示例，路径仅为占位，不是可直接写入的设备路径：

```json
{
  "templateNum": 32,
  "canvas": [1075, 1434],
  "canvasH": [1080, 610],
  "fontDir": "/<当前宿主确认的字体目录>",
  "stickerDir": "/<当前宿主确认的贴纸目录>",
  "fonts": {"Example:Regular": "Example-Regular.ttf"}
}
```

`fontDir`、`stickerDir` 是配置引用的宿主目录，不是本地素材目录。`fonts` 显式映射 Figma 的 `Family:Style` 到真实文件名，不靠命名猜测字体。两种画布尺寸按当前项目确定，上述数字只是旧模板示例；真实导出的画布尺寸优先保留。

### 2. 仅在需要时读取 Figma

1. 从用户给出的链接确认文件与横竖屏 node-id。按当前 MCP 要求先建立文件会话，复用返回的会话 ID。
2. 每次调用 `use_figma` 前加载 `figma-use`，再按当前工具协议执行 `scripts/figma_dump.js`；脚本只读，不改节点或样式。
3. 分别保存竖屏与横屏 dump。明确导出对象，文字递归识别；只有无文字的复杂图形组才整体导出为素材。
4. 遇到混合字体、混合颜色或当前配置不可表达的效果时，失败或标记人工处理，不把文字静默栅格化成贴纸。需要改设计或转换表现形式时另行确认。
5. 逐项确认背景照片、画板底色、遮罩和装饰；尺寸过滤只能提出候选，不能证明大尺寸元素一定是背景。

### 3. 生成并审阅报告

```bash
python3 -I -B '<技能目录>/scripts/build_config.py' \
  --figma "$WORK/input/dump_v.json" \
  --figma-h "$WORK/input/dump_h.json" \
  --blueprint '<技能目录>/reference/blueprint.json' \
  --meta "$WORK/input/meta.json" --out "$WORK/generated-v1"
```

生成器要求两个方向及完整显式元数据，新输出目录拒绝覆盖。预期产物包括 `cover_template_item_config_32.json` 和 `conversion_report.json`。

阅读报告中的剔除候选、文字合并、横竖屏对应与待确认项。按 [config-contract.md](config-contract.md) 核对 ID、文字内容和文件引用。重复文案、相似装饰、低置信对应须人工消歧；数量相同和贪心分数最高都不等于匹配正确。不能为通过数量检查随意丢弃元素。

### 4. 准备贴纸与字体

贴纸可以从 Figma 导出 SVG，再用本机已有 `rsvg-convert` 栅格化；缺少命令就停止并报告，不自动安装。

```bash
python3 -I -B '<技能目录>/scripts/rasterize_svg_assets.py' \
  --input "$WORK/svg" --out "$WORK/png-v1"
```

拒绝外部引用、样式块和需进一步解析的转义样式；这是一套受限 SVG 输入检查，不是通用 SVG 沙箱，不访问网络或本地外部资源。转换不自动删除 SVG 中的背景；要删除背景须确认设计语义后单独处理。检查输出尺寸、alpha 实际取值，并在棋盘格或不同底色上检查视觉透明性；不能只凭扩展名或存在 alpha 通道判定合格。

建立并保留 `templateN_stickerK.png → 旧编号的素材语义 → 本次源文件` 映射。更新旧模板时以旧配置或旧 zip 为准，逐个对比尺寸和缩略图；相似箭头、爱心等不能按新文件名或目录顺序猜编号。字体从用户提供的真实文件取得，逐一对应配置映射。

## 合并导出

此阶段只需已有基础配置和 App 导出，不要求重新抓 Figma 或操作设备。

完整导出含 `texts`、`stickers`、`textsH`、`stickersH` 时，四组整体作为真值：

```bash
python3 -I -B '<技能目录>/scripts/merge_export.py' \
  --base "$WORK/generated-v1/cover_template_item_config_32.json" \
  --exported "$WORK/exports/full.json" \
  --out "$WORK/merged-v1.json"
```

部分方向导出必须显式选择方向；竖屏只替换 `texts/stickers`，横屏只替换 `textsH/stickersH`，保留另一方向已有数据：

```bash
python3 -I -B '<技能目录>/scripts/merge_export.py' \
  --base "$WORK/merged-v1.json" --exported "$WORK/exports/vertical.json" \
  --direction v --out "$WORK/merged-v2.json"
```

横屏使用 `--direction h`。输出始终是新文件，不覆盖基础配置或导出。合并后重新核对两类数量、样式 ID、文字内容、贴纸引用和各方向画布。禁止用生成器旧矩阵回填 App 手调值。

## 打包与本地校验

先检查全部配置引用、字体、贴纸和封面，再创建新输出目录。旧 `build` 不删除、不清空；失败时报告缺失素材，不以不完整包交付。

```bash
python3 -I -B '<技能目录>/scripts/package_template.py' \
  --config "$WORK/merged-v2.json" --stickers "$WORK/png-v1" \
  --fonts "$WORK/fonts" --cover "$WORK/input/cover.webp" \
  --template-num 32 --out "$WORK/package-v1"

python3 -I -B '<技能目录>/scripts/validate_template.py' \
  --config "$WORK/package-v1/build/cover_template_item_config_32.json" \
  --zip "$WORK/package-v1/template32.zip"
```

确认外部 item config 与 zip 内 item config 匹配。zip 包含配置引用的全部贴纸和字体，不含总配置、历史包、工作目录或临时文件；检查清单、重复条目和文件名映射。打包结果中的 `build/` 是本次新目录，不是可覆盖的固定旧目录。

校验通过只说明本地核心一致性，不说明完整 App schema 兼容或视觉正确。需要确认宿主行为时进入下一节；若本次只要求本地合并或打包，明确未进行宿主与视觉验收即可。

## 设备验证（独立授权）

先确认当前项目规则和获准动作。制作不授权设备写入，设备写入也不自动授权安装启动。没有授权时仅整理待执行清单。

- 只使用当前 `ANDROID_SERIAL`。未设置或绑定设备不可用时停止确认，不枚举设备让用户重新挑选。
- 按当前项目确认包名、资源根目录、配置加载来源与导出入口；不直接套用旧项目私有路径，不自动写私有目录。
- 安装启动遵循当前项目流程；页面操作优先项目已有 Maestro。没有可用流程时说明缺口，不静默扩大操作范围。
- 同时校对横竖屏的文字、字体、换行、装饰、旋转及比例切换。字号、矩阵和旋转方向以真实宿主与导出为据。
- 模板不可见时检查当前项目内置总配置、下载总配置和版本选择逻辑；任何临时配置写入仍需对应授权，不能直接修改业务仓库总配置。
- 手调后通过当前 App 导出入口取得文件，保存到新本地路径，再进入“合并导出”。不凭截图单改主矩阵，避免布局重算后再次位移。

## 发布（独立授权）

从当前项目的发布配置、`site`、`fonts-site`、实际客户端域名与现有发布工具确认云端目标。旧 VideoGuru 配置不能证明 YouCut 路径适用，不能把历史 bucket、域名或个人绝对脚本路径写成通用事实。

1. 列出准确上传清单和目标；资源 staging 只含封面、item config、zip 及项目要求独立存放的字体。
2. 默认排除 `cover_config_android_v2.json`，包括 zip、staging 及可能被递归同步的父目录。总配置更新另行授权。
3. 用户明确授权后复用当前项目现有发布工具；不能以“准备发布”推定上传授权，也不自动改为其他上传方式。
4. 需要可达性检查时，显式传入已确认的 HTTPS URL。该参数会访问网络，不属于默认本地校验：

```bash
python3 -I -B '<技能目录>/scripts/validate_template.py' \
  --config "$WORK/package-v1/build/cover_template_item_config_32.json" \
  --zip "$WORK/package-v1/template32.zip" \
  --base-url 'https://<已确认资源主机>/<模板路径>' \
  --font-base-url 'https://<已确认字体主机>/<字体路径>'
```

可选参数只做显式 HTTPS HEAD 可达性检查，不证明远端字节与本地一致、CDN 已刷新或 App 实际下载成功。按获得的证据报告上传、可达性、内容核对和客户端下载各自状态；只做 HEAD 时不得宣称发布闭环完成。
