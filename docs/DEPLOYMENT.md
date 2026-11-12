# 部署指南

## 1. 环境要求

- reComputer RK3576，系统时区 `Asia/Shanghai`
- Docker及Docker Compose
- reComputer AI Lab
- Node.js 20、npm、PM2
- Python 3.11及RKNN Toolkit Lite 2运行环境
- 摄像头/NVR与设备网络互通

RTC电池必须安装。无RTC电池时，断电重启可能先使用错误日期，NTP校时后产生日期跳转并污染日/周/月统计。

## 2. 获取源码和配置

```bash
sudo mkdir -p /data/seeed
sudo chown "$USER:$USER" /data/seeed
git clone https://github.com/xinjiechen727/mult_camera_people_counting_solution.git /data/seeed/demo
cd /data/seeed/demo
cp config.example.json config.json
cp app/.env.example app/.env
cp .env.deploy.example .env.deploy
```

编辑 `config.json`，配置每路摄像头IP、区域名、模式、RTSP路径、NVR账号和密码。真实配置不会被Git跟踪。

## 3. 安装AI模型

通过reComputer AI Lab安装 [MODELS.md](MODELS.md) 中的YOLO11n和Qwen2.5-VL模型。完成后确认：

```bash
mkdir -p /data/seeed/demo/model
test -f /data/seeed/demo/model/yolo11n.rknn
curl http://127.0.0.1:8002/v1/models
```

VLM不是必需项；不部署VLM时人数检测和客流大屏仍可运行，但场景描述不会更新。

## 4. 启动MariaDB

先修改 `.env.deploy` 中的密码：

```bash
docker compose --env-file .env.deploy -f deploy/docker-compose.db.yml up -d
```

在 `app/.env` 中填写：

```dotenv
APP_ID=local-dashboard
APP_SECRET=请生成随机长字符串
DATABASE_URL=mysql://people_app:CHANGE_ME_APP@127.0.0.1:3306/people_counting
```

## 5. 安装依赖和初始化数据库

```bash
cd /data/seeed/demo
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -r requirements.txt

cd app
npm ci
npm run db:push
npx tsx db/seed.ts
npm run build
```

`db:push`创建应用表；`db/seed.ts`初始化区域。累计客流基准属于现场业务数据，必须在部署验收时单独设置，不能写进公共仓库。

## 6. 启动并配置开机自启

```bash
cd /data/seeed/demo
pm2 start ecosystem.config.cjs
pm2 save
pm2 startup systemd -u "$USER" --hp "$HOME"
```

执行 `pm2 startup` 输出的sudo命令，然后确认：

```bash
pm2 status
systemctl is-enabled pm2-$USER
systemctl is-enabled docker
curl http://127.0.0.1:3000/api/trpc/ping?input=%7B%22json%22%3Anull%7D
```

调试控制台默认仅监听 `127.0.0.1:8081`。需要远程调试时应使用SSH端口转发，不要直接暴露到公网：

```bash
ssh -L 8081:127.0.0.1:8081 user@device
```

## 7. 验收

```bash
pm2 logs yolo-detector --lines 100
pm2 logs people-counting-dashboard --lines 100
curl http://127.0.0.1:3000/api/trpc/footfall.stats?input=%7B%22json%22%3Anull%7D
```

必须确认：

- 摄像头帧持续更新，RTSP没有持续超时
- 原始人数增长，校准人数不倒退且不超过350
- 今日总人数严格等于各区域人数之和
- 周、月、年、总客流只按校准增量增长一次
- 重启后数据库、每日比例和累计基准不丢失


### PM2 v7 systemd兼容配置

部分PM2 v7环境生成的systemd单元使用 `Type=forking` 和 `PIDFile`，但PM2守护进程没有及时生成PID文件时，systemd会将已经在线的进程误判为 `Result: protocol`，并反复执行 `pm2 resurrect`。仓库提供了经过现场验证的 `Type=oneshot` 单元：

```bash
sudo install -o root -g root -m 0644 \
  deploy/pm2-seeed.service /etc/systemd/system/pm2-seeed.service
sudo systemctl daemon-reload
sudo systemctl enable --now pm2-seeed.service
systemctl is-active pm2-seeed.service
pm2 status
```

该单元会等待本机MariaDB端口就绪，再恢复 `pm2 save` 保存的进程列表。若部署用户不是 `seeed`，需要同步修改单元中的 `User`、`PM2_HOME` 和NVM路径。

设备根分区必须保留可写空间；磁盘达到100%时PM2无法写入状态和日志，检测、大屏及跨日统计都会停止。建议部署监控至少在剩余空间低于10%时告警，并定期检查：

```bash
df -h /
du -sh ~/.pm2/logs ~/.vscode-server* /data/seeed/demo/field_test_log.jsonl
```
