import { getDb } from "../api/queries/connection";
import { personFlowRecords } from "./schema";

async function seedStats() {
  const db = getDb();
  console.log("Seeding base statistics...");

  // Insert base cumulative records to establish the baseline
  // Total: 360109, Year: 46451, Month: 8465, Week: 0
  const now = new Date();
  const records = [];

  // 1. Total baseline - insert a record from beginning of year
  const yearStart = new Date(2026, 0, 1);
  records.push({
    count: 360109,
    event: "person_count_changed" as const,
    timestamp: yearStart,
    roomName: "系统初始化",
    personIds: [],
    confidence: 1.0,
  });

  // 2. Year baseline
  records.push({
    count: 46451,
    event: "person_count_changed" as const,
    timestamp: new Date(2026, 0, 2),
    roomName: "系统初始化-本年",
    personIds: [],
    confidence: 1.0,
  });

  // 3. Month baseline
  records.push({
    count: 8465,
    event: "person_count_changed" as const,
    timestamp: new Date(2026, 4, 1),
    roomName: "系统初始化-本月",
    personIds: [],
    confidence: 1.0,
  });

  await db.insert(personFlowRecords).values(records);

  console.log("Base statistics seeded successfully:");
  console.log("  Total base: 360,109");
  console.log("  Year base: 46,451");
  console.log("  Month base: 8,465");
  console.log("Done.");
  process.exit(0);
}

seedStats();
