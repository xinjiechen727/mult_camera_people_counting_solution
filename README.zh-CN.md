# 多摄像头人数统计解决方案

[English](README.md) | [简体中文](README.zh-CN.md)

面向 reComputer RK3576 的多摄像头人数检测与数据大屏方案。系统使用 YOLO11n RKNN 完成多路 RTSP/reCamera 人员检测，通过 Node.js 后端统一校准人数并写入 MariaDB，React 大屏实时展示区域、日、周、月、年及累计客流；可选接入本地 Qwen2.5-VL 生成场景描述。

## 主要组件

- `main.py`：多路视频采集、YOLO 推理、去重与人数上报
- `vlm_analysis.py`：调用 AI Lab VLM Docker 的 OpenAI 兼容接口
- `app/`：React 大屏、tRPC 后端、数据库结构与客流校准逻辑
- `recamera_puller.py`：reCamera 实时快照拉取
- `watchdog.py`：检测进程心跳守护
- `field_monitor.py`：PM2 与资源状态采样
- `debug_controller.py`：仅本机开放的调试控制台

## 模型

模型文件不存入 Git 仓库，统一通过 reComputer AI Lab 安装：

- 人员检测：`YOLO11n`，RK3576 RKNN 文件部署为 `model/yolo11n.rknn`
- 场景分析：`Qwen2.5-VL-3B-W4A16`
- VLM Docker 镜像：`ghcr.io/seeed-projects/rk3576-qwen2.5-vl:3b-w4a16-latest`

完整文件名和接口要求见 [docs/MODELS.md](docs/MODELS.md)。

## 快速开始

```bash
git clone https://github.com/xinjiechen727/mult_camera_people_counting_solution.git
cd mult_camera_people_counting_solution
cp config.example.json config.json
cp app/.env.example app/.env
cp .env.deploy.example .env.deploy
```

将本地配置文件中的所有 `CHANGE_ME` 和文档专用 IP 地址替换为实际部署值，然后按照 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 完成 AI Lab 模型、MariaDB、Python、Node.js 和 PM2 部署。

## 隐私与安全

- 仓库内配置只包含占位符和 RFC 5737 文档专用地址。
- `192.168.42.1` 仅作为 reCamera 官方默认直连地址保留。
- `config.json`、`app/.env`、模型、数据库、日志、快照、照片和视频均被 Git 忽略。
- MariaDB 默认仅绑定 `127.0.0.1:3306`。
- 调试控制台默认仅绑定 `127.0.0.1:8081`。
- 不要提交现场摄像头/NVR 密码、数据库备份、访问令牌、客户名称或现场平面图。

## 许可证

[MIT](LICENSE)
