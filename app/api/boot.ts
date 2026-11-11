import { Hono } from "hono";
import { bodyLimit } from "hono/body-limit";
import type { HttpBindings } from "@hono/node-server";
import { fetchRequestHandler } from "@trpc/server/adapters/fetch";
import { appRouter } from "./router";
import { createContext } from "./context";
import { env } from "./lib/env";
import { and, eq, lt, ne } from "drizzle-orm";

const app = new Hono<{ Bindings: HttpBindings }>();

app.use(bodyLimit({ maxSize: 50 * 1024 * 1024 }));
app.use("/api/trpc/*", async (c) => {
  return fetchRequestHandler({
    endpoint: "/api/trpc",
    req: c.req.raw,
    router: appRouter,
    createContext,
  });
});
app.all("/api/*", (c) => c.json({ error: "Not Found" }, 404));

export default app;

if (env.isProduction) {
  const { serve } = await import("@hono/node-server");
  const { serveStaticFiles } = await import("./lib/vite");
  serveStaticFiles(app);

  const port = parseInt(process.env.PORT || "3000");
  serve({ fetch: app.fetch, port }, () => {
    console.log(`Server running on http://localhost:${port}/`);
  });

  // 每天凌晨2点清理30天前的流水记录，防止数据库无限增长导致磁盘占满
  const scheduleDailyCleanup = () => {
    const now = new Date();
    const next2AM = new Date(now);
    next2AM.setHours(2, 0, 0, 0);
    if (next2AM <= now) next2AM.setDate(next2AM.getDate() + 1);
    const msUntil = next2AM.getTime() - now.getTime();

    setTimeout(async () => {
      try {
        const { getDb } = await import("./queries/connection");
        const { personFlowRecords, eventLogs, vlmLogs } = await import("@db/schema");
        const db = getDb();
        // 室级别记录保留 400 天（覆盖完整一年，保证 yearVisitors 统计不丢数）
        // 全区域汇总保留 5 年；事件/VLM日志保留 90 天
        const cutoff400 = new Date();
        cutoff400.setDate(cutoff400.getDate() - 400);
        const cutoff5y = new Date();
        cutoff5y.setFullYear(cutoff5y.getFullYear() - 5);
        const cutoff90 = new Date();
        cutoff90.setDate(cutoff90.getDate() - 90);

        const cleanupTimeout = new Promise((_, reject) =>
          setTimeout(() => reject(new Error("cleanup timed out after 60s")), 60000)
        );
        await Promise.race([
          Promise.all([
            db.delete(personFlowRecords).where(and(lt(personFlowRecords.timestamp, cutoff400), ne(personFlowRecords.roomName, '全区域'))),
            db.delete(personFlowRecords).where(and(lt(personFlowRecords.timestamp, cutoff5y), eq(personFlowRecords.roomName, '全区域'))),
            db.delete(eventLogs).where(lt(eventLogs.timestamp, cutoff90)),
            db.delete(vlmLogs).where(lt(vlmLogs.timestamp, cutoff90)),
          ]),
          cleanupTimeout,
        ]);
        console.log(`[cleanup] 室记录400天 cutoff=${cutoff400.toISOString()}，全区域5年 cutoff=${cutoff5y.toISOString()}`);
      } catch (e) {
        // 即使DB卡死/超时，也要继续往下执行 scheduleDailyCleanup()，
        // 否则本次失败会导致此后每天的清理永久停止（无人重新调度）
        console.error("[cleanup] 清理失败:", e);
      }
      scheduleDailyCleanup();
    }, msUntil);

    console.log(`[cleanup] 下次清理时间: ${next2AM.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}`);
  };

  scheduleDailyCleanup();
}
