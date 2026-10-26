# 批量操作流程

批量添加/删除网易云歌单中歌曲的操作细节。

## 前置条件

- `weapiEncrypt()` 已注入到页面上下文（见 `weapi-encrypt.md`）
- CSRF token 已获取：`document.cookie.match(/__csrf=([^;]+)/)?.[1]`
- 分类 CSV 已准备好，歌单 ID 已确认

## 数据准备

### 执行前 gating

在构建批次前，先确认增强版分类结果已经完成复核：

- 只处理 `needs_review = no` 且 `final_categories` 非空的歌曲
- 不从 `candidate_categories` 直接生成加歌批次
- 如果 review queue 还没处理完，要么继续复核，要么明确跳过未确认歌曲

### 构建批次配置

从增强版分类 CSV + 源歌单 track 数据构建每歌单的 track ID 列表：

```python
import csv, json
from collections import defaultdict

# 源歌单 tracks（从 API 响应获取）
with open('playlist_tracks.json') as f:
    data = json.load(f)
track_ids = [t['id'] for t in data['playlist']['tracks']]

# 增强版分类结果
cat_tracks = defaultdict(list)
with open('classification.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    idx_key = reader.fieldnames[0]  # 处理 BOM
    for row in reader:
        if row.get('needs_review', '').strip().lower() in {'yes', 'true', '1'}:
            continue
        final_categories = [c.strip() for c in row['final_categories'].split(';') if c.strip()]
        if not final_categories:
            continue
        idx = int(row[idx_key]) - 1
        tid = track_ids[idx]
        for cat in final_categories:
            cat_tracks[cat].append(tid)

# 歌单 ID 映射
playlist_map = {
    "类别名1": "歌单ID1",
    "类别名2": "歌单ID2",
    # ...
}

# 生成批次（每批 ≤ 20 首）
batches = []
for cat, pid in playlist_map.items():
    tids = cat_tracks[cat]
    for i in range(0, len(tids), 20):
        batches.append({
            "playlist_id": pid,
            "category": cat,
            "track_ids": tids[i:i+20]
        })
```

### 保存批次配置

```bash
# 输出为 JSON，供 Playwright 脚本读取
python3 -c "import json; json.dump(batches, open('/tmp/batch_config.json','w'), ensure_ascii=False)"
```

> `classification.csv` 在 v2 中应包含 `final_categories` 和 `needs_review` 字段；批量加歌只消费最终确认后的分类结果。

## 执行批量添加

### Playwright 注入执行

在 `page.evaluate` 中执行以下 JavaScript：

```js
async () => {
  const csrf = document.cookie.match(/__csrf=([^;]+)/)?.[1];
  const results = [];

  // batches 数组由外部拼入（或从 JSON 文件加载）
  const batches = BATCH_DATA_PLACEHOLDER;

  for (let i = 0; i < batches.length; i++) {
    const { playlist_id, category, track_ids } = batches[i];
    const encrypted = window.weapiEncrypt({
      trackIds: JSON.stringify(track_ids),
      pid: playlist_id,
      op: 'add'
    });

    try {
      const resp = await fetch(
        '/weapi/playlist/manipulate/tracks?csrf_token=' + csrf, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          credentials: 'include',
          body: 'params=' + encodeURIComponent(encrypted.params)
               + '&encSecKey=' + encodeURIComponent(encrypted.encSecKey)
        }
      );
      const text = await resp.text();
      const data = JSON.parse(text);
      results.push({
        batch: i + 1, category, playlist_id,
        trackCount: track_ids.length,
        code: data.code,
        message: data.message || 'ok'
      });
    } catch (e) {
      results.push({
        batch: i + 1, category, playlist_id,
        error: e.message
      });
    }

    // 间隔 500ms 防限流
    await new Promise(r => setTimeout(r, 500));
  }

  return results;
}
```

### 批次数据注入方式

由于 `page.evaluate` 中无法直接读取本地文件，需要将批次数据拼入 JS 代码：

**方案 A：直接拼接（推荐）**
```python
import json
js_batches = json.dumps(batches, ensure_ascii=False)
js_code = f"""
async () => {{
  const batches = {js_batches};
  // ... 执行逻辑
}}
"""
# 通过 Playwright evaluate 执行
```

**方案 B：分批执行**
如果数据量太大导致单个 evaluate 调用超时，按歌单分组，每个 evaluate 添加一个歌单的所有歌曲。

## 错误处理

| 响应码 | 含义 | 处理 |
|--------|------|------|
| 200 | 添加成功 | 继续 |
| 502 | 歌曲已存在（重复） | 忽略，继续 |
| 其他 | 需要排查 | 记录，继续 |

## 验证

执行完毕后验证每个歌单的曲目数：

```js
async () => {
  const csrf = document.cookie.match(/__csrf=([^;]+)/)?.[1];
  const playlists = PLAYLIST_MAP_PLACEHOLDER; // { "类别名": "歌单ID", ... }
  const results = {};

  for (const [name, id] of Object.entries(playlists)) {
    const encrypted = window.weapiEncrypt({ id, n: 1000000, s: 8 });
    const resp = await fetch('/weapi/v6/playlist/detail?csrf_token=' + csrf, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      credentials: 'include',
      body: 'params=' + encodeURIComponent(encrypted.params)
           + '&encSecKey=' + encodeURIComponent(encrypted.encSecKey)
    });
    const text = await resp.text();
    const data = JSON.parse(text);
    results[name] = data.playlist?.trackCount || 'error';
    await new Promise(r => setTimeout(r, 300));
  }
  return results;
}
```

## 注意事项

1. **每批 ≤20 首**：网易云 API 单次调用有数量限制
2. **顺序执行**：并发请求会导致 Brotli 解码失败（`r.json()` 返回空）
3. **间隔 500ms**：防止被限流
4. **502 是正常的**：同一首歌在多个类别时会出现重复，忽略即可
5. **先加到非通勤歌单**：用户可能已在目标歌单手动添加过歌曲，最后处理该歌单可减少重复

---

## 清空源歌单（批量删除）

分类加歌完成后，可选清空来源歌单。使用相同的 API，将 `op` 改为 `'del'`。

### 构建删除批次

```python
# 从源歌单 JSON 提取所有 track ID
track_ids = [t['id'] for t in data['playlist']['tracks']]

# 每批 ≤ 20 首
batches = []
for i in range(0, len(track_ids), 20):
    batches.append(track_ids[i:i+20])

# 保存
json.dump(batches, open('/tmp/remove_batches.json', 'w'))
```

### 执行删除

```js
async () => {
  const csrf = document.cookie.match(/__csrf=([^;]+)/)?.[1];
  const batches = REMOVE_BATCHES_PLACEHOLDER; // [[id,id,...], [id,id,...], ...]
  const sourcePlaylistId = 'SOURCE_PLAYLIST_ID';
  const results = [];

  for (let i = 0; i < batches.length; i++) {
    const trackIds = batches[i];
    const encrypted = window.weapiEncrypt({
      trackIds: JSON.stringify(trackIds),
      pid: sourcePlaylistId,
      op: 'del'
    });

    try {
      const resp = await fetch(
        '/weapi/playlist/manipulate/tracks?csrf_token=' + csrf, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          credentials: 'include',
          body: 'params=' + encodeURIComponent(encrypted.params)
               + '&encSecKey=' + encodeURIComponent(encrypted.encSecKey)
        }
      );
      const text = await resp.text();
      const data = JSON.parse(text);
      results.push({
        batch: i + 1,
        removed: trackIds.length,
        remaining: data.count,
        code: data.code
      });
    } catch (e) {
      results.push({ batch: i + 1, error: e.message });
    }

    await new Promise(r => setTimeout(r, 500));
  }

  return results;
}
```

### 删除验证

```js
async () => {
  const csrf = document.cookie.match(/__csrf=([^;]+)/)?.[1];
  const encrypted = window.weapiEncrypt({ id: 'SOURCE_PLAYLIST_ID', n: 1000, s: 8 });
  const resp = await fetch('/weapi/v6/playlist/detail?csrf_token=' + csrf, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    credentials: 'include',
    body: 'params=' + encodeURIComponent(encrypted.params)
         + '&encSecKey=' + encodeURIComponent(encrypted.encSecKey)
  });
  const text = await resp.text();
  const data = JSON.parse(text);
  return {
    name: data.playlist?.name,
    trackCount: data.playlist?.trackCount
  };
}
```

### 注意事项

1. **不可逆**：删除后歌曲不会回到源歌单，必须先确认用户意图
2. **每批 ≤20 首**：与添加操作相同限制
3. **502 可忽略**：歌曲已被其他操作移除时会出现，继续即可
4. **响应含 count**：`data.count` 表示歌单当前剩余歌曲数，可用于监控进度
