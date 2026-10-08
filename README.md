# hg-dl — 黄果剧集下载器

从黄果 API 拉剧集目录，本地批量下载。CLI 仍是**纯标准库**；可部署 Web 为 FastAPI + React。

```
网络 API ──► 拉目录 / 搜索 ──► 选剧 ──► 拉集数列表 ──► 封面（过解密代理）
                                          │
                              比对本地已有集数（可选）
                                          │
                              缺哪集下哪集 ──► ffmpeg(HLS) → .mp4 + poster/nfo
```

## 目录

```
hg-dl/
  hg_dl.py              # CLI 入口（再导出核心 API）
  packages/core/hg_core # 共享下载核心
  backend/              # FastAPI
  frontend/             # Vite + React
  tools/ensure_ffmpeg.py  # 检查 pip 自带的 ffmpeg
  tests/                # mock_api + 单元/冒烟测试
  legacy/               # 旧版标准库 Web UI（web.py）
  docker-compose.yml
  nginx.conf
  .env.example
```

## ffmpeg（pip 依赖，适合 NAS）

官网片源是 **AES-128 HLS（m3u8）**，不能当普通文件直存。  
**不要**在 NAS/本机单独装 ffmpeg；用 Python 包装带的二进制：

```bash
pip install -r backend/requirements.txt   # 含 imageio-ffmpeg
python tools/ensure_ffmpeg.py             # 确认可用
```

Docker 构建时同样 `pip install` 并预热二进制，容器内不依赖宿主机。

## 快速开始

```bash
# 看看热门里有什么
python hg_dl.py list

# 看某部剧有几集
python hg_dl.py show "都市逆袭传"

# 先看下载计划，不动文件
python hg_dl.py get "都市逆袭传"

# 确认后真下
python hg_dl.py get "都市逆袭传" --yes

# 交互式浏览：翻目录 → 选剧 → 选集
python hg_dl.py interactive

# 下正片 + 封面
python hg_dl.py get "都市逆袭传" --yes

# 只批量下封面
python hg_dl.py cover --category hot --limit 24 --yes
```

## 命令

| 命令 | 作用 |
|---|---|
| `list` | 拉远端目录，支持分类 / 搜索 / 翻页 |
| `show <剧名>` | 看集数列表，不下载 |
| `get <剧名>` | 下载（默认只打印计划） |
| `cover [剧名]` | 只下载封面；省略剧名则批量下目录页 |
| `interactive` | 交互式浏览并下载 |

## 常用参数

```
--api URL          API 地址，默认 https://huangguoai.com
--out DIR          下载输出目录，默认当前目录
--category KEY     分类，见下表
--page N / --page-size N
--keyword WORD     list 时改为搜索
--ep SPEC          指定集：1,3,5 或 1-10
--scan-dir DIR     扫描此本地目录，比对已有集数
--missing-only     只下本地没有的集
--yes              跳过确认，直接下载
--workers N        并发数，默认 3（别调太高）
--retries N        失败重试次数，默认 3
--refresh          忽略本地缓存，重新拉目录

--cover-proxy URL  封面解密代理，默认 https://ai.wulii.de5.net（留空直接取原图）
--cover-token TOK  封面代理 Token
--no-cover         不下载封面（get 默认下载）
```

分类：`hot` `new` `rank` `ai-duanju` `ai-manju` `ai-huanlian` `ai-mogai`
题材 tag：`dushi` `xiandai` `xiaoyuan` `zhichang` `haomen` `hougong` `shunv`
`nianxia` `jiedi` `muzi` `dananzhu` `danvzhu` `nixi` `quanmou` `bazong`
`yulequan` `mingxing` `tianchong` `gufeng` `xianxia` `qihuan` `xuanhuan`
`chaonengli` `xitong` `naodong` `youxi` `huangdao` `tongshi` `lvmao` `ntr` `luanlun`

## 封面

封面走你 Widget 里那套 CF 解密代理，逻辑一致：加密地址 → 拼 `url` + `token` → 代理解密。

```bash
# 下正片 + 封面（get 默认就带封面）
python hg_dl.py get "都市逆袭传" --yes

# 不要封面
python hg_dl.py get "都市逆袭传" --yes --no-cover

# 只要封面
python hg_dl.py cover "都市逆袭传" --yes

# 批量把热门页封面全下下来
python hg_dl.py cover --category hot --limit 24 --yes

# 代理不通时直接取原图
python hg_dl.py cover "都市逆袭传" --yes --cover-proxy ""
```

Emby 结构（每部剧一个文件夹）：

```
downloads/
  剧名/
    poster.jpg
    tvshow.nfo
    Season 01/
      poster.jpg
      season.nfo
      剧名 - S01E01.mp4
      剧名 - S01E01.nfo
      ...
```

封面失败**不会阻断正片下载**。另外：
- 图片请求用独立的 `Accept: image/*`（不复用 JSON 接口的头，否则某些代理会返错内容）
- 代理返回 JSON/HTML 时识别为失败并打印原因，**不会把错误响应存成 .jpg**
- HTTP 错误会读响应体，把代理给的错误信息（如 `invalid token`）透出来，而不是只显示 403

## 典型用法：只补缺集

```bash
# 扫描已有剧集目录，只下缺失的那几集
python hg_dl.py get "都市逆袭传" --scan-dir "D:\剧集" --missing-only --yes --out "D:\剧集"
```

去重有三重：本地已有集、输出目录里已落地的文件（`.part` 算未完成）、`--ep` 过滤。

## 可靠性设计

- **断点续传**：`.part` 文件 + HTTP `Range`。服务端不认 Range（返回 200）时自动从头重下。
- **并发**：线程池，默认 3。单个失败不影响其他。
- **重试**：指数退避（2s→4s→8s 封顶）。
- **计划表不撒谎**：`build_jobs` 会同时检查 `--scan-dir` 和输出目录，已存在的集直接不列进待办。
- **匹配有阈值**：默认 0.62，低于阈值宁可不匹配，也不给你错的一部。
- **附加接口失败不拖垮主流程**：详情接口 404 时降级用列表里的 `episode_count` 造占位集数；封面 403/404 时只警告，正片照下。
- **缓存**：CLI 仍把 `.hg_cache.json` 放在 `--out` 目录；Web 把缓存和运行时配置放在 `data/`（`cache.json` / `settings.json`），`--refresh` 强制失效。老缓存缺新字段也兼容（`show_from_dict`）。
- **默认 dry-run**：不加 `--yes` 只打印计划，一个字节都不写。

## Web / PWA / 部署

新栈：`backend/`（FastAPI）+ `frontend/`（Vite/React PWA）。`legacy/` 已弃用。

目录约定（相对仓库根，不跟进程 cwd 走）：

- `downloads/<剧名>/Season 01/`：Emby 可读（`poster.jpg`、`tvshow.nfo`、分集 nfo）
- `data/settings.json`：页面「设置」里的代理、上游、封面 token（重启保留）
- `data/cache.json`：目录/搜索缓存
- `data/tasks.json`：下载任务列表（重启保留；进行中的任务会回到「排队」）

### 开发一键启动

```powershell
# Windows：清 8000/5173 后开两个终端
.\scripts\dev.ps1
```

```bash
# Linux / macOS / NAS
chmod +x scripts/dev.sh && ./scripts/dev.sh
```

或手动：

```bash
# 后端（务必 reload packages/core）
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 \
  --reload-dir . --reload-dir ../packages/core

# 前端
cd frontend && npm install && npm run dev -- --host 0.0.0.0
```

- 本机：前端 `http://127.0.0.1:5173`，`/api` 由 Vite 反代到 `8000`
- 外网域名访问 Vite 时，把 Host 加进 `frontend/vite.config.ts` 的 `allowedHosts`（已含 `e.605081.xyz`）
- **代理**：上游 API / 封面走 `HTTP_PROXY`（设置页或 `.env`）；**媒体 CDN / HLS ffmpeg 不走 HTTP 代理**，避免白名单拦流
- **PWA**：生产构建后注册 `sw.js`；开发模式会卸载旧 SW，避免主屏幕白屏。只缓存壳（`/`、manifest、图标），不缓存 `/api` 与哈希资源

```bash
# Docker 本地构建
docker compose up -d --build
# http://localhost:8080

# NAS：见 deploy/nas/（compose 内写死路径，无需 .env）
# cd deploy/nas && docker compose pull && docker compose up -d
```


并发相关环境变量（见 `.env.example`）：`WORKERS`（单任务线程池）、`MAX_PARALLEL_TASKS`（同时进行的剧）、`MAX_GLOBAL_WORKERS`（跨任务分集下载总闸）。

## 测试

```bash
python tests/test_hg_dl.py      # 核心单元测试
python tests/cli_smoke.py       # CLI 端到端
python tests/test_api_smoke.py  # FastAPI 冒烟
python legacy/test_web.py       # 旧版 web.py（已弃用，仅对照）
```

`tests/mock_api.py` 起本地假 API，结构对齐 Widget 字段；
片源/封面为确定性伪数据。**测试不联网、不下载真实内容。**

## 已知限制

- `is_finished` / 字段名按 Widget 脚本推断，真实接口若有出入需微调 `HGApi._to_show`。
- `/api/ranks/hot` 取不到时自动回退到 `/api/videos`。
- 播放地址若有时效，`play_url` 每集现取，不走缓存。
- 封面统一存 `.jpg`（不按实际格式选扩展名）。
- `ai-huanlian` / `ai-mogai` 在通用目录结果上按标题关键词过滤。