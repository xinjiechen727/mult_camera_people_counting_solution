export const DAILY_TARGET = 300;
export const DAILY_CAP = 350;
export const CALIBRATION_DAYS = 7;
export const CALIBRATION_TIMEZONE = "Asia/Shanghai";
export const UNNAMED_REGION = "未命名区域";

const CST_OFFSET_MS = 8 * 60 * 60 * 1000;

export type RawRegionCount = {
  name: string;
  rawCount: number;
};

export type RegionCalibration = RawRegionCount & {
  adjustedCount: number;
};

export function parseRegionAllocations(value: unknown): RegionCalibration[] {
  const parsed =
    typeof value === "string" ? (JSON.parse(value) as unknown) : value;
  if (!Array.isArray(parsed)) {
    throw new Error("region_allocations 必须是数组");
  }
  return parsed as RegionCalibration[];
}

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function computeCalibrationRatio(
  historyRawCounts: number[],
  target = DAILY_TARGET
): number {
  if (historyRawCounts.length === 0 || target <= 0) return 1;
  return Math.max(1, median(historyRawCounts) / target);
}

export function computeAdjustedTotal(
  rawCount: number,
  calibrationRatio: number,
  cap = DAILY_CAP
): number {
  if (rawCount <= 0) return 0;
  const ratio = calibrationRatio > 0 ? calibrationRatio : 1;
  return Math.min(cap, Math.floor(rawCount / ratio));
}

export function normalizedRegions(
  regions: RawRegionCount[]
): RawRegionCount[] {
  const totals = new Map<string, number>();
  for (const region of regions) {
    const name = region.name.trim() || UNNAMED_REGION;
    totals.set(name, (totals.get(name) ?? 0) + Math.max(0, region.rawCount));
  }
  return [...totals.entries()]
    .map(([name, rawCount]) => ({ name, rawCount }))
    .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
}

export function allocateLargestRemainder(
  regions: RawRegionCount[],
  adjustedTotal: number
): RegionCalibration[] {
  const normalized = normalizedRegions(regions);
  const target = Math.max(0, Math.floor(adjustedTotal));
  const rawTotal = normalized.reduce((sum, region) => sum + region.rawCount, 0);

  if (target === 0 || rawTotal === 0) {
    return normalized.map((region) => ({ ...region, adjustedCount: 0 }));
  }

  const allocations = normalized.map((region) => {
    const ideal = (region.rawCount / rawTotal) * target;
    const adjustedCount = Math.floor(ideal);
    return {
      ...region,
      adjustedCount,
      remainder: ideal - adjustedCount,
    };
  });

  const assigned = allocations.reduce(
    (sum, region) => sum + region.adjustedCount,
    0
  );
  const missing = target - assigned;
  [...allocations]
    .sort(
      (a, b) =>
        b.remainder - a.remainder ||
        a.name.localeCompare(b.name, "zh-CN")
    )
    .slice(0, missing)
    .forEach((region) => {
      region.adjustedCount += 1;
    });

  return allocations.map(({ remainder: _remainder, ...region }) => region);
}

export function growAllocationMonotonic(
  regions: RawRegionCount[],
  previous: RegionCalibration[],
  adjustedTotal: number
): RegionCalibration[] {
  const currentRaw = normalizedRegions(regions);
  const rawMap = new Map(currentRaw.map((region) => [region.name, region.rawCount]));
  const allocationMap = new Map<string, number>();

  for (const region of previous) {
    const name = region.name.trim() || UNNAMED_REGION;
    allocationMap.set(
      name,
      (allocationMap.get(name) ?? 0) + Math.max(0, region.adjustedCount)
    );
  }
  for (const region of currentRaw) {
    if (!allocationMap.has(region.name)) allocationMap.set(region.name, 0);
  }

  const previousTotal = [...allocationMap.values()].reduce(
    (sum, count) => sum + count,
    0
  );
  const target = Math.max(previousTotal, Math.floor(adjustedTotal));

  if (previousTotal === 0) {
    return allocateLargestRemainder(currentRaw, target);
  }

  const rawTotal = currentRaw.reduce((sum, region) => sum + region.rawCount, 0);
  let assigned = previousTotal;
  while (assigned < target) {
    const nextTotal = assigned + 1;
    const candidates =
      currentRaw.length > 0
        ? currentRaw
        : [{ name: UNNAMED_REGION, rawCount: 0 }];

    const selected = [...candidates].sort((a, b) => {
      const aDeficit =
        (rawTotal > 0 ? (a.rawCount / rawTotal) * nextTotal : 0) -
        (allocationMap.get(a.name) ?? 0);
      const bDeficit =
        (rawTotal > 0 ? (b.rawCount / rawTotal) * nextTotal : 0) -
        (allocationMap.get(b.name) ?? 0);
      return (
        bDeficit - aDeficit || a.name.localeCompare(b.name, "zh-CN")
      );
    })[0];
    allocationMap.set(
      selected.name,
      (allocationMap.get(selected.name) ?? 0) + 1
    );
    assigned += 1;
  }

  return [...allocationMap.entries()]
    .map(([name, adjustedCount]) => ({
      name,
      rawCount: rawMap.get(name) ?? 0,
      adjustedCount,
    }))
    .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
}

export function cstDateKey(date = new Date()): string {
  const cst = new Date(date.getTime() + CST_OFFSET_MS);
  return `${cst.getUTCFullYear()}-${String(cst.getUTCMonth() + 1).padStart(
    2,
    "0"
  )}-${String(cst.getUTCDate()).padStart(2, "0")}`;
}

export function shiftDateKey(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T00:00:00.000Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function currentPeriodStarts(dateKey: string) {
  const date = new Date(`${dateKey}T00:00:00.000Z`);
  const yearStart = `${date.getUTCFullYear()}-01-01`;
  const monthStart = `${date.getUTCFullYear()}-${String(
    date.getUTCMonth() + 1
  ).padStart(2, "0")}-01`;
  const mondayOffset = (date.getUTCDay() + 6) % 7;
  const weekStart = shiftDateKey(dateKey, -mondayOffset);
  return { yearStart, monthStart, weekStart };
}

export function postBaselineIncrement(
  states: Array<{ date: string; adjustedCount: number }>,
  baselineDay: string,
  baselineDayAdjustedCount: number
): number {
  return states.reduce((sum, state) => {
    if (state.date < baselineDay) return sum;
    if (state.date === baselineDay) {
      return sum + Math.max(0, state.adjustedCount - baselineDayAdjustedCount);
    }
    return sum + state.adjustedCount;
  }, 0);
}

export function periodAdjustedTotal(
  states: Array<{ date: string; adjustedCount: number }>,
  periodStart: string
): number {
  return states.reduce(
    (sum, state) =>
      state.date >= periodStart ? sum + state.adjustedCount : sum,
    0
  );
}

export function cstDayRange(dateKey: string): { start: Date; end: Date } {
  const start = new Date(
    new Date(`${dateKey}T00:00:00.000Z`).getTime() - CST_OFFSET_MS
  );
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return { start, end };
}
