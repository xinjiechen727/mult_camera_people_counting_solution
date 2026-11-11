import {
  mysqlTable,
  serial,
  varchar,
  int,
  timestamp,
  json,
  date,
  float,
  double,
  uniqueIndex,
} from "drizzle-orm/mysql-core";

// 人流记录表 — 每次人数变化时记录
export const personFlowRecords = mysqlTable("person_flow_records", {
  id: serial("id").primaryKey(),
  count: int("count").notNull(),
  event: varchar("event", { length: 50 }).notNull(), // person_count_changed / person_entered / person_left
  timestamp: timestamp("timestamp").notNull().defaultNow(),
  roomName: varchar("room_name", { length: 100 }),
  personIds: json("person_ids").$type<number[]>(),
  confidence: float("confidence"), // AI 置信度
});

// 房间表 — 各房间的空间信息和容量
export const rooms = mysqlTable("rooms", {
  id: serial("id").primaryKey(),
  name: varchar("name", { length: 100 }).notNull(),
  floor: int("floor").notNull().default(1),
  maxCapacity: int("max_capacity").notNull().default(20),
  xPosition: float("x_position").notNull().default(0),
  yPosition: float("y_position").notNull().default(0),
  width: float("width").notNull().default(100),
  height: float("height").notNull().default(80),
  currentCount: int("current_count").notNull().default(0),
  label: varchar("label", { length: 50 }), // 显示标签
});

// 每日统计表 — 每日汇总数据
// VLM 分析日志表 — 本地VLM实时分析输出
export const vlmLogs = mysqlTable("vlm_logs", {
  id: serial("id").primaryKey(),
  eventType: varchar("event_type", { length: 50 }).notNull(), // info / detect / analyze / count / warning
  message: varchar("message", { length: 1000 }).notNull(),
  timestamp: timestamp("timestamp").notNull().defaultNow(),
  roomName: varchar("room_name", { length: 100 }), // 关联区域
  personId: int("person_id"), // 追踪到的人物ID
  confidence: float("confidence"), // AI 置信度 0-1
  metadata: json("metadata"), // 扩展字段（行为类型、停留时长等）
});

export const dailyStats = mysqlTable("daily_stats", {
  id: serial("id").primaryKey(),
  date: date("date").notNull(),
  totalVisitors: int("total_visitors").notNull().default(0),
  peakCount: int("peak_count").notNull().default(0),
  peakTime: timestamp("peak_time"),
  averageCount: float("average_count").default(0),
});

export type RegionCalibration = {
  name: string;
  rawCount: number;
  adjustedCount: number;
};

export const dailyCalibrations = mysqlTable(
  "daily_calibrations",
  {
    id: serial("id").primaryKey(),
    date: date("date", { mode: "string" }).notNull(),
    dailyTarget: int("daily_target").notNull(),
    dailyCap: int("daily_cap").notNull(),
    calibrationRatio: double("calibration_ratio").notNull(),
    historyDaysUsed: int("history_days_used").notNull(),
    historyRawAverage: double("history_raw_average").notNull(),
    historyRawMedian: double("history_raw_median").notNull(),
    rawCount: int("raw_count").notNull().default(0),
    adjustedCount: int("adjusted_count").notNull().default(0),
    regionAllocations: json("region_allocations")
      .$type<RegionCalibration[]>()
      .notNull(),
    finalizedAt: timestamp("finalized_at"),
    createdAt: timestamp("created_at").notNull().defaultNow(),
    updatedAt: timestamp("updated_at").notNull().defaultNow().onUpdateNow(),
  },
  (table) => [
    uniqueIndex("daily_calibrations_date_unique").on(table.date),
  ]
);

export const visitorBaselines = mysqlTable("visitor_baselines", {
  id: serial("id").primaryKey(),
  totalBaseline: int("total_baseline").notNull(),
  yearBaseline: int("year_baseline").notNull(),
  monthBaseline: int("month_baseline").notNull(),
  weekBaseline: int("week_baseline").notNull(),
  baselineAsOf: timestamp("baseline_as_of").notNull(),
  baselineDay: date("baseline_day", { mode: "string" }).notNull(),
  baselineDayAdjustedCount: int("baseline_day_adjusted_count").notNull(),
  yearStart: date("year_start", { mode: "string" }).notNull(),
  monthStart: date("month_start", { mode: "string" }).notNull(),
  weekStart: date("week_start", { mode: "string" }).notNull(),
  timezone: varchar("timezone", { length: 64 }).notNull(),
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow().onUpdateNow(),
});

// 事件日志表 — 系统事件记录
export const eventLogs = mysqlTable("event_logs", {
  id: serial("id").primaryKey(),
  eventType: varchar("event_type", { length: 50 }).notNull(),
  message: varchar("message", { length: 500 }).notNull(),
  timestamp: timestamp("timestamp").notNull().defaultNow(),
  metadata: json("metadata"),
});
