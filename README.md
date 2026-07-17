# WSS Recorder ARM

ARM64 Linux 友好的中移物联网（qly.cmviot.cn）摄像头 WSS 录制服务，带网页控制台。

## 功能

- Web 控制台（密码登录）
- Ticket 有效期展示 / 过期重输 / 可选 token_cache 自动续票（**无 Playwright**）
- WebSocket 分片录制 CFLV → 后台转 MP4
- 近实时预览（最新完成分片）
- 录像库在线播放 / 下载
- WebDAV 定时批量同步
- Docker multi-arch（arm64 / amd64）

## 一键安装（ARM64 Linux 推荐）

在已解压/克隆的项目根目录执行（需 root）：

```bash
chmod +x install.sh
sudo ./install.sh
```

脚本会：检测架构 → 安装 Docker/Compose（若缺失）→ 同步到 `/opt/wss-recorder-arm` → 生成随机控制台密码与 session 密钥 → 构建并启动容器 → **终端打印关键信息**，并写入 `CREDENTIALS.txt`。

可选环境变量：

```bash
sudo WSS_CONSOLE_PASSWORD='mypass' \
     WSS_DEVICE_ID='14eaa12a154e' \
     WSS_PORT=8080 \
     INSTALL_DIR=/opt/wss-recorder-arm \
     NON_INTERACTIVE=1 \
     ./install.sh
```

| 变量 | 说明 | 默认 |
|------|------|------|
| `WSS_CONSOLE_PASSWORD` | 控制台密码 | 随机生成 |
| `WSS_SESSION_SECRET` | Cookie 签名密钥 | 随机生成 |
| `WSS_DEVICE_ID` | 设备 SN | `14eaa12a154e` |
| `WSS_PORT` | 宿主机端口 | `8080` |
| `INSTALL_DIR` | 安装目录 | `/opt/wss-recorder-arm` |
| `SKIP_DOCKER_INSTALL` | 设为 `1` 则不装 Docker | 关闭 |
| `NON_INTERACTIVE` | 设为 `1` 跳过确认 | 关闭 |
| `IN_PLACE` | 设为 `1` 原地安装 | 关闭 |

部署成功后输出示例：

```
访问地址     : http://192.168.x.x:8080
控制台密码   : <生成或指定的密码>
安装目录     : /opt/wss-recorder-arm
密钥备份     : /opt/wss-recorder-arm/CREDENTIALS.txt
```

## 快速开始（本机开发）

```bash
cd wss-recorder-arm
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy config.example.yaml config.yaml   # 或 cp
set WSS_CONSOLE_PASSWORD=yourpassword  # Linux: export

# 需要系统已安装 ffmpeg
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

浏览器打开 http://127.0.0.1:8080 ，默认密码见 `config.example.yaml` / 环境变量。

## Docker（手动）

```bash
# 准备数据目录
mkdir -p data
cp config.example.yaml data/config.yaml

export WSS_CONSOLE_PASSWORD=yourpassword
docker compose up -d --build
```

ARM64：

```bash
docker buildx build --platform linux/arm64 -t wss-recorder-arm:latest --load .
```

## 获取 Ticket

1. 浏览器打开 https://qly.cmviot.cn/normal/hubs/home 并登录
2. F12 → Network → WS → 播放摄像头
3. 找到 `wss://...?ticket=xxxx`，复制 ticket
4. 控制台 **Ticket** 页粘贴保存
5. **Dashboard** 点「开始录制」

可选：导入旧项目 `token_cache.json` 后点「自动续票」。

## 配置

| 环境变量 | 说明 |
|----------|------|
| `WSS_CONSOLE_PASSWORD` | 控制台密码 |
| `WSS_SESSION_SECRET` | Cookie 签名密钥 |
| `WSS_DEVICE_ID` | 设备 SN |
| `WSS_OUTPUT_DIR` | 录像目录 |
| `WSS_SEGMENT_DURATION` | 分片秒数（默认 300） |
| `WSS_WEBDAV_PASSWORD` | WebDAV 密码 |
| `WSS_CONFIG` | 配置文件路径 |

完整项见 `config.example.yaml`。

## 目录

```
data/
  app.db
  token_cache.json
  recordings/YYYY-MM-DD/HH/stream_*.mp4
```

## 注意

- 同一设备同时仅一路播放连接
- 视频为 HEVC，建议 Chrome/Edge；Safari 可能无法内联播放
- 服务器不运行浏览器登录；token 过期请重新导入缓存或手输 ticket
- 预览延迟约等于分片时长

## 从旧项目迁移

可将 `wss-recorder/token_cache.json` 复制到 `data/token_cache.json`，或在控制台导入 JSON。  
历史 MP4 可用 `scripts/import_legacy_recordings.py` 扫入数据库。

## 许可

仅供个人学习使用。
