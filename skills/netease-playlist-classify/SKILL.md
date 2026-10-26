---
name: netease-playlist-classify
description: 将网易云音乐歌单中的歌曲按场景/情绪分类，创建并填充多个目标歌单
---

# 网易云音乐歌单分类技能

将用户"我喜欢的音乐"（或其他歌单）中的歌曲按场景/情绪/曲风进行更准确的分类：先读取网易云元数据，再按需补充外部标签证据，经过规则打分与人工复核后，自动创建并填充目标歌单。

## 使用方式

用户发起类似请求时激活：
- "帮我把喜欢的歌分类到不同歌单"
- "网易云音乐的歌太多了，想整理一下"
- "按情绪把歌单分成几个类别"

## 流程概览

```
1. 收集参数 → 2. 获取数据 → 3. 标签增强与分类打分 → 4. Review Queue 复核 → 5. 创建歌单 → 5.5 重命名歌单（如需）→ 6. 批量加歌 → 7. 验证 → 8. 清空源歌单（可选）
```

## 步骤详解

### 1. 收集用户偏好（对话交互）

向用户确认以下参数，未指定时给出默认建议：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| 来源歌单 | URL 或歌单 ID | 当前页面歌单 |
| 分类维度 | 场景 / 情绪 / 曲风 / 自定义 | 场景+情绪混合 |
| 歌单数量 | 目标分类数 | 6-8 个 |
| 命名风格 | 务实 / 文艺 / 混合 | 混合 |
| 允许重复 | 同一首歌出现在多个歌单 | 是 |
| 外部补证策略 | 只补不确定歌曲 / 尽量补全 / 仅人工复核时补 | 只补不确定歌曲 |
| 清空源歌单 | 分类完成后清空来源歌单 | 询问用户 |

### 2. 获取歌单数据

**关键点：网易云 DOM 文本被加密混淆，必须通过 API 获取数据。**

使用 Playwright MCP 打开歌单页面，拦截 API 响应：

```
1. Playwright navigate → https://music.163.com/#/playlist?id=<PLAYLIST_ID>
2. 读取拦截到的 weapi/v6/playlist/detail 响应
3. 提取 playlist.tracks[] → 每首歌的 id, name, ar[].name, al.name
4. 保存为 JSON 文件供后续使用
```

如果用户未登录，引导用户登录后再继续。判断方式：检查页面是否显示了完整的歌曲列表。

### 2.1 重分类模式（来源歌单已清空时）

如果用户已经把“我喜欢的音乐”清空，但之前那批分类歌单还在，不要中断流程，直接切到重分类模式：

```
1. 进入“我的音乐”页，定位已有的分类歌单
2. 识别旧分类歌单的 playlist ID（通常是 8 个目标歌单）
3. 逐个调用 /weapi/v6/playlist/detail 拉取每个歌单的 tracks
4. 按 track_id 去重，合并成新的源数据集
5. 保留每首歌的 source_categories，作为旧分类痕迹
6. 基于合并后的源数据重新分类
7. 如果要真正覆盖旧结果，先清空这 8 个旧分类歌单，再按新版分类批量写回
```

**适用场景：**
- 用户说之前已经把“我喜欢的音乐”清空了
- 需要对旧分类结果做纠偏或整体重分
- 想保留原歌单名字，但重写其中的歌曲内容

**重分类模式额外约束：**
- 不能直接在旧歌单上“增量加歌”，否则旧错分会残留
- 真正重分类时，应先读取旧歌单实时内容，再生成 delete 批次
- 清空后再按新版 `final_categories` 全量写回
- 最终校验时，优先信任实际 `tracks[]` 数量；若 `trackCount` 与 `tracks.length` 暂时不一致，以 `tracks.length` 为准

### 3. 标签增强与分类打分

基于网易云元数据、艺人风格信息和按需补充的外部标签进行分类，不再只按歌名语义判断：

```
1. 读取步骤 2 的 JSON 数据，保留 id、name、alias、ar[].name、al.name 等字段
2. 先做元数据初筛，生成 seed_category
3. 对不确定歌曲按需补外部证据：
   - 艺人级风格信息
   - 曲目级 genre / mood / scene 标签
   - 专辑或单曲简介摘要
4. 输出增强版 CSV 文件：
   index, track_id, track_name, artists, album, netease_alias,
   seed_category, candidate_categories, final_categories,
   confidence, needs_review, evidence_source, evidence_summary,
   external_tags, artist_profile_hint, notes
5. 展示分类结果，让用户审阅
6. 对 `needs_review = yes` 的歌曲进行定向复核，完成后再进入批量加歌

**推荐字段说明：**
- `seed_category`：初筛得到的主类
- `candidate_categories`：候选类别列表
- `final_categories`：最终确认后用于加歌的类别
- `needs_review`：是否需要人工复核
- `evidence_source`：证据来源，如 `netease_meta;artist_profile;lastfm;musicbrainz;search_summary`
- `evidence_summary`：一句话说明分类依据
- `external_tags`：外部补到的 genre / mood / scene 标签
- `artist_profile_hint`：艺人层面的风格提示

**CSV 表头模板：**
```csv
index,track_id,track_name,artists,album,netease_alias,seed_category,candidate_categories,final_categories,confidence,needs_review,evidence_source,evidence_summary,external_tags,artist_profile_hint,notes
```

**CSV 示例行：**
```csv
12,151234567,Centuries,Fall Out Boy,American Beauty/American Psycho,,热血提神,热血提神;节奏撑场,热血提神,high,no,netease_meta;artist_profile;lastfm,anthem/energetic/rock 信号一致且推进感强,anthem;energetic;rock;workout,竞技摇滚与燃向流行,排除情绪低潮
87,198765432,某首边界歌,某歌手,某专辑,,深夜一个人,深夜一个人;情绪低潮,,low,yes,netease_meta;artist_profile,独处感明显但失落感证据不足,,夜间氛围稳定但情绪指向不够,等待复核
```

**填写规范：**
- `candidate_categories`、`final_categories`、`external_tags` 使用分号 `;` 分隔
- `needs_review` 统一写 `yes` / `no`
- `final_categories` 为空表示还未复核完成，不能进入批量加歌
- `evidence_summary` 尽量控制在一句话内，直接说明最关键证据

**外部信息源优先级：**
1. 艺人级风格信息
2. 曲目级标签（genre / mood / scene）
3. 专辑或单曲简介摘要
4. 最后才参考歌名字面语义

**外部补证操作模板：**

1. **Last.fm 优先查曲目标签**
   - 查询关键词：`歌名 + 歌手`
   - 重点提取：genre、mood、scene、user tags
   - 可用标签示例：rock、pop、sad、romantic、energetic、workout、chill、dreamy、party、acoustic
   - 使用方式：
     - 如果 track tags 和艺人风格一致，可作为强信号
     - 如果 tags 明显指向两个类别，可保留双候选并进入打分比较
     - 如果 tag 很泛（如 `favorite`、`seen live`），忽略

2. **MusicBrainz 用于做匹配和艺人确认**
   - 查询关键词：`歌名 + 歌手`，必要时再加专辑名
   - 重点用途：确认曲目、艺人、专辑是否匹配，避免同名歌串错
   - 可提取信息：艺人类型、发行归属、作品关系、标准化名称
   - 使用方式：
     - 更适合做“这是哪首歌”的确认，不直接单独决定情绪分类
     - 当 Last.fm 结果不稳定时，用它辅助确认艺人/作品身份

3. **搜索摘要 / 页面简介用于补场景描述**
   - 适用情况：热门歌、影视原声、ACG、OST、话题曲
   - 重点提取：媒体描述中的曲风、氛围、使用场景
   - 使用方式：
     - 如果简介里明确出现 battle、anthem、love song、ballad、dance track、healing 等词，可作为补充证据
     - 只取稳定的风格描述，不取营销文案式夸张语句

4. **艺人级风格提示作为兜底信号**
   - 当 track-level 证据不足时，参考艺人常见风格
   - 例如：燃向流行摇滚、抒情男声、梦幻独立流行、夜感 R&B
   - 只能作为中信号，不能压过明确的曲目级反证

**查不到时的降级规则：**
- 如果没有外部结果，但艺人风格非常稳定，且网易云元数据不冲突，可给 `medium confidence`
- 如果只有歌名语义、缺少艺人风格和外部证据，直接给 `low confidence`
- 如果是中文小众歌、翻唱、日文歌、纯音乐、OST，外部证据缺失时优先进入 review
- 如果外部来源互相冲突，保留多个 `candidate_categories`，并在 `notes` 标出冲突来源
- 如果完全查不到，但听感倾向从歌手/专辑名也看不出，`final_categories` 留空，等待复核

**推荐补证触发条件：**
- 英文歌名容易被字面误导
- 明显像 anthem / OST / ACG / workout / party 曲
- 情歌但不确定是甜还是苦
- 同时命中两个以上候选类别
- 用户明确指出此前这类歌常被错分

**使用约束：**
- 不要求每首歌都联网补全，只对不确定或高价值歌曲按需补证据
- 查询时优先使用“歌名 + 歌手”组合，避免仅按歌名模糊匹配
- 如果外部证据缺失，可退回网易云元数据 + 艺人风格判断，但必须降低置信度

**分类原则：**
- 歌名只能作为弱信号，不能单独决定最终类别
- 最终分类至少要有两类证据支持：网易云元数据 / 艺人风格 / 外部标签 / 用户已确认示例
- 若外部标签与艺人风格一致，优先按该类别
- 若歌名语义与外部标签冲突，以外部标签 / 艺人风格为准
- 若两个类别都合理且用户允许重复，可双归类
- 若只有歌名语义、缺乏其他证据，标记为 `low` confidence

**八类打分模板：**

1. `通勤顺耳`
   - 加分信号：pop、mid-tempo、easy listening、city pop、轻快、熟悉感、hook 明显、不压情绪
   - 减分信号：过于沉重、过于炸场、实验性太强、长前奏、纯器乐铺陈过长
   - 典型说明：适合路上随手播，不需要太投入，也不会太打扰注意力

2. `深夜一个人`
   - 加分信号：late night、lonely、introspective、moody、slow burn、卧室感、空旷感、后劲强
   - 减分信号：workout、party、anthem、阳光外放、强烈鼓点推进
   - 典型说明：偏内收、适合夜里单独听，情绪不一定悲伤，但通常更沉静

3. `热血提神`
   - 加分信号：energetic、anthem、epic、rock、pump up、motivational、drive、power vocal
   - 减分信号：sad、sleepy、ambient、lullaby、过慢、过软
   - 典型说明：强调唤醒感、推进感、运动感，像 `Centuries` 这类优先往这里看

4. `轻松哼唱`
   - 加分信号：acoustic pop、folk pop、轻松、朗朗上口、chill、温和、旋律亲近
   - 减分信号：情绪负担重、爆发感太强、编曲压迫感强、戏剧张力过大
   - 典型说明：适合跟着哼，听感轻，不以强情绪或强节奏取胜

5. `浪漫心动`
   - 加分信号：romantic、crush、love song、sweet、warm、duet、暧昧感、亲密感
   - 减分信号：明显失恋、愤怒、疏离、竞技感、硬核说唱攻击性
   - 典型说明：偏心动、靠近、甜感或暧昧，不等于所有情歌都归这里

6. `情绪低潮`
   - 加分信号：sad、melancholic、heartbreak、fragile、blue、piano ballad、slow、downcast
   - 减分信号：anthem、workout、epic、energetic、victory、stadium、强烈激励感
   - 典型说明：核心是脆弱、失落、下坠感，不是“严肃”或“年代感”就算低潮

7. `节奏撑场`
   - 加分信号：dance、party、club、groove、edm、funk、bounce、强律动、适合外放
   - 减分信号：过于私密、过慢、铺陈型抒情、低能量民谣
   - 典型说明：能撑住现场气氛或聚会氛围，强调节奏存在感

8. `治愈放空`
   - 加分信号：healing、dreamy、soft、ambient pop、温柔、漂浮感、松弛、舒展
   - 减分信号：焦躁、炸裂、强冲突、过度苦情、攻击性强
   - 典型说明：更偏安抚、松弛和放空，不要求强旋律推动

**实操规则：**
- 如果一首歌同时命中 `热血提神` 和 `节奏撑场`，看它更偏“鼓动你动起来”还是“适合把场子顶住”
- 如果同时命中 `深夜一个人` 和 `情绪低潮`，看它是“独处感”更强还是“失落感”更强
- 如果同时命中 `轻松哼唱` 和 `治愈放空`，看它更偏“顺口好哼”还是“松弛漂浮”
- 如果同时命中 `浪漫心动` 和 `情绪低潮`，优先区分“甜蜜靠近”与“失恋回撤”
- 对 `anthem`、`epic`、`workout`、`stadium rock` 一类标签，默认排除出 `情绪低潮`

### 4. Review Queue 复核

以下歌曲进入复核队列，在用户确认前不写入最终分类：

- `confidence = low`
- 缺少外部 tags，且艺人风格也不稳定
- 候选类别分差太小
- 标题语义与外部证据冲突
- 纯器乐、影视原声、ACG、二创、混剪 BGM 等高歧义内容

复核时：
- 展示 `candidate_categories`、`evidence_summary`、`external_tags`
- 用户可选择保留单分类、改为双分类、或重新指定最终分类
- 复核完成后，把结果写入 `final_categories`

### 5. 在网易云创建歌单

通过 Playwright UI 自动化创建歌单：

```
1. 导航到用户主页歌单区域
2. 点击"新建"按钮（见下方踩坑说明）
3. 输入歌单名称
4. 等待页面 URL 变化（确认歌单 ID 生成）
5. 从 URL 或 DOM 中提取新歌单 ID
6. 重复直到所有歌单创建完毕
```

### 5.5 重命名歌单（如需调整分类名）

如果用户在分类完成后想调整歌单名称，使用 API 重命名：

```
1. 注入 weapiEncrypt()
2. 调用 /weapi/playlist/update/name（注意：不是 /weapi/playlist/update，会 404）
3. 参数：{ id: playlistId, name: '新名称' }
4. 逐个调用，间隔 500ms
```

详见 `weapi-encrypt.md` 中的重命名歌单章节。

### 6. 批量添加歌曲

核心步骤，详见 `weapi-encrypt.md` 和 `batch-add.md`：

```
1. 读取增强版分类 CSV + 歌单 ID 映射
2. 仅处理 `needs_review = no` 且 `final_categories` 非空的歌曲
3. 在页面上下文注入 weapiEncrypt() 函数
4. 按最终分类构建批次（每批 ≤20 首）
5. 逐批调用 /weapi/playlist/manipulate/tracks
6. 处理 502 重复错误（忽略即可）
7. 批次间等待 500ms 防限流
```

### 7. 验证结果

```
1. 调用 /weapi/v6/playlist/detail 获取每个歌单的实际 trackCount
2. 与 CSV 中的 final_categories 预期数量对比
3. 向用户报告最终结果
```

### 8. 清空源歌单（可选）

分类加歌全部完成后，询问用户是否清空来源歌单。**不可逆操作，必须确认。**

```
1. 询问用户是否清空源歌单
2. 用户确认后，构建删除批次（每批 ≤20 首，与加歌相同）
3. 逐批调用 /weapi/playlist/manipulate/tracks，op: 'del'
4. 批次间等待 500ms
5. 最终验证源歌单 trackCount 为 0
```

详见 `batch-add.md` 中的删除操作说明。

## 产物保存位置

执行过程中生成的产物默认直接写入当前技能目录，不要先落到 home 目录。

**固定文件名：**
- 最终分类结果：`latest-classification.csv`
- 最新批次配置：`latest-batches.json`
- 最新校验结果：`latest-verify.json`

**补充产物：**
- 分类源数据或临时抓取结果：`netease-*.json`
- 仅在需要排查时才保留 review queue / 中间校验文件

**推荐做法：**
- 生成文件时直接写到 `~/.claude/skills/netease-playlist-classify/`
- 每次执行完成后，默认覆盖 `latest-classification.csv`、`latest-batches.json`、`latest-verify.json`
- 如果确实需要保留历史版本，再额外另存一份带日期或批次后缀的文件

## 执行清单（下次可直接照着跑）

### 阶段 A：确认输入
- [ ] 拿到来源歌单 URL 或歌单 ID
- [ ] 确认分类维度（场景 / 情绪 / 曲风 / 混合）
- [ ] 确认目标歌单数量
- [ ] 确认命名风格
- [ ] 确认是否允许重复分类
- [ ] 确认是否在完成后清空源歌单

### 阶段 B：抓取网易云数据
- [ ] 打开 `music.163.com` 对应歌单页
- [ ] 确认用户已登录，且能看到完整歌单
- [ ] 拦截 `weapi/v6/playlist/detail` 响应
- [ ] 导出 `playlist.tracks[]` 为 JSON
- [ ] 保留 `id / name / alias / artists / album` 等基础字段

### 阶段 C：初筛与补证
- [ ] 先基于网易云元数据做 `seed_category` 初筛
- [ ] 标记明显边界歌、英文歌名歌、OST/ACG/anthem/workout 倾向歌
- [ ] 对不确定歌曲按优先级补证：Last.fm → MusicBrainz → 搜索摘要
- [ ] 写入 `external_tags / artist_profile_hint / evidence_source / evidence_summary`
- [ ] 生成 `candidate_categories`

### 阶段 D：生成分类结果 CSV
- [ ] 输出增强版 CSV
- [ ] 为每首歌填写 `confidence`
- [ ] 为需要复核的歌标 `needs_review = yes`
- [ ] 暂时无法定类的歌曲保持 `final_categories` 为空

### 阶段 E：Review Queue 复核
- [ ] 把 `needs_review = yes` 的歌曲单独列出
- [ ] 逐首向用户展示候选分类和证据摘要
- [ ] 根据用户反馈修正 `final_categories`
- [ ] 确认 review queue 已清空，或明确跳过未确认项

### 阶段 F：创建歌单
- [ ] 按最终分类名创建目标歌单
- [ ] 记录每个歌单的 playlist ID
- [ ] 建立 `类别名 → 歌单 ID` 映射

### 阶段 G：重命名歌单（如需调整分类名）
- [ ] 用户确认或提出新的歌单名
- [ ] 注入 `weapiEncrypt()`
- [ ] 逐个调用 `/weapi/playlist/update/name`（不是 `/weapi/playlist/update`）
- [ ] 参数：`{ id: playlistId, name: '新名称' }`
- [ ] 间隔 500ms，全部返回 code 200

### 阶段 H：批量加歌
- [ ] 只读取 `needs_review = no` 且 `final_categories` 非空的歌曲
- [ ] 构建每批 ≤20 首的 add 批次
- [ ] 注入 `weapiEncrypt()`
- [ ] 顺序调用 `/weapi/playlist/manipulate/tracks`
- [ ] 忽略 `502` 重复错误
- [ ] 保持批次间 500ms 间隔

### 阶段 I：验证结果
- [ ] 逐个查询目标歌单 `trackCount`
- [ ] 与 `final_categories` 预期数量对比
- [ ] 报告成功数、重复数、异常数

### 阶段 J：可选清空源歌单
- [ ] 再次确认用户要执行不可逆删除
- [ ] 按每批 ≤20 首构建 delete 批次
- [ ] 顺序执行 `op: 'del'`
- [ ] 验证源歌单 `trackCount = 0`

### 阶段 K：最终交付
- [ ] 向用户汇报各歌单最终曲目数
- [ ] 说明哪些歌曲被跳过、待复核或重复
- [ ] 保留分类 CSV 供后续增量整理使用

## 踩坑速查

| 问题 | 解决方案 |
|------|----------|
| DOM 文本加密无法读取 | 拦截 API 响应获取原始 JSON |
| RSA 模数找不到 | 从混淆 JS 中提取 emoji→hex 映射还原（见 weapi-encrypt.md） |
| Playwright click 被遮挡 | 用 `page.getByRole('link', { name: '新 建' })` |
| Chrome cookies 加密 | 不从磁盘读，从页面 `document.cookie` 获取 |
| CSRF token 传递 | URL query 参数 `?csrf_token=<值>` |
| 并发请求 Brotli 解码失败 | 改为顺序执行 |
| 批量加歌 API 限制 | 每批 ≤20 首 |
| `/weapi/playlist/update` 返回 404 | 正确端点是 `/weapi/playlist/update/name` |
| `/#/playlist?id=xxx` 页面 404 | 网页播放器路由可能变化，先到主页获取上下文，再走 API |

## 文件说明

- `weapi-encrypt.md` — weapi 加密实现细节和代码模板
- `batch-add.md` — 批量加歌流程和错误处理
