# Multi-camera People Counting Solution

[English](README.md) | [简体中文](README.zh-CN.md)

A multi-camera people counting and dashboard solution for reComputer RK3576. It runs YOLO11n RKNN inference on RTSP cameras and reCamera, applies centralized count calibration in the Node.js backend, persists statistics in MariaDB, and displays live regional, daily, weekly, monthly, yearly, and all-time traffic in a React dashboard. An optional local Qwen2.5-VL service can generate scene descriptions.

## Components

- `main.py`: multi-stream capture, YOLO inference, deduplication, and count reporting
- `vlm_analysis.py`: OpenAI-compatible client for the AI Lab VLM container
- `app/`: React dashboard, tRPC backend, database schema, and count calibration
- `recamera_puller.py`: live reCamera snapshot puller
- `watchdog.py`: detector heartbeat monitor
- `field_monitor.py`: PM2 and resource status sampler
- `debug_controller.py`: local-only diagnostics console

## Models

Model weights are not stored in this repository. Install them with reComputer AI Lab:

- Person detection: `YOLO11n`, exported for RK3576 as `model/yolo11n.rknn`
- Scene analysis: `Qwen2.5-VL-3B-W4A16`
- VLM image: `ghcr.io/seeed-projects/rk3576-qwen2.5-vl:3b-w4a16-latest`

See [docs/MODELS.md](docs/MODELS.md) for the validated filenames and API requirements.

## Quick Start

```bash
git clone https://github.com/xinjiechen727/mult_camera_people_counting_solution.git
cd mult_camera_people_counting_solution
cp config.example.json config.json
cp app/.env.example app/.env
cp .env.deploy.example .env.deploy
```

Replace every `CHANGE_ME` value and every documentation-only IP address in the local configuration files. Then follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) to install the AI Lab models, MariaDB, Python dependencies, Node.js dependencies, and PM2 services.

## Privacy and Security

- The tracked configuration contains only placeholders and RFC 5737 documentation addresses.
- `192.168.42.1` is retained only as the documented default direct-connect address for reCamera.
- `config.json`, `app/.env`, models, databases, logs, snapshots, photos, and videos are ignored by Git.
- MariaDB binds to `127.0.0.1:3306` by default.
- The diagnostics console binds to `127.0.0.1:8081` by default.
- Never commit production camera/NVR credentials, database dumps, access tokens, customer names, or site layouts.

## License

[MIT](LICENSE)
