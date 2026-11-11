import { describe, expect, it } from "vitest";
import {
  allocateLargestRemainder,
  computeAdjustedTotal,
  computeCalibrationRatio,
  cstDateKey,
  currentPeriodStarts,
  growAllocationMonotonic,
  median,
  parseRegionAllocations,
  periodAdjustedTotal,
  postBaselineIncrement,
} from "./footfallCalibrationMath";

describe("footfall calibration", () => {
  it("uses the median of the confirmed seven complete days", () => {
    const history = [122, 266, 1943, 626, 1942, 2054, 1459];
    expect(median(history)).toBe(1459);
    expect(computeCalibrationRatio(history)).toBeCloseTo(1459 / 300, 10);
    expect(computeAdjustedTotal(1151, 1459 / 300)).toBe(236);
  });

  it("caps the adjusted total and handles empty history", () => {
    expect(computeCalibrationRatio([])).toBe(1);
    expect(computeAdjustedTotal(9999, 2, 350)).toBe(350);
    expect(computeAdjustedTotal(0, 2, 350)).toBe(0);
  });

  it("uses largest remainders and preserves the exact total", () => {
    const allocation = allocateLargestRemainder(
      [
        { name: "A", rawCount: 5 },
        { name: "B", rawCount: 3 },
        { name: "C", rawCount: 2 },
      ],
      7
    );
    expect(allocation.map((region) => region.adjustedCount)).toEqual([4, 2, 1]);
    expect(
      allocation.reduce((sum, region) => sum + region.adjustedCount, 0)
    ).toBe(7);
  });

  it("adds exactly one region count without decreasing existing regions", () => {
    const previous = [
      { name: "A", rawCount: 6, adjustedCount: 2 },
      { name: "B", rawCount: 4, adjustedCount: 1 },
    ];
    const next = growAllocationMonotonic(
      [
        { name: "A", rawCount: 5 },
        { name: "B", rawCount: 5 },
      ],
      previous,
      4
    );
    expect(next.reduce((sum, region) => sum + region.adjustedCount, 0)).toBe(4);
    expect(
      next.find((region) => region.name === "A")?.adjustedCount
    ).toBeGreaterThanOrEqual(2);
    expect(
      next.find((region) => region.name === "B")?.adjustedCount
    ).toBeGreaterThanOrEqual(1);
  });

  it("uses Asia/Shanghai calendar boundaries", () => {
    expect(cstDateKey(new Date("2026-07-30T15:59:59.000Z"))).toBe("2026-07-30");
    expect(cstDateKey(new Date("2026-07-30T16:00:00.000Z"))).toBe("2026-07-31");
  });

  it("parses MariaDB JSON columns returned as strings", () => {
    const regions = [
      { name: "A", rawCount: 10, adjustedCount: 2 },
    ];
    expect(parseRegionAllocations(JSON.stringify(regions))).toEqual(regions);
    expect(parseRegionAllocations(regions)).toEqual(regions);
  });

  it("adds only the adjusted increment after the cumulative baseline", () => {
    const states = [
      { date: "2026-07-30", adjustedCount: 237 },
      { date: "2026-07-31", adjustedCount: 2 },
    ];
    expect(postBaselineIncrement(states, "2026-07-30", 236)).toBe(3);
    expect(postBaselineIncrement(states, "2026-07-30", 236)).toBe(3);
  });

  it("handles Monday, month, and year period boundaries", () => {
    expect(currentPeriodStarts("2026-08-03")).toEqual({
      yearStart: "2026-01-01",
      monthStart: "2026-08-01",
      weekStart: "2026-08-03",
    });
    expect(currentPeriodStarts("2027-01-01")).toEqual({
      yearStart: "2027-01-01",
      monthStart: "2027-01-01",
      weekStart: "2026-12-28",
    });
    expect(
      periodAdjustedTotal(
        [
          { date: "2026-12-31", adjustedCount: 10 },
          { date: "2027-01-01", adjustedCount: 4 },
        ],
        "2027-01-01"
      )
    ).toBe(4);
  });
});
