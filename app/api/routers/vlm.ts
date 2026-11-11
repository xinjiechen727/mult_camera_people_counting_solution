import { z } from "zod";
import { createRouter, publicQuery } from "../middleware";
import { getDb } from "../queries/connection";
import { vlmLogs } from "@db/schema";
import { desc, gte, sql } from "drizzle-orm";

function normalizeVlmDisplayText(text: string): string {
  return text
    .replaceAll("社区咖啡厅", "咖啡厅");
}

export const vlmRouter = createRouter({
  // 上报 VLM 分析日志
  report: publicQuery
    .input(
      z.object({
        eventType: z.enum(["info", "detect", "analyze", "count", "warning"]),
        message: z.string().min(1).max(1000),
        timestamp: z.string().optional(),
        roomName: z.string().optional(),
        personId: z.number().int().optional(),
        confidence: z.number().min(0).max(1).optional(),
        metadata: z.record(z.string(), z.any()).optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      await db.insert(vlmLogs).values({
        eventType: input.eventType,
        message: input.message,
        timestamp: input.timestamp ? new Date(input.timestamp) : new Date(),
        roomName: input.roomName,
        personId: input.personId,
        confidence: input.confidence,
        metadata: input.metadata,
      });
      await db.execute(
        sql`DELETE FROM vlm_logs WHERE id NOT IN (SELECT id FROM (SELECT id FROM vlm_logs ORDER BY timestamp DESC LIMIT 30) AS t)`
      );
      return { success: true };
    }),

  // 获取最近 N 条日志（默认50条，最多200条）
  latest: publicQuery
    .input(
      z
        .object({
          limit: z.number().int().min(1).max(200).optional().default(50),
          since: z.string().optional(), // ISO timestamp, 获取某时间之后的日志
        })
        .optional()
    )
    .query(async ({ input }) => {
      const db = getDb();
      const limit = input?.limit ?? 50;

      let query = db.select().from(vlmLogs).orderBy(desc(vlmLogs.timestamp)).limit(limit);

      if (input?.since) {
        const sinceDate = new Date(input.since);
        query = db
          .select()
          .from(vlmLogs)
          .where(gte(vlmLogs.timestamp, sinceDate))
          .orderBy(desc(vlmLogs.timestamp))
          .limit(limit) as any;
      }

      const logs = await query;
      return logs.map((log) => ({
        ...log,
        message: normalizeVlmDisplayText(log.message),
      })); // 已按 desc 排序，最新在最前
    }),

  // 批量上报（适合摄像头批量推送）
  reportBatch: publicQuery
    .input(
      z.object({
        logs: z.array(
          z.object({
            eventType: z.enum(["info", "detect", "analyze", "count", "warning"]),
            message: z.string().min(1).max(1000),
            timestamp: z.string().optional(),
            roomName: z.string().optional(),
            personId: z.number().int().optional(),
            confidence: z.number().min(0).max(1).optional(),
            metadata: z.record(z.string(), z.any()).optional(),
          })
        ),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const values = input.logs.map((log) => ({
        eventType: log.eventType,
        message: log.message,
        timestamp: log.timestamp ? new Date(log.timestamp) : new Date(),
        roomName: log.roomName,
        personId: log.personId,
        confidence: log.confidence,
        metadata: log.metadata,
      }));

      await db.insert(vlmLogs).values(values);
      await db.execute(
        sql`DELETE FROM vlm_logs WHERE id NOT IN (SELECT id FROM (SELECT id FROM vlm_logs ORDER BY timestamp DESC LIMIT 30) AS t)`
      );
      return { success: true, inserted: values.length };
    }),
});
