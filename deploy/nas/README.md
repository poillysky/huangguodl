# NAS 部署黄果（huangguodl）

单一镜像：`poillysky/huangguodl`（Web + API 同端口 `8080`）。

## 需要的文件

把本目录拷到 NAS，例如：

```
/volume1/docker/huangguodl/
  docker-compose.yml
  .env                 ← 由 .env.example 复制改名
  data/
    downloads/         ← 或映射到媒体库路径
    config/
```

## 快速开始

```bash
cd /volume1/docker/huangguodl   # 按你的实际路径

cp .env.example .env
# 编辑 .env：HOST_DOWNLOADS / HOST_CONFIG / API_TOKEN / WEB_PORT

mkdir -p data/downloads data/config

docker compose pull
docker compose up -d

# 看日志
docker compose logs -f
```

浏览器打开：`http://NAS的IP:8080`

## 路径怎么填

| 变量 | 作用 | 示例 |
|------|------|------|
| `HOST_DOWNLOADS` | 剧集下载目录 | `/volume1/media/huangguo` |
| `HOST_CONFIG` | 任务/收藏/设置 JSON | `/volume1/docker/huangguodl/config` |
| `WEB_PORT` | 宿主机端口 | `8080` |
| `API_TOKEN` | 访问口令（可选） | 随机字符串 |

群晖 File Station / Container Manager 里路径一般以 `/volume1/...` 开头。

## 更新镜像

```bash
cd /volume1/docker/huangguodl
docker compose pull
docker compose up -d
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
