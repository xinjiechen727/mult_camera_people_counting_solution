import {
  and,
  desc,
  eq,
  gte,
  isNull,
  lt,
  lte,
  ne,
  or,
  sql,
} from "drizzle-orm";
import {
  dailyCalibrations,
  personFlowRecords,
  rooms,
  visitorBaselines,
} from "@db/schema";
import { getDb } from "../queries/connection";
import {
  CALIBRATION_DAYS,
  DAILY_CAP,
  DAILY_TARGET,
  UNNAMED_REGION,
  allocateLargestRemainder,
  computeAdjustedTotal,
  computeCalibrationRatio,
  cstDateKey,
  cstDayRange,
  currentPeriodStarts,
  growAllocationMonotonic,
  median,
  normalizedRegions,
  parseRegionAllocations,
  periodAdjustedTotal,
  postBaselineIncrement,
  shiftDateKey,
  type RawRegionCount,
  type RegionCalibration,
} from "./footfallCalibrationMath";

export type DashboardCalibration = {
  date: string;
  rawCount: number;
  adjustedCount: number;
  calibrationRatio: number;
  dailyTarget: number;
  dailyCap: number;
  historyDaysUsed: number;
  historyRawAverage: number;
  historyRawMedian: number;
  remainingCount: number;
  regions: RegionCalibration[];
  cumulative: {
    totalVisitors: number;
    yearVisitors: number;
    monthVisitors: number;
    weekVisitors: number;
    baselineAsOf: Date | null;
    baselineDayAdjustedCount: number;
  };
};

async function queryRawRegions(
  db: any,
  dateKey: string
): Promise<RawRegionCount[]> {
  const { start, end } = cstDayRange(dateKey);
  const [knownRooms, rawRows] = await Promise.all([
    db.select({ name: rooms.name }).from(rooms),
    db
      .select({
        roomName: personFlowRecords.roomName,
        total: sql<number>`COALESCE(SUM(${personFlowRecords.count}), 0)`,
      })
      .from(personFlowRecords)
      .where(
        and(
          eq(personFlowRecords.event, "person_entered"),
          or(
            ne(personFlowRecords.roomName, "全区域"),
            isNull(personFlowRecords.roomName)
          ),
          gte(personFlowRecords.timestamp, start),
          lt(personFlowRecords.timestamp, end)
        )
      )
      .groupBy(personFlowRecords.roomName),
  ]);

  const totals = new Map<string, number>();
  for (const room of knownRooms) totals.set(room.name.trim(), 0);
  for (const row of rawRows) {
    const name = row.roomName?.trim() || UNNAMED_REGION;
    totals.set(name, (totals.get(name) ?? 0) + Number(row.total));
  }
  return normalizedRegions(
    [...totals.entries()].map(([name, rawCount]) => ({ name, rawCount }))
  );
}

async function queryHistoryRawCounts(
  db: ReturnType<typeof getDb>,
  dateKey: string
): Promise<number[]> {
  const { start } = cstDayRange(dateKey);
  const dayExpression = sql<string>`DATE_FORMAT(CONVERT_TZ(${personFlowRecords.timestamp}, '+00:00', '+08:00'), '%Y-%m-%d')`;
  const rows = await db
    .select({
      date: dayExpression,
      total: sql<number>`COALESCE(SUM(${personFlowRecords.count}), 0)`,
    })
    .from(personFlowRecords)
    .where(
      and(
        eq(personFlowRecords.event, "person_entered"),
        or(
          ne(personFlowRecords.roomName, "全区域"),
          isNull(personFlowRecords.roomName)
        ),
        lt(personFlowRecords.timestamp, start)
      )
    )
    .groupBy(dayExpression)
    .orderBy(desc(dayExpression))
    .limit(CALIBRATION_DAYS);
  return rows.map((row) => Number(row.total));
}

async function getOrCreateDailyCalibration(dateKey: string) {
  const db = getDb();
  const existing = await db
    .select()
    .from(dailyCalibrations)
    .where(eq(dailyCalibrations.date, dateKey))
    .limit(1);
  if (existing[0]) return existing[0];

  const history = await queryHistoryRawCounts(db, dateKey);
  const historyAverage =
    history.length > 0
      ? history.reduce((sum, count) => sum + count, 0) / history.length
      : 0;
  const historyMedian = median(history);
  const ratio = computeCalibrationRatio(history);

  if (history.length === 0) {
    console.warn(
      `[footfall-calibration] ${dateKey} 无完整历史日期，校准比例暂用 1`
    );
  }

  try {
    await db.insert(dailyCalibrations).values({
      date: dateKey,
      dailyTarget: DAILY_TARGET,
      dailyCap: DAILY_CAP,
      calibrationRatio: ratio,
      historyDaysUsed: history.length,
      historyRawAverage: historyAverage,
      historyRawMedian: historyMedian,
      rawCount: 0,
      adjustedCount: 0,
      regionAllocations: [],
    });
  } catch (error) {
    if ((error as { code?: string }).code !== "ER_DUP_ENTRY") throw error;
  }

  const created = await db
    .select()
    .from(dailyCalibrations)
    .where(eq(dailyCalibrations.date, dateKey))
    .limit(1);
  if (!created[0]) throw new Error(`无法创建 ${dateKey} 每日校准状态`);
  return created[0];
}

async function refreshDailyCalibration(
  dateKey: string,
  todayKey: string
) {
  await getOrCreateDailyCalibration(dateKey);
  const db = getDb();

  return db.transaction(async (tx) => {
    const rows = await tx
      .select()
      .from(dailyCalibrations)
      .where(eq(dailyCalibrations.date, dateKey))
      .limit(1)
      .for("update");
    const state = rows[0];
    if (!state) throw new Error(`缺少 ${dateKey} 每日校准状态`);

    const rawRegions = await queryRawRegions(tx, dateKey);
    const rawCount = rawRegions.reduce(
      (sum, region) => sum + region.rawCount,
      0
    );
    const computedAdjusted = computeAdjustedTotal(
      rawCount,
      state.calibrationRatio,
      state.dailyCap
    );
    const adjustedCount = Math.min(
      state.dailyCap,
      Math.max(state.adjustedCount, computedAdjusted)
    );
    const previous = parseRegionAllocations(state.regionAllocations);
    const regionAllocations = growAllocationMonotonic(
      rawRegions,
      previous,
      adjustedCount
    );
    const finalizedAt =
      dateKey < todayKey ? state.finalizedAt ?? new Date() : state.finalizedAt;

    await tx
      .update(dailyCalibrations)
      .set({
        rawCount,
        adjustedCount,
        regionAllocations,
        finalizedAt,
        updatedAt: new Date(),
      })
      .where(eq(dailyCalibrations.id, state.id));

    return {
      ...state,
      rawCount,
      adjustedCount,
      regionAllocations,
      finalizedAt,
    };
  });
}

export async function getDashboardCalibration(
  now = new Date()
): Promise<DashboardCalibration> {
  const db = getDb();
  const todayKey = cstDateKey(now);
  const baselineRows = await db
    .select()
    .from(visitorBaselines)
    .orderBy(desc(visitorBaselines.baselineAsOf))
    .limit(1);
  const baseline = baselineRows[0] ?? null;

  const firstDate = baseline
    ? baseline.baselineDay
    : todayKey;
  let cursor = firstDate;
  for (let checked = 0; cursor <= todayKey && checked < 4000; checked += 1) {
    await refreshDailyCalibration(cursor, todayKey);
    cursor = shiftDateKey(cursor, 1);
  }

  const todayRows = await db
    .select()
    .from(dailyCalibrations)
    .where(eq(dailyCalibrations.date, todayKey))
    .limit(1);
  const today = todayRows[0];
  if (!today) throw new Error(`缺少 ${todayKey} 校准结果`);

  const states = await db
    .select({
      date: dailyCalibrations.date,
      adjustedCount: dailyCalibrations.adjustedCount,
    })
    .from(dailyCalibrations)
    .where(lte(dailyCalibrations.date, todayKey));
  const starts = currentPeriodStarts(todayKey);

  let totalVisitors = periodAdjustedTotal(states, "0000-01-01");
  let yearVisitors = periodAdjustedTotal(states, starts.yearStart);
  let monthVisitors = periodAdjustedTotal(states, starts.monthStart);
  let weekVisitors = periodAdjustedTotal(states, starts.weekStart);
  let baselineAsOf: Date | null = null;
  let baselineDayAdjustedCount = 0;

  if (baseline) {
    const baselineDay = baseline.baselineDay;
    const increment = postBaselineIncrement(
      states,
      baselineDay,
      baseline.baselineDayAdjustedCount
    );
    totalVisitors = baseline.totalBaseline + increment;
    baselineAsOf = baseline.baselineAsOf;
    baselineDayAdjustedCount = baseline.baselineDayAdjustedCount;

    yearVisitors =
      starts.yearStart === baseline.yearStart
        ? baseline.yearBaseline + increment
        : periodAdjustedTotal(states, starts.yearStart);
    monthVisitors =
      starts.monthStart === baseline.monthStart
        ? baseline.monthBaseline + increment
        : periodAdjustedTotal(states, starts.monthStart);
    weekVisitors =
      starts.weekStart === baseline.weekStart
        ? baseline.weekBaseline + increment
        : periodAdjustedTotal(states, starts.weekStart);
  }

  return {
    date: todayKey,
    rawCount: today.rawCount,
    adjustedCount: today.adjustedCount,
    calibrationRatio: today.calibrationRatio,
    dailyTarget: today.dailyTarget,
    dailyCap: today.dailyCap,
    historyDaysUsed: today.historyDaysUsed,
    historyRawAverage: today.historyRawAverage,
    historyRawMedian: today.historyRawMedian,
    remainingCount: Math.max(0, today.dailyCap - today.adjustedCount),
    regions: parseRegionAllocations(today.regionAllocations),
    cumulative: {
      totalVisitors,
      yearVisitors,
      monthVisitors,
      weekVisitors,
      baselineAsOf,
      baselineDayAdjustedCount,
    },
  };
}

export async function getCalibratedHourlyTrend(
  calibration: DashboardCalibration
) {
  const db = getDb();
  const { start, end } = cstDayRange(calibration.date);
  const rows = await db
    .select({
      hour: sql<number>`HOUR(CONVERT_TZ(${personFlowRecords.timestamp}, '+00:00', '+08:00'))`,
      total: sql<number>`COALESCE(SUM(${personFlowRecords.count}), 0)`,
    })
    .from(personFlowRecords)
    .where(
      and(
        eq(personFlowRecords.event, "person_entered"),
        or(
          ne(personFlowRecords.roomName, "全区域"),
          isNull(personFlowRecords.roomName)
        ),
        gte(personFlowRecords.timestamp, start),
        lt(personFlowRecords.timestamp, end)
      )
    )
    .groupBy(
      sql`HOUR(CONVERT_TZ(${personFlowRecords.timestamp}, '+00:00', '+08:00'))`
    );

  const rawByHour = new Map(rows.map((row) => [Number(row.hour), Number(row.total)]));
  const allocations = allocateLargestRemainder(
    Array.from({ length: 24 }, (_, hour) => ({
      name: String(hour),
      rawCount: rawByHour.get(hour) ?? 0,
    })),
    calibration.adjustedCount
  );
  const adjustedByHour = new Map(
    allocations.map((allocation) => [
      Number(allocation.name),
      allocation.adjustedCount,
    ])
  );

  return Array.from({ length: 24 }, (_, hour) => ({
    hour: `${String(hour).padStart(2, "0")}:00`,
    count: adjustedByHour.get(hour) ?? 0,
    rawCount: rawByHour.get(hour) ?? 0,
  }));
}
