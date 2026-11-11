# AI Lab模型要求

本仓库不分发模型权重。请在reComputer AI Lab中按设备平台安装模型，或使用AI Lab教程生成的Docker部署命令。

## YOLO人员检测

- 模型：YOLO11n person detection
- 平台：RK3576
- 运行时：RKNN Toolkit Lite 2
- 项目期望路径：`model/yolo11n.rknn`
- 输入尺寸：`640 x 640`

AI Lab安装完成后，将导出的RKNN文件链接或放置到上述路径。不要把模型提交到Git。

## 本地VLM

当前已验证的AI Lab Docker配置：

```text
模型：Qwen2.5-VL-3B-W4A16
镜像：ghcr.io/seeed-projects/rk3576-qwen2.5-vl:3b-w4a16-latest
LLM：Qwen2.5-VL-3B-W4A16_LEVEL1_RK3576.rkllm
Vision：Qwen2.5_VL_3B_VISION_RK3576.rknn
容器名：qwen-vl
网络：host
重启策略：unless-stopped
API：http://127.0.0.1:8002/v1
```

部署后检查：

```bash
curl http://127.0.0.1:8002/v1/models
```

项目请求的模型标识为 `rkllm-vision`。AI Lab生成的容器需要访问RK3576的NPU、DRM、DMA heap和Mali设备，请使用AI Lab教程提供的Docker参数，不要自行删减设备映射。
