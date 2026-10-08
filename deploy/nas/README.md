# NAS 部署黄果（huangguodl）

单一镜像：`poillysky/huangguodl`（Web + API 同端口 `8080`）。

## 需要的文件

推荐目录（已按本机 NAS 写好默认值）：

```
/vol1/1000/Docker/huangguodl/
  docker-compose.yml
  .env                 ← 由 .env.example 复制改名
  config/              ← 任务 / 收藏 / 设置
  update.sh

下载目录（115 同步）：
/vol1/1000/Sync/115上传/黄果
```

`restart: always`（开机与崩溃都会拉起）。

## 快速开始

```bash
cd /vol1/1000/Docker/huangguodl

cp .env.example .env
# 需要鉴权时再改 API_TOKEN；路径默认已可用

mkdir -p /vol1/1000/Docker/huangguodl/config
mkdir -p "/vol1/1000/Sync/115上传/黄果"

docker compose pull
docker compose up -d

docker compose logs -f
```

浏览器打开：`http://NAS的IP:8080`

## 路径

| 变量 | 作用 | 默认 |
|------|------|------|
| `HOST_DOWNLOADS` | 剧集下载 | `/vol1/1000/Sync/115上传/黄果` |
| `HOST_CONFIG` | 任务/收藏/设置 | `/vol1/1000/Docker/huangguodl/config` |
| `WEB_PORT` | 宿主机端口 | `8080` |
| `API_TOKEN` | 访问口令（可选） | 空 |

## 更新镜像

```bash
cd /vol1/1000/Docker/huangguodl
sh update.sh
# 或：docker compose pull && docker compose up -d
```

镜像由 GitHub Actions 推到 Docker Hub：  
https://hub.docker.com/r/poillysky/huangguodl

## 反代（可选）

若用 NPM / 群晖反代 / Cloudflare Tunnel，指到 `http://127.0.0.1:8080` 即可。  
需支持 WebSocket/SSE（任务进度）；超时建议 ≥ 60s。

## 常见问题

**拉不到镜像**  
NAS 能访问 Docker Hub；或在能联网的机器 `docker pull poillysky/huangguodl:latest` 后导出导入。

**上游 API / 封面超时**  
在 `.env` 填容器可达的 `HTTP_PROXY`（不要用 `127.0.0.1`，用 NAS 网关或 docker bridge 网关 IP）。

**权限**  
下载目录对容器可写；群晖若遇权限问题，可在共享文件夹给 `docker` 用户读写，或先用 `chmod`/`chown` 放开测试。
