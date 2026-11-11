import { z } from "zod";
import { createRouter, publicQuery } from "../middleware";
import { getDb } from "../queries/connection";
import {
  personFlowRecords,
  rooms,
  eventLogs,
} from "@db/schema";
import { desc, eq, sql, gte, lt, asc, and, ne } from "drizzle-orm";
import {
  getCalibratedHourlyTrend,
  getDashboardCalibration,
} from "../services/footfallCalibration";

// 服务端缓存各区域上次上报的人数，用于计算增量进入人次
// -1 表示该区域首次上报，跳过（避免服务重启后虚高）
const _prevRoomCounts = new Map<string, number>();

export const footfallRouter = createRouter({
  // 上报人流数据
  report: publicQuery
    .input(
      z.object({
        count: z.number().int().min(0),
        event: z.enum([
          "person_count_changed",
          "person_entered",
          "person_left",
        ]),
        timestamp: z.string().optional(),
        roomName: z.string().optional(),
        personIds: z.array(z.number()).optional(),
        confidence: z.number().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      await db.insert(personFlowRecords).values({
        count: input.count,
        event: input.event,
        timestamp: input.timestamp
          ? new Date(input.timestamp)
          : new Date(),
        roomName: input.roomName,
        personIds: input.personIds,
        confidence: input.confidence,
      });

      // 同时写入事件日志
      const eventMessages: Record<string, string> = {
        person_count_changed: `人数变化为 ${input.count} 人`,
        person_entered: `人员进入，当前 ${input.count} 人`,
        person_left: `人员离开，当前 ${input.count} 人`,
      };

      await db.insert(eventLogs).values({
        eventType: input.event,
        message: eventMessages[input.event] || `人数变化: ${input.count}`,
        timestamp: new Date(),
        metadata: {
          count: input.count,
          roomName: input.roomName,
        },
      });

      return { success: true };
    }),

  // 获取当前总人数
  current: publicQuery.query(async () => {
    const db = getDb();
    const latest = await db
      .select()
      .from(personFlowRecords)
      .orderBy(desc(personFlowRecords.timestamp))
      .limit(1);

    return {
      count: latest[0]?.count ?? 0,
      lastUpdate: latest[0]?.timestamp ?? new Date(),
      event: latest[0]?.event ?? "none",
    };
  }),

  // 获取趋势数据（最近N小时，默认1小时）
  trend: publicQuery
    .input(
      z
        .object({
          hours: z.number().int().min(1).max(168).optional().default(1),
        })
        .optional()
    )
    .query(async ({ input }) => {
      const db = getDb();
      const hours = input?.hours ?? 1;
      const since = new Date(Date.now() - hours * 60 * 60 * 1000);

      const records = await db
        .select()
        .from(personFlowRecords)
        .where(and(
          eq(personFlowRecords.roomName, '全区域'),
          gte(personFlowRecords.timestamp, since),
        ))
        .orderBy(personFlowRecords.timestamp);

      // 按5分钟聚合
      const bucketMap = new Map<string, number>();

      records.forEach((r) => {
        const d = new Date(r.timestamp);
        const key = `${String(d.getHours()).padStart(2, "0")}:${String(
          Math.floor(d.getMinutes() / 5) * 5
        ).padStart(2, "0")}`;
        bucketMap.set(key, r.count);
      });

      const aggregated: { time: string; count: number }[] = [];
      bucketMap.forEach((count, time) => {
        aggregated.push({ time, count });
      });

      return aggregated;
    }),

  // 获取各房间人流数据
  rooms: publicQuery.query(async () => {
    const db = getDb();
    const allRooms = await db.select().from(rooms).orderBy(asc(rooms.id));
    return allRooms;
  }),

  // 各区域今日累计进入人次（取代实时人数用于热力图展示，单次采集中断不会导致显示归零）
  roomsDaily: publicQuery.query(async () => {
    const calibration = await getDashboardCalibration();
    return calibration.regions.map((region) => ({
      roomName: region.name,
      total: region.adjustedCount,
      rawCount: region.rawCount,
    }));
  }),

  // 批量更新各区域实时人数（YOLO推理结果上报）
  reportRoomCounts: publicQuery
    .input(
      z.object({
        rooms: z.array(
          z.object({
            name: z.string(),
            count: z.number().int().min(0),
            // 显式进入人次（reCamera 用 ID 追踪计算，比瞬时人数差值更准确）
            // 有值时直接采用，不走差值逻辑；=0 表示本次调用不计入任何进入人次
            entryCount: z.number().int().min(0).optional(),
          })
        ),
        writeTotal: z.boolean().optional().default(false),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const now = new Date();

      const entryRecords: typeof personFlowRecords.$inferInsert[] = [];

      for (const room of input.rooms) {
        // 更新实时人数（用于热力图显示）
        await db
          .update(rooms)
          .set({ currentCount: room.count })
          .where(eq(rooms.name, room.name));

        let delta = 0;
        if (room.entryCount !== undefined) {
          // 显式提供：直接采用（reCamera ID 追踪 / 主循环对 reCamera 区域标 0）
          delta = room.entryCount;
        } else {
          // 差值法：适用于无 ID 追踪的 RTSP 摄像头
          const prev = _prevRoomCounts.get(room.name);
          if (prev !== undefined && room.count > prev) {
            delta = room.count - prev;
          }
        }
        _prevRoomCounts.set(room.name, room.count);

        if (delta > 0) {
          entryRecords.push({
            count: delta,
            event: 'person_entered',
            timestamp: now,
            roomName: room.name,
          });
        }
      }

      if (entryRecords.length > 0) {
        const totalEntries = entryRecords.reduce((s, r) => s + r.count, 0);
        const toInsert = [...entryRecords];
        if (input.writeTotal && totalEntries > 0) {
          toInsert.push({
            count: totalEntries,
            event: 'person_entered',
            timestamp: now,
            roomName: '全区域',
          });
        }
        await db.insert(personFlowRecords).values(toInsert);
      }

      return { success: true };
    }),

  // reCamera 设备实时人数代理（服务端转发，避免浏览器CORS限制）
  recameraCount: publicQuery.query(async () => {
    try {
      const resp = await fetch('http://192.168.42.1:1880/api/count', {
        signal: AbortSignal.timeout(3000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as {
        count: number;
        event: string;
        timestamp: string;
      };
      return {
        count: data.count ?? 0,
        event: data.event ?? 'person_count_changed',
        timestamp: data.timestamp ?? new Date().toISOString(),
        online: true,
      };
    } catch {
      return {
        count: 0,
        event: 'person_count_changed',
        timestamp: new Date().toISOString(),
        online: false,
      };
    }
  }),

  // 更新房间人数
  updateRoom: publicQuery
    .input(
      z.object({
        id: z.number().int(),
        currentCount: z.number().int().min(0),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      await db
        .update(rooms)
        .set({ currentCount: input.currentCount })
        .where(eq(rooms.id, input.id));
      return { success: true };
    }),

  // 获取统一校准后的今日与累计客流
  stats: publicQuery.query(async () => {
    const calibration = await getDashboardCalibration();
    return {
      ...calibration.cumulative,
      dayVisitors: calibration.adjustedCount,
      rawDayVisitors: calibration.rawCount,
      calibrationRatio: calibration.calibrationRatio,
      dailyTarget: calibration.dailyTarget,
      dailyCap: calibration.dailyCap,
      remainingCount: calibration.remainingCount,
      historyDaysUsed: calibration.historyDaysUsed,
      historyRawAverage: calibration.historyRawAverage,
      historyRawMedian: calibration.historyRawMedian,
    };
  }),

  calibration: publicQuery.query(async () => getDashboardCalibration()),

  // 获取今日24小时校准客流分布
  hourlyTrend: publicQuery.query(async () => {
    const calibration = await getDashboardCalibration();
    return getCalibratedHourlyTrend(calibration);
  }),

  // 获取最近事件日志
  events: publicQuery
    .input(
      z
        .object({
          limit: z.number().int().min(1).max(200).optional().default(50),
        })
        .optional()
    )
    .query(async ({ input }) => {
      const db = getDb();
      const limit = input?.limit ?? 50;
      const events = await db
        .select()
        .from(eventLogs)
        .orderBy(desc(eventLogs.timestamp))
        .limit(limit);
      return events;
    }),

  // 今日峰值人数（全区域 MAX count）
  todayPeak: publicQuery.query(async () => {
    const db = getDb();
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);

    const result = await db
      .select({ peak: sql<number>`COALESCE(MAX(${personFlowRecords.count}), 0)` })
      .from(personFlowRecords)
      .where(and(
        eq(personFlowRecords.roomName, '全区域'),
        gte(personFlowRecords.timestamp, todayStart),
      ));

    return { peak: result[0]?.peak ?? 0 };
  }),

  // 当前小时 vs 上一小时的人数变化百分比
  hourlyChange: publicQuery.query(async () => {
    const db = getDb();
    const now = new Date();
    const curHourStart = new Date(now);
    curHourStart.setMinutes(0, 0, 0);
    const prevHourStart = new Date(curHourStart);
    prevHourStart.setHours(prevHourStart.getHours() - 1);

    const [curRes, prevRes] = await Promise.all([
      db
        .select({ val: sql<number>`COALESCE(MAX(${personFlowRecords.count}), 0)` })
        .from(personFlowRecords)
        .where(and(
          eq(personFlowRecords.roomName, '全区域'),
          gte(personFlowRecords.timestamp, curHourStart),
        )),
      db
        .select({ val: sql<number>`COALESCE(MAX(${personFlowRecords.count}), 0)` })
        .from(personFlowRecords)
        .where(and(
          eq(personFlowRecords.roomName, '全区域'),
          gte(personFlowRecords.timestamp, prevHourStart),
          lt(personFlowRecords.timestamp, curHourStart),
        )),
    ]);

    const cur = Number(curRes[0]?.val ?? 0);
    const prev = Number(prevRes[0]?.val ?? 0);

    if (prev === 0) return { changePercent: cur > 0 ? 100 : null };
    return { changePercent: Math.round(((cur - prev) / prev) * 100) };
  }),

  // 获取今日各区域校准客流总量（用于排行榜）
  roomDailyTotals: publicQuery.query(async () => {
    const db = getDb();
    const calibration = await getDashboardCalibration();
    const allRooms = await db.select().from(rooms).orderBy(asc(rooms.id));
    const roomMap = new Map(allRooms.map((room) => [room.name, room]));

    return calibration.regions.map((region) => ({
      name: region.name,
      maxCapacity: roomMap.get(region.name)?.maxCapacity ?? 20,
      dailyTotal: region.adjustedCount,
      rawTotal: region.rawCount,
      currentCount: roomMap.get(region.name)?.currentCount ?? 0,
    }));
  }),

  // 批量上报房间数据（用于初始化模拟数据）
  seedRooms: publicQuery.mutation(async () => {
    const db = getDb();
    const existing = await db.select().from(rooms);
    if (existing.length > 0) {
      return { message: "Rooms already seeded" };
    }

    const roomData = [
      { name: "Area 01", maxCapacity: 20, xPosition: 0.02, yPosition: 0.04, width: 0.16, height: 0.17, currentCount: 0, label: "Area 01" },
      { name: "Area 02", maxCapacity: 20, xPosition: 0.22, yPosition: 0.04, width: 0.16, height: 0.17, currentCount: 0, label: "Area 02" },
      { name: "Area 03", maxCapacity: 20, xPosition: 0.42, yPosition: 0.04, width: 0.16, height: 0.17, currentCount: 0, label: "Area 03" },
      { name: "Area 04", maxCapacity: 20, xPosition: 0.62, yPosition: 0.04, width: 0.16, height: 0.17, currentCount: 0, label: "Area 04" },
      { name: "Area 05", maxCapacity: 20, xPosition: 0.82, yPosition: 0.04, width: 0.16, height: 0.17, currentCount: 0, label: "Area 05" },
      { name: "Area 06", maxCapacity: 20, xPosition: 0.02, yPosition: 0.28, width: 0.16, height: 0.17, currentCount: 0, label: "Area 06" },
      { name: "Area 07", maxCapacity: 20, xPosition: 0.22, yPosition: 0.28, width: 0.16, height: 0.17, currentCount: 0, label: "Area 07" },
      { name: "Area 08", maxCapacity: 20, xPosition: 0.42, yPosition: 0.28, width: 0.16, height: 0.17, currentCount: 0, label: "Area 08" },
      { name: "Area 09", maxCapacity: 20, xPosition: 0.62, yPosition: 0.28, width: 0.16, height: 0.17, currentCount: 0, label: "Area 09" },
      { name: "Area 10", maxCapacity: 20, xPosition: 0.82, yPosition: 0.28, width: 0.16, height: 0.17, currentCount: 0, label: "Area 10" },
      { name: "Area 11", maxCapacity: 20, xPosition: 0.02, yPosition: 0.52, width: 0.16, height: 0.17, currentCount: 0, label: "Area 11" },
      { name: "Area 12", maxCapacity: 20, xPosition: 0.22, yPosition: 0.52, width: 0.16, height: 0.17, currentCount: 0, label: "Area 12" },
      { name: "Area 13", maxCapacity: 20, xPosition: 0.42, yPosition: 0.52, width: 0.16, height: 0.17, currentCount: 0, label: "Area 13" },
      { name: "Area 14", maxCapacity: 20, xPosition: 0.62, yPosition: 0.52, width: 0.16, height: 0.17, currentCount: 0, label: "Area 14" },
      { name: "Area 15", maxCapacity: 20, xPosition: 0.82, yPosition: 0.52, width: 0.16, height: 0.17, currentCount: 0, label: "Area 15" },
      { name: "Area 16", maxCapacity: 20, xPosition: 0.02, yPosition: 0.76, width: 0.45, height: 0.18, currentCount: 0, label: "Area 16" },
      { name: "Area 17", maxCapacity: 20, xPosition: 0.52, yPosition: 0.76, width: 0.46, height: 0.18, currentCount: 0, label: "Area 17" },
    ];

    await db.insert(rooms).values(roomData);
    return { message: "Rooms seeded successfully" };
  }),

  // 归档清理90天前的单区域明细记录（保留全区域汇总行）
  archiveOldRecords: publicQuery
    .input(z.object({ cutoffDate: z.string() }))
    .mutation(async ({ input }) => {
      const db = getDb();
      const cutoff = new Date(input.cutoffDate);
      const result = await db
        .delete(personFlowRecords)
        .where(and(
          lt(personFlowRecords.timestamp, cutoff),
          ne(personFlowRecords.roomName, '全区域'),
        ));
      return { deleted: result[0].affectedRows, cutoff: input.cutoffDate };
    }),
});
