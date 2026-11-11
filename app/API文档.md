# 示例站点人流数据大屏 - 数据接口文档

> 本文档供第三方系统接入使用，包含数据大屏所有模块的数据接口定义、请求格式、响应格式和示例。

---

## 一、接口概览

| 模块 | 功能 | 接口路径 | 类型 |
|------|------|----------|------|
| 监控画面 | 实时视频流 | iframe: `http://192.168.42.1/#/dashboard` | 嵌入 |
| 监控画面 | 当前人数 | `footfall.current` | Query |
| VLM分析 | 上报分析日志 | `vlm.report` | Mutation |
| VLM分析 | 批量上报日志 | `vlm.reportBatch` | Mutation |
| VLM分析 | 获取日志列表 | `vlm.latest` | Query |
| 热力图 | 获取区域数据 | `footfall.rooms` | Query |
| 热力图 | 获取统计汇总 | `footfall.stats` | Query |
| 客流趋势 | 获取24小时趋势 | `footfall.hourlyTrend` | Query |
| 到访时段 | 获取24小时分布 | `footfall.hourlyTrend` | Query |
| 区域排行 | 获取区域数据 | `footfall.rooms` | Query |
| 综合面板 | 获取区域数据 | `footfall.rooms` | Query |

> **接口基础路径**: `http://<服务器地址>/api/trpc/`
> **Content-Type**: `application/json`

---

## 二、数据库表结构

### 2.1 人流记录表 (person_flow_records)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint unsigned | 自增主键 |
| count | int | 当前人数 |
| event | varchar(50) | 事件类型: `person_count_changed` / `person_entered` / `person_left` |
| timestamp | timestamp | 记录时间 |
| room_name | varchar(100) | 区域名称(可选) |
| person_ids | json | 追踪的人员ID列表(可选) |
| confidence | float | AI置信度 0-1(可选) |

### 2.2 区域表 (rooms)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint unsigned | 自增主键 |
| name | varchar(100) | 区域名称 |
| floor | int | 楼层(默认1) |
| max_capacity | int | 最大容量 |
| x_position | float | X坐标(热力图位置) |
| y_position | float | Y坐标(热力图位置) |
| width | float | 宽度(热力图尺寸) |
| height | float | 高度(热力图尺寸) |
| current_count | int | 当前人数 |
| label | varchar(50) | 显示标签 |

**17个预置区域**: Area 01、Area 02、Area 03、Area 04、Area 05、Area 06、Area 07、Area 08、Area 09、Area 10、Area 11、Area 12、Area 13、Area 14、Area 15、Area 16、Area 17

### 2.3 VLM分析日志表 (vlm_logs)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint unsigned | 自增主键 |
| event_type | varchar(50) | 事件类型: `info`/`detect`/`analyze`/`count`/`warning` |
| message | varchar(1000) | 分析消息内容 |
| timestamp | timestamp | 记录时间 |
| room_name | varchar(100) | 关联区域(可选) |
| person_id | int | 追踪人物ID(可选) |
| confidence | float | AI置信度 0-1(可选) |
| metadata | json | 扩展字段(可选) |

### 2.4 事件日志表 (event_logs)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint unsigned | 自增主键 |
| event_type | varchar(50) | 事件类型 |
| message | varchar(500) | 事件消息 |
| timestamp | timestamp | 记录时间 |
| metadata | json | 扩展数据(可选) |

### 2.5 每日统计表 (daily_stats)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint unsigned | 自增主键 |
| date | date | 日期 |
| total_visitors | int | 总访客数 |
| peak_count | int | 峰值人数 |
| peak_time | timestamp | 峰值时间 |
| average_count | float | 平均人数 |

---

## 三、接口详情

### 3.1 footfall.current - 获取当前人数

获取最新的人流记录，包括当前人数和最后更新时间。

**请求方式**: `GET /api/trpc/footfall.current`

**请求参数**: 无

**响应格式**:
```json
{
  "result": {
    "data": {
      "count": 42,
      "lastUpdate": "2026-05-29T14:30:00.000Z",
      "event": "person_count_changed"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| count | number | 当前检测到的人数 |
| lastUpdate | string (ISO 8601) | 最后更新时间 |
| event | string | 最近事件类型 |

---

### 3.2 footfall.report - 上报人流数据

上报一次人数变化事件，系统会自动记录并生成事件日志。

**请求方式**: `POST /api/trpc/footfall.report`

**请求体**:
```json
{
  "count": 12,
  "event": "person_count_changed",
  "timestamp": "2026-05-29T14:30:00.000Z",
  "roomName": "Area 04",
  "personIds": [1, 2, 3],
  "confidence": 0.95
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| count | number(int) | 是 | 当前人数，>=0 |
| event | string | 是 | 枚举: `person_count_changed`, `person_entered`, `person_left` |
| timestamp | string(ISO 8601) | 否 | 事件时间，不传则使用服务器当前时间 |
| roomName | string | 否 | 区域名称 |
| personIds | number[] | 否 | 追踪到的人员ID列表 |
| confidence | number | 否 | AI置信度 0-1 |

**响应格式**:
```json
{
  "result": {
    "data": {
      "success": true
    }
  }
}
```

---

### 3.3 footfall.trend - 获取趋势数据

获取最近N小时的趋势数据，按5分钟聚合。

**请求方式**: `GET /api/trpc/footfall.trend`

**查询参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| hours | number | 否 | 1 | 查询小时数，范围 1-168 |

**请求示例**: `GET /api/trpc/footfall.trend?input={"hours":2}`

**响应格式**:
```json
{
  "result": {
    "data": [
      { "time": "14:00", "count": 12 },
      { "time": "14:05", "count": 15 },
      { "time": "14:10", "count": 18 }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| time | string(HH:MM) | 时间段 |
| count | number | 该时间段的人数 |

---

### 3.4 footfall.hourlyTrend - 获取今日24小时客流分布

**这是核心接口，模块4（客流趋势）和模块5（到访时段分布）都使用此接口。**

获取今日00:00到当前时间的小时级客流汇总，24个时间点（00:00-23:00）。

**请求方式**: `GET /api/trpc/footfall.hourlyTrend`

**请求参数**: 无

**响应格式**:
```json
{
  "result": {
    "data": [
      { "hour": "00:00", "count": 2 },
      { "hour": "01:00", "count": 1 },
      { "hour": "02:00", "count": 0 },
      { "hour": "03:00", "count": 0 },
      ...,
      { "hour": "22:00", "count": 8 },
      { "hour": "23:00", "count": 3 }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| hour | string(HH:00) | 小时标签 |
| count | number | 该小时的总客流量（SUM(count)） |

> 注意：如果某小时没有数据，count 返回 0。

---

### 3.5 footfall.rooms - 获取所有区域数据

**这是核心接口，模块3（热力图）、模块6（区域排行）、模块7（综合面板）都使用此接口。**

获取所有17个区域的空间信息和当前人数。

**请求方式**: `GET /api/trpc/footfall.rooms`

**请求参数**: 无

**响应格式**:
```json
{
  "result": {
    "data": [
      {
        "id": 1,
        "name": "Area 01",
        "floor": 1,
        "maxCapacity": 15,
        "xPosition": 0.02,
        "yPosition": 0.04,
        "width": 0.16,
        "height": 0.17,
        "currentCount": 3,
        "label": "Area 01"
      },
      ...
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 区域ID |
| name | string | 区域名称 |
| floor | number | 所在楼层 |
| maxCapacity | number | 最大容量 |
| xPosition | number | 热力图X坐标(0-1相对值) |
| yPosition | number | 热力图Y坐标(0-1相对值) |
| width | number | 热力图宽度(0-1相对值) |
| height | number | 热力图高度(0-1相对值) |
| currentCount | number | 当前人数（外部系统需通过 updateRoom 更新） |
| label | string | 显示标签 |

---

### 3.6 footfall.updateRoom - 更新区域人数

更新指定区域的当前人数，用于外部计数系统同步数据到热力图。

**请求方式**: `POST /api/trpc/footfall.updateRoom`

**请求体**:
```json
{
  "id": 4,
  "currentCount": 12
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number(int) | 是 | 区域ID(rooms表的id) |
| currentCount | number(int) | 是 | 当前人数，>=0 |

**响应格式**:
```json
{
  "result": {
    "data": {
      "success": true
    }
  }
}
```

**17个区域ID对照表**:
| ID | 区域名称 | 最大容量 |
|----|---------|---------|
| 1 | Area 01 | 20 |
| 2 | Area 02 | 20 |
| 3 | Area 03 | 20 |
| 4 | Area 04 | 20 |
| 5 | Area 05 | 20 |
| 6 | Area 06 | 20 |
| 7 | Area 07 | 20 |
| 8 | Area 08 | 20 |
| 9 | Area 09 | 20 |
| 10 | Area 10 | 20 |
| 11 | Area 11 | 20 |
| 12 | Area 12 | 20 |
| 13 | Area 13 | 20 |
| 14 | Area 14 | 20 |
| 15 | Area 15 | 20 |
| 16 | Area 16 | 20 |
| 17 | Area 17 | 20 |

---

### 3.7 footfall.stats - 获取统计汇总

获取总访客数、本年、本月、本周的客流统计。

**请求方式**: `GET /api/trpc/footfall.stats`

**请求参数**: 无

**响应格式**:
```json
{
  "result": {
    "data": {
      "totalVisitors": 15234,
      "yearVisitors": 8432,
      "monthVisitors": 2156,
      "weekVisitors": 487
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| totalVisitors | number | 总访客数（所有记录的count累加） |
| yearVisitors | number | 本年访客数（从1月1日起） |
| monthVisitors | number | 本月访客数（从本月1日起） |
| weekVisitors | number | 本周访客数（从本周日起） |

---

### 3.8 footfall.events - 获取事件日志

获取系统事件日志。

**请求方式**: `GET /api/trpc/footfall.events`

**查询参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| limit | number | 否 | 50 | 返回条数，范围 1-200 |

**请求示例**: `GET /api/trpc/footfall.events?input={"limit":20}`

**响应格式**:
```json
{
  "result": {
    "data": [
      {
        "id": 1,
        "eventType": "person_count_changed",
        "message": "人数变化为 12 人",
        "timestamp": "2026-05-29T14:30:00.000Z",
        "metadata": { "count": 12, "roomName": "Area 04" }
      }
    ]
  }
}
```

---

### 3.9 vlm.report - 上报VLM分析日志

上报单条VLM（视觉语言模型）分析日志，用于模块2显示。

**请求方式**: `POST /api/trpc/vlm.report`

**请求体**:
```json
{
  "eventType": "count",
  "message": "检测到12人，位于Area 04区域",
  "timestamp": "2026-05-29T14:30:00.000Z",
  "roomName": "Area 04",
  "personId": 3,
  "confidence": 0.95,
  "metadata": { "behavior": "standing", "duration": 120 }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| eventType | string | 是 | 枚举: `info`, `detect`, `analyze`, `count`, `warning` |
| message | string | 是 | 分析消息内容，1-1000字符 |
| timestamp | string(ISO 8601) | 否 | 时间，不传则用服务器当前时间 |
| roomName | string | 否 | 关联区域 |
| personId | number | 否 | 追踪人物ID |
| confidence | number | 否 | AI置信度 0-1 |
| metadata | object | 否 | 扩展字段 |

**事件类型说明**:
| 类型 | 说明 | 显示颜色 |
|------|------|---------|
| info | 普通信息 | 灰色 |
| detect | 检测到目标 | 黄色 |
| analyze | 分析结果 | 绿色 |
| count | 人数统计 | 亮绿色 |
| warning | 警告 | 红色 |

**响应格式**:
```json
{
  "result": {
    "data": {
      "success": true
    }
  }
}
```

---

### 3.10 vlm.reportBatch - 批量上报VLM日志

批量上报多条VLM日志，适合摄像头系统批量推送。

**请求方式**: `POST /api/trpc/vlm.reportBatch`

**请求体**:
```json
{
  "logs": [
    {
      "eventType": "count",
      "message": "检测到12人",
      "timestamp": "2026-05-29T14:30:00.000Z",
      "roomName": "Area 04",
      "confidence": 0.95
    },
    {
      "eventType": "detect",
      "message": "检测到人员进入Area 08",
      "roomName": "Area 08",
      "personId": 5
    }
  ]
}
```

**响应格式**:
```json
{
  "result": {
    "data": {
      "success": true,
      "inserted": 2
    }
  }
}
```

---

### 3.11 vlm.latest - 获取VLM日志列表

获取最新的VLM分析日志，用于模块2（VLM分析）展示。

**请求方式**: `GET /api/trpc/vlm.latest`

**查询参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| limit | number | 否 | 50 | 返回条数，范围 1-200 |
| since | string(ISO 8601) | 否 | - | 只返回该时间之后的日志 |

**请求示例**: `GET /api/trpc/vlm.latest?input={"limit":50}`

**响应格式**:
```json
{
  "result": {
    "data": [
      {
        "id": 1,
        "eventType": "count",
        "message": "检测到12人，位于Area 04",
        "timestamp": "2026-05-29T14:30:00.000Z",
        "roomName": "Area 04",
        "personId": null,
        "confidence": 0.92,
        "metadata": null
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 日志ID |
| eventType | string | 事件类型 |
| message | string | 消息内容 |
| timestamp | string(ISO 8601) | 记录时间 |
| roomName | string \| null | 关联区域 |
| personId | number \| null | 人物ID |
| confidence | number \| null | 置信度 |
| metadata | object \| null | 扩展数据 |

---

## 四、各模块数据接入对照

### 模块1：监控画面 (ModuleCamera)
| 数据源 | 说明 |
|--------|------|
| iframe `http://192.168.42.1/#/dashboard` | reCamera 本地视频流画面 |
| `footfall.current` | 叠加显示实时人数 |

### 模块2：VLM实时分析 (ModuleVLM)
| 数据源 | 说明 |
|--------|------|
| `vlm.latest` | 获取日志列表展示 |
| `vlm.report` | （外部调用）上报分析日志 |
| `vlm.reportBatch` | （外部调用）批量上报 |

### 模块3：区域热力图 (ModuleHeatmap)
| 数据源 | 说明 |
|--------|------|
| `footfall.rooms` | 17个区域的currentCount决定热力颜色 |
| `footfall.stats` | 顶部统计栏显示总客流数据 |

### 模块4：今日客流趋势 (ModuleTrendMulti)
| 数据源 | 说明 |
|--------|------|
| `footfall.hourlyTrend` | 24小时折线图数据 |

### 模块5：到访时段分布 (ModulePieChart)
| 数据源 | 说明 |
|--------|------|
| `footfall.hourlyTrend` | 24小时环形图分布数据 |

### 模块6：区域客流排行 (ModuleRanking)
| 数据源 | 说明 |
|--------|------|
| `footfall.rooms` | 按currentCount排序的排行榜 |

### 模块7：综合信息面板 (ModuleInfoPanel)
| 数据源 | 说明 |
|--------|------|
| `footfall.rooms` | 计算在场人数、热力焦点、负载率 |

---

## 五、外部系统接入示例

以下命令使用 RFC 5737 文档专用地址。运行前请替换为目标设备的实际地址：

```bash
export DEVICE_IP=192.0.2.20
```

### 5.1 摄像头人数统计系统接入

场景：摄像头系统检测到人数变化后，同步到大屏系统。

**步骤1：上报人数变化**
```bash
curl -X POST "http://${DEVICE_IP}:3000/api/trpc/footfall.report" \
  -H "Content-Type: application/json" \
  -d '{
    "count": 15,
    "event": "person_count_changed",
    "timestamp": "2026-05-29T14:30:00.000Z",
    "roomName": "Area 04",
    "confidence": 0.95
  }'
```

**步骤2：更新区域人数（用于热力图）**
```bash
curl -X POST "http://${DEVICE_IP}:3000/api/trpc/footfall.updateRoom" \
  -H "Content-Type: application/json" \
  -d '{
    "id": 4,
    "currentCount": 15
  }'
```

### 5.2 VLM分析系统接入

场景：边缘AI分析设备推送分析结果到大屏。

**单条上报**:
```bash
curl -X POST "http://${DEVICE_IP}:3000/api/trpc/vlm.report" \
  -H "Content-Type: application/json" \
  -d '{
    "eventType": "analyze",
    "message": "Area 04区域检测到12人，其中3人在排队",
    "roomName": "Area 04",
    "confidence": 0.88,
    "metadata": { "queue": 3, "behavior": "shopping" }
  }'
```

**批量上报**:
```bash
curl -X POST "http://${DEVICE_IP}:3000/api/trpc/vlm.reportBatch" \
  -H "Content-Type: application/json" \
  -d '{
    "logs": [
      { "eventType": "count", "message": "Area 01: 3人", "roomName": "Area 01" },
      { "eventType": "count", "message": "Area 08: 10人", "roomName": "Area 08" },
      { "eventType": "warning", "message": "Area 16人数接近上限: 35/40", "roomName": "Area 16" }
    ]
  }'
```

### 5.3 查询当前状态

```bash
# 获取当前人数
curl "http://${DEVICE_IP}:3000/api/trpc/footfall.current"

# 获取所有区域数据
curl "http://${DEVICE_IP}:3000/api/trpc/footfall.rooms"

# 获取今日24小时分布
curl "http://${DEVICE_IP}:3000/api/trpc/footfall.hourlyTrend"

# 获取统计汇总
curl "http://${DEVICE_IP}:3000/api/trpc/footfall.stats"

# 获取最近50条VLM日志
curl "http://${DEVICE_IP}:3000/api/trpc/vlm.latest?input={\"limit\":50}"
```

---

## 六、前端刷新频率

| 模块 | 接口 | 刷新间隔 |
|------|------|---------|
| 监控画面 | footfall.current | 5秒 |
| VLM分析 | vlm.latest | 3秒 |
| 热力图 | footfall.rooms | 10秒 |
| 热力图 | footfall.stats | 30秒 |
| 客流趋势 | footfall.hourlyTrend | 页面加载时（可手动刷新） |
| 到访时段 | footfall.hourlyTrend | 页面加载时（可手动刷新） |
| 区域排行 | footfall.rooms | 10秒 |
| 综合面板 | footfall.rooms | 10秒 |

---

## 七、注意事项

1. **区域ID固定**: 17个区域的ID是固定的，外部系统更新区域人数时务必使用正确的ID。
2. **时区**: 服务器使用UTC时间存储，接口返回ISO 8601格式时间字符串。
3. **数据为空**: 当数据库无记录时，统计接口返回0，hourlyTrend返回24个count为0的数据点。
4. **VLM日志自动翻转**: vlm.latest 接口返回的数据按时间正序排列（旧的在前面），适合终端式展示。
5. **并发上报**: report 和 reportBatch 接口支持并发调用，无并发限制。
6. **热更新**: footfall.updateRoom 更新后，热力图、区域排行、综合面板会在下次刷新时自动更新（最长10秒延迟）。
