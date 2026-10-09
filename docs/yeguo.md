# 野果短剧（yeguo）接入说明

> 截至 2026-10 的探测结论与 hg-dl 集成方案。域名轮换频繁，**必须做多候选 + 健康检测**。

---

## 1. 两套线上形态（不要混）

| 形态 | 代表域名 | 技术栈 | 是否适合聚合 |
|------|----------|--------|--------------|
| **A. Nuxt + api.php** | `yeguodj.com`、`analyze.buxefaex.cc`、`adviser.tjecfkte.cc` | SPA 首页 + 加密 JSON API | **推荐**，与真果鉴一致 |
| **B. SSR 静态站** | `yeguo.mom`、`yeguo1.mom` | HTML 直出 + `/api/play/{id}/{ep}` | 可作备用，协议不同 |

**hg-dl 当前实现走形态 A**（`packages/core/hg_core/sources/yeguo.py`）。

形态 B 播放需带播放页 Referer + `window.__PLAY__.t` 令牌，部分集 VIP 会 `locked: true`；与 api.php 的 `episode_id` 模型不通用，**除非单独写 `YeguoMomSource`，否则不要混在一个 adapter 里**。

---

## 2. 形态 A：请求模型

### 2.1 入口与 API 根

- **页面入口（Referer/Origin）**：`https://analyze.buxefaex.cc/`（国内常能开）
- **API 根**：从 Nuxt 的 `__NUXT_DATA__` 里读 `apiBaseURL`，实测多为：

  ```
  https://www.yeguodj.com/api.php
  ```

- **实际调用 URL** = `{apiBaseURL}{route}`，例如：

  ```
  POST https://www.yeguodj.com/api.php/api/theater/exploreList
  GET  https://www.yeguodj.com/api.php/api/home/contentOptions?...
  ```

> 注意：不是 `POST body` 里带 path，而是 **path 拼在 api.php 后面**。

### 2.2 公共表单字段（每次必带）

```
bundleId=com.pwa.mater
version=1.3.2
oauth_type=web
language=zh
via=pwa
oauth_id=<随机 hex，会话内固定>
trace_id=<同 oauth_id>
token=
```

### 2.3 Header

```
User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 ...) Safari/604.1
Content-Type: application/x-www-form-urlencoded   # POST 时
Accept: application/json, text/plain, */*
Origin: https://analyze.buxefaex.cc
Referer: https://analyze.buxefaex.cc/
```

### 2.4 响应信封

```json
{
  "errcode": 0,
  "timestamp": 1791550566,
  "data": "<Base64 AES-CBC 密文>",
  "sign": "..."
}
```

解密后内层 JSON 形如：

```json
{
  "data": { ... 业务字段 ... }
}
```

adapter 取 **`payload["data"]`** 作为业务对象。

### 2.5 AES 密钥（2026-10 公开爬虫一致）

| 用途 | Key (16B) | IV (16B) |
|------|-----------|----------|
| API 响应 | `2acf7e91e9864673` | `1c29882d3ddfcfd6` |
| 封面/媒体（备用） | `f5d965df75336270` | `97b60394abc2fbe1` |

算法：AES-128-CBC，PKCS7，Base64 解码 `data` 字段。

**密钥轮换**：真果鉴会从 Nuxt chunk（如 `/_nuxt/CazmKgo-.js`）动态解析 `key/iv/sign_key`（`version:v0, mode:CBC, padding:Pkcs7`）。若固定 key 失效，应实现 **discoverConfiguration**  fallback（参考 `guoapp/native/core/provider_yeguo_client.go`）。

---

## 3. 业务接口一览

| 能力 | Method | Route | 主要参数 |
|------|--------|-------|----------|
| 分类/筛选项 | GET | `/api/home/contentOptions` | 仅公共字段 |
| 目录列表 | POST | `/api/theater/exploreList` | `page`, `limit`, 可选 `theme`/`setting`/… |
| 搜索 | POST | `/api/search/result` | `keyword`, `tab=video`, `page`, `limit` |
| 详情+分集 | POST | `/api/playlet/detail` | `video_id`, `id`, `episode_id=0`, `related_limit=0` |
| 播放地址 | POST | `/api/playlet/play` | `playlet_id`, `video_id`, `episode_id` |

### 3.1 分类（contentOptions）

`video_filter` 下有多维筛选，hg-dl 目前只用 **theme**：

```text
theme:7  → 野果原创
theme:8  → 真人短剧
theme:9  → 魔改漫剧
...
```

对外 slug 建议：`theme:7`（与 catalog category 一致）。

### 3.2 列表项字段 → Show

| API 字段 | Show 字段 |
|----------|-----------|
| `video_id` / `id` | `id`（native） |
| `title` | `title` |
| `cover` | `cover`（多为直链 HTTPS，无需解密） |
| `tags[]` | `tags` |
| `serialize_status` 1/2 | 连载 / 完结 |
| `play_count` | `hot` |

复合 ID：`yeguo:{video_id}`（见 `hg_core.ids.make_key`）。

### 3.3 分集（detail.episodes[]）

| 字段 | 说明 |
|------|------|
| `id` | **episode_id**（播放必用，不是集序号） |
| `sort` | 集号 1..N |
| `title` | 标题 |
| `is_adv` | 广告集，跳过 |

### 3.4 播放（playlet/play）

返回示例：

```json
{
  "playlet_id": "3395",
  "id": "186639",
  "episode_sort": 1,
  "video_url": "https://op.udhhzr.cn/.../index.m3u8?auth_key=...",
  "video_url_h265": "",
  "resolution": "1280x720"
}
```

- 优先 `video_url`，其次 `video_url_h265`
- 多为 **带 auth_key 的 m3u8/mp4**，有时效
- 部分 CDN 需正确 Referer（Origin 站根即可）

---

## 4. 域名池与健康检测

### 4.1 建议候选（2026-10）

**API 线（api.php，可互换）：**

```
https://www.yeguodj.com/api.php
https://yeguodj.com/api.php
https://analyze.buxefaex.cc/api.php
https://adviser.tjecfkte.cc/api.php
```

**页面 Referer 线：**

```
https://analyze.buxefaex.cc
https://yeguodj.com          # 常需代理
https://ygdj.org/az          # 跳转页，解析落地域名
```

**跳转发现（真果鉴做法）：**

- 访问 `https://ygdj7.com/` 解析 HTML/JS 里的 `*.buxefaex.cc` / `*.fzchosdi.cc`
- 邮件 `yeguodj@gmail.com` 可收最新国内地址（官方说明）

### 4.2 健康检测逻辑（`YeguoSource._call`）

1. 按 `lines[]` 顺序尝试
2. 成功：`errcode==0` 且 AES 解密成功 → 将该 line 置顶
3. 失败：试下一条；全部失败抛 `野果请求失败`
4. 可选：定时对 `/api/home/contentOptions` 探活（GET，轻量）

### 4.3 代理

- 本机 `http_proxy`（settings.json）对 `yeguodj.com` 直连失败时必需
- `analyze.buxefaex.cc` 在部分网络可直连

---

## 5. hg-dl 架构挂接点

与黄果/黄豆相同，走 **SourceRegistry 门面**：

```
Browse/Search/Detail/Play API
        ↓
SourceRegistry.catalog / search / detail / episodes / play_url
        ↓
YeguoSource
        ↓
www.yeguodj.com/api.php/...
```

### 5.1 已完成（后端）

| 文件 | 内容 |
|------|------|
| `packages/core/hg_core/sources/yeguo.py` | 完整 adapter（catalog/search/detail/episodes/play） |
| `packages/core/hg_core/ids.py` | `KNOWN_SOURCES` 含 `yeguo` |
| `packages/core/hg_core/sources/__init__.py` | 导出 `YeguoSource` |
| `backend/app/config.py` | `yeguo_api`、`sources_enabled` 默认含 yeguo |
| `backend/app/services/state.py` | 注册 `YeguoSource` |
| `backend/app/services/runtime_settings.py` | `yeguo_api` 持久化 |
| `backend/app/routes/api.py` | settings 返回 `yeguo_api` |
| `backend/app/services/hls_proxy.py` | Referer 识别 yeguodj/buxefaex |

### 5.2 待完成 / 待验证

| 项 | 说明 |
|----|------|
| `Browse.tsx` | `BrowseSource` 增加 `yeguo`；拉 `/api/config?source=yeguo` 填 theme 分类；`category` 映射 `theme:N` / `hot` |
| `Search.tsx` | `resolveSource` 支持 `yeguo`，返回路径 `/yeguo` |
| `ShowDetail.tsx` | 详情页返回键 `listBack=/yeguo` |
| `Settings.tsx` + `client.ts` | 增加「野果 API」输入框；`sources_enabled` 占位符含 yeguo |
| `styles.css` | `.src-badge.src-ye` 角标色（ShowGrid 已加 meta） |
| 冒烟测试 | `scripts/_probe_yeguo_full.py`；可选 `tests/test_yeguo.py` |
| 播放 E2E | `/api/play?id=yeguo:3395&ep=1` → `/api/hls` 代理 m3u8 |
| 密钥轮换 | 固定 key 失效时，从 Nuxt chunk 拉动态 key（见 §7） |

### 5.3 前端路由（已部分完成）

- `/yeguo` → `BrowsePage source="yeguo"`
- 底栏 Tab：黄果 | 黄豆 | **野果** | 我的
- 左右滑：`TAB_PATHS` 含 `/yeguo`

---

## 6. Browse 页分类映射

野果 **没有** 黄果式 `/api/tags`，也 **没有** 黄豆式 navBlock 子 Tab。

推荐 UI：

| 控件 | 行为 |
|------|------|
| 分类 chips | `全部` + 从 `contentOptions` 拉的 theme（`theme:7`…） |
| 设定 / 背景 / 时间 | 第二维筛选，来自 `video_filter.setting/background/time`，经 `tab=setting:23,time:1` 传给 catalog |
| 排序 | 映射 API `recommend`：`hot→1`，`new→2`（与 theme / 第二维可叠加） |
| 状态 | 本地 filter（完结/连载），与 API 无关 |
| 题材 | 不展示（野果无 tag API） |

```typescript
function yeguoCatalogKey(kind: string, sort: "hot" | "new") {
  if (kind && kind !== "all") return kind; // theme:7
  return sort; // hot | new
}
```

---

## 7. 进阶：动态密钥（真果鉴方案）

当 §2.5 固定 key 解密失败时：

1. GET `{site}/` 解析 `__NUXT_DATA__` → `apiBaseURL`
2. 找 `type=module` 的 `/_nuxt/*.js` 入口
3. 跟随 import 链读 chunk，正则匹配：

   ```javascript
   version: "v0", mode: "CBC", padding: "Pkcs7",
   key: "...", iv: "...", sign_key: "..."
   ```

4. `key/iv` 可能是 `104_172_...` 下划线编码字节
5. 响应还可校验 `sign`（SHA256+MD5，见 guoapp `yeguoResponseSignature`）

实现位置建议：`yeguo.py` 内 `_discover_access()`，缓存 1 小时。

---

## 8. 播放与 HLS 代理

```
客户端 → GET /api/play?id=yeguo:3395&ep=1
       → YeguoSource.play_url → m3u8 URL
       → 返回 /api/hls?url=...&ref=...
       → hls_proxy 带 Referer 拉 playlist/分片
```

注意：

- m3u8 的 `auth_key` 有过期时间，**不要长期缓存 play_url**
- CDN 域名（如 `op.udhhzr.cn`）与站点域名不同，Referer 仍用野果站根
- VIP/未授权集可能返回空 `video_url`（需在 UI 提示）

---

## 9. 配置示例

`data/settings.json`：

```json
{
  "hg_api": "https://huangguoai.com",
  "http_proxy": "http://127.0.0.1:7897",
  "huangdou_api": "https://lzlukvca.cc",
  "yeguo_api": "https://www.yeguodj.com/api.php",
  "sources_enabled": "huangguo,huangdou,yeguo"
}
```

---

## 10. 本地探测脚本

| 脚本 | 用途 |
|------|------|
| `scripts/probe_yeguo.py` | 多域名粗探 |
| `scripts/_probe_yeguo_full.py` | catalog → detail → play 全链路 |
| `scripts/_probe_yeguo_keys.py` | 验证 AES 固定 key |
| `scripts/_probe_yeguo_guoapp.py` | 模拟真果鉴 Nuxt 密钥发现 |

运行（需代理时确保 settings 或环境可用）：

```bash
cd hg-dl
python scripts/_probe_yeguo_full.py
```

---

## 11. 参考实现

- [guoapp / provider_yeguo.go](https://github.com/zhoufuweigg/guoapp/blob/main/native/core/provider_yeguo.go) — 业务路由与字段映射
- [guoapp / provider_yeguo_client.go](https://github.com/zhoufuweigg/guoapp/blob/main/native/core/provider_yeguo_client.go) — 加密、签名、域名发现
- hg-dl 内对照：`huangguo.py`（开放 JSON）、`huangdou.py`（Forward AES）

---

## 12. 实施顺序建议

1. **验证后端**：`YeguoSource` 冒烟（catalog/search/detail/play）
2. **Browse 野果 Tab**：分类 + 列表 + 详情 + 播放
3. **Settings**：`yeguo_api`、启用开关
4. **HLS 实测**：浏览器播一集，确认 auth_key 未过期
5. **域名池**：配置多 line + 自动 failover
6. **密钥轮换**（可选）：Nuxt chunk 动态 key
7. **形态 B**（可选）：单独 `yeguo.mom` SSR 源，不与 api.php 混用

---

## 13. 与用户提供信息的对应关系

| 用户文档 | 实测 |
|----------|------|
| `https://yeguodj.com/api.php` + AES | ✅ 固定 key 可解密，全链路通 |
| `/api/playlet/detail`、`/api/search/result` | ✅ 路径正确，拼在 api.php 后 |
| `analyze.buxefaex.cc` 备用 | ✅ 可开，api.php 同源响应 |
| `yeguo.mom` 另一套 | ⚠️ 见 §1 形态 B，非同一 API |
| 剧果 / 帝果 | 未纳入本次；需独立 adapter |
