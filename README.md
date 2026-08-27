# RSS Notify

一个轻量级 RSS/Atom 关键词监控和通知服务，基于 Flask + SQLite + 原生前端。适合部署在 VPS/NAS 上，用 Docker Compose 持久化运行。

## 功能

- RSS/Atom 订阅源管理
- 白名单/黑名单关键词匹配
- 命中关键词标签展示
- Apprise 通知推送（Telegram、Gotify 等 Apprise 支持的 URL 均可）
- 手动轮询、手动推送
- 消息保留数量清理
- 单用户登录与账户密码修改
- SQLite 数据库存储，`./data` 目录持久化

## 快速部署

### 方式 A：源码构建部署

#### 1. 克隆项目

```bash
git clone https://github.com/zcoal/rss-notify.git
cd rss-notify
```

#### 2. 配置环境变量

```bash
cp .env.example .env
nano .env
```

至少修改：

```env
ADMIN_USER=admin
ADMIN_PASS=change-this-password
APP_SECRET_KEY=change-this-to-a-long-random-string
APP_PORT=8000
```

建议生成一个随机 `APP_SECRET_KEY`：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

#### 3. 启动

```bash
docker compose up -d --build
```

访问：

```text
http://服务器IP:8000
```

如果修改了 `APP_PORT`，使用对应端口。

#### 4. 验证

```bash
docker compose ps
curl http://127.0.0.1:${APP_PORT:-8000}/api/health
```

正常返回：

```json
{"ok": true}
```

### 方式 B：docker部署

```yaml
services:
  rss-notify:
    image: ghcr.io/zcoal/rss-notify:latest
    container_name: rss-notify
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      ADMIN_USER: admin
      ADMIN_PASS: change-this-password
      APP_SECRET_KEY: change-this-to-a-long-random-string
      FEED_TIMEOUT: 30
      TZ: Asia/Shanghai
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

建议仍然用 `.env` 管理密码和密钥。项目里也提供了 `docker-compose.image.yml` 模板，记得把里面的镜像名改成你的真实 GitHub 用户名/仓库名。

启动：

```bash
docker compose up -d
```

更新：

```bash
docker compose pull
docker compose up -d
```

## 反向代理

可以用 Nginx/OpenResty/Caddy 反代到容器暴露的本地端口，例如：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 通知 URL

通知基于 [Apprise](https://github.com/caronc/apprise)。在订阅源编辑框中填写“Apprise 通知 URL”，每行一个。

示例占位：

```text
tgram://bot-token/chat-id
gotify://host/token
```

## 数据目录

运行数据默认保存在：

```text
./data/
├── rss_notify.db
└── config.json
```

备份：

```bash
tar czf rss-notify-data-backup.tar.gz data/
```

恢复：

```bash
tar xzf rss-notify-data-backup.tar.gz
```

## 更新部署

```bash
git pull
docker compose up -d --build
```

如果只改了 `.env`，建议强制重建容器环境：

```bash
docker compose up -d --force-recreate
```
