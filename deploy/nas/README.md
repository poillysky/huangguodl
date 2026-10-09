# NAS 部署黄果（huangguodl）

单一镜像：`poillysky/huangguodl:v1.0.6`  
配置写在 `docker-compose.yml` 里，**不需要 `.env`**。

## 目录

```
/vol1/1000/Docker/huangguodl/
  docker-compose.yml
  config/              ← 任务 / 收藏 / 设置（自动写入）
  update.sh

下载：
/vol1/1000/Sync/115上传/黄果
```

## 启动

```bash
mkdir -p /vol1/1000/Docker/huangguodl/config
mkdir -p "/vol1/1000/Sync/115上传/黄果"
cd /vol1/1000/Docker/huangguodl

# 放入本目录的 docker-compose.yml 后：
docker compose pull
docker compose up -d
docker compose logs -f
```

浏览器：`http://NAS的IP:8080`

## 改配置

直接编辑 `docker-compose.yml` 里的 `environment` / `ports` / `volumes`，然后：

```bash
docker compose up -d
```

- `API_TOKEN`：访问口令，留空则不鉴权  
- `HTTP_PROXY`：容器访问上游用的代理（不要写 `127.0.0.1`）  
- `ports`：改宿主机端口，如 `"9000:8080"`

## 更新

```bash
cd /vol1/1000/Docker/huangguodl
sh update.sh
# 或：docker compose pull && docker compose up -d
```

镜像：https://hub.docker.com/r/poillysky/huangguodl

## 常见问题

**下载报 `ffmpeg 失败 code=-11`**  
旧镜像里 imageio 自带 ffmpeg 在部分 NAS CPU 上会段错误。拉含系统 ffmpeg 的新镜像：

```bash
cd /vol1/1000/Docker/huangguodl
docker compose pull && docker compose up -d
docker exec huangguodl ffmpeg -version
```

**上游超时**  
改 compose 里 `HTTP_PROXY`（容器可达地址，勿用 `127.0.0.1`）。
