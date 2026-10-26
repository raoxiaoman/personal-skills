# weapi 加密方案

网易云音乐 `weapi` 接口使用 AES-128-CBC + RSA 加密。必须在页面 JS 上下文中实现，因为页面已加载 CryptoJS 和 RSA 工具函数。

## 加密流程

```
原始 JSON 数据
    │
    ▼
┌─────────────────────┐
│ AES-CBC 加密        │  key: 0CoJUm6Qyw8W8jud
│ (第一层)            │  iv:  0102030405060708
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ AES-CBC 加密        │  key: 随机 16 位字母数字
│ (第二层)            │  iv:  0102030405060708
└─────────────────────┘
    │
    └────→ params (Base64)

┌─────────────────────┐
│ RSA 加密            │  modulus: (见下方)
│ (随机 key)          │  exponent: 010001
└─────────────────────┘
    │
    └────→ encSecKey (Hex)
```

## 常量

| 名称 | 值 |
|------|-----|
| AES 固定密钥 | `0CoJUm6Qyw8W8jud` |
| IV | `0102030405060708` |
| RSA exponent | `010001` |
| RSA modulus | 见下方 |

### RSA 模数（258 hex chars = 1024-bit）

```
00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7
```

> **注意**：网易云可能更新此模数。如加密后 API 返回空响应，需重新从页面 JS 源码中提取。
> 提取方法：搜索 JS 中 `emj` emoji→hex 映射表，拼接还原 `RSAKeyPair` 构造参数。

## 注入代码（在 Playwright page.evaluate 中执行）

```js
// 将此函数注入到网易云页面上下文
window.weapiEncrypt = function(data) {
  const text = JSON.stringify(data);
  const CryptoJS = window.CryptoJS;
  const iv = CryptoJS.enc.Utf8.parse('0102030405060708');

  // 生成随机 16 位 key
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let randomKey = '';
  for (let i = 0; i < 16; i++) {
    randomKey += chars.charAt(Math.floor(Math.random() * chars.length));
  }

  // 第一层 AES：固定 key
  const firstPass = CryptoJS.AES.encrypt(
    text,
    CryptoJS.enc.Utf8.parse('0CoJUm6Qyw8W8jud'),
    { iv, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 }
  ).toString();

  // 第二层 AES：随机 key
  const secondPass = CryptoJS.AES.encrypt(
    firstPass,
    CryptoJS.enc.Utf8.parse(randomKey),
    { iv, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 }
  ).toString();

  // RSA 加密随机 key
  setMaxDigits(130);
  const rsaKey = new RSAKeyPair(
    '010001',
    '',
    '00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7'
  );
  const encSecKey = encryptedString(rsaKey, randomKey);

  return { params: secondPass, encSecKey };
};
```

## 页面依赖

注入前需确认页面已加载以下全局函数/对象：

| 变量 | 用途 |
|------|------|
| `window.CryptoJS` | AES 加密 |
| `window.setMaxDigits` | RSA 辅助 |
| `window.RSAKeyPair` | RSA 密钥对构造 |
| `window.encryptedString` | RSA 加密执行 |
| `window.BigInt` / `window.BarrettMu` | 大数运算 |

这些在网易云主页加载后均可用。如果不在主页上下文，需先导航到 `music.163.com`。

## 调用 API

```js
// 获取 CSRF token
const csrf = document.cookie.match(/__csrf=([^;]+)/)?.[1];

// 调用 weapi 接口
const resp = await fetch('/weapi/playlist/manipulate/tracks?csrf_token=' + csrf, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  credentials: 'include',
  body: 'params=' + encodeURIComponent(encrypted.params)
       + '&encSecKey=' + encodeURIComponent(encrypted.encSecKey)
});
```

## 重命名歌单

使用 `/weapi/playlist/update/name` 端点（注意：不是 `/weapi/playlist/update`，那个会 404）。

```js
const encrypted = window.weapiEncrypt({ id: playlistId, name: '新歌单名' });
const resp = await fetch('/weapi/playlist/update/name?csrf_token=' + csrf, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  credentials: 'include',
  body: 'params=' + encodeURIComponent(encrypted.params)
       + '&encSecKey=' + encodeURIComponent(encrypted.encSecKey)
});
```

> **踩坑**：`/weapi/playlist/update` 返回 404 "接口未找到"，正确端点必须带 `/name` 后缀。

## 已知 API 端点汇总

| 操作 | 端点 | 关键参数 |
|------|------|----------|
| 获取歌单详情 | `/weapi/v6/playlist/detail` | `id`, `n`, `s` |
| 加歌/删歌 | `/weapi/playlist/manipulate/tracks` | `trackIds`, `pid`, `op` |
| 重命名歌单 | `/weapi/playlist/update/name` | `id`, `name` |
| 创建歌单 | 需通过 UI 自动化 | - |

## 踩坑记录

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `/weapi/playlist/update` 返回 404 | 端点路径不完整 | 改用 `/weapi/playlist/update/name` |
| `/#/playlist?id=xxx` 打开 404 | 网页播放器路由变化 | 先到主页获取上下文，再走 API 调用 |
| 并发请求 Brotli 解码失败 | 网易云不支持并发 weapi 请求 | 改为顺序执行，间隔 500ms |
| 批量加歌单次上限 | API 限制 | 每批 ≤20 首 |

## 响应码

| code | 含义 |
|------|------|
| 200 | 成功 |
| 502 | 歌单内歌曲重复（忽略即可） |
| 其他 | 需排查 |

## 职责边界

本文件只负责加歌/删歌/重命名所需的 weapi 加密与请求格式。
分类准确性、外部标签补全、评分规则和 review queue 统一在 `SKILL.md` 中定义。
