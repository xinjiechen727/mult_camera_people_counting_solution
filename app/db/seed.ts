import { getDb } from "../api/queries/connection";
import { rooms } from "./schema";

// Example areas. Keep these names aligned with each deployment's config.json.
const REAL_ROOMS = [
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
  { name: "Area 16", maxCapacity: 20, xPosition: 0.02, yPosition: 0.76, width: 0.30, height: 0.18, currentCount: 0, label: "Area 16" },
  { name: "Area 17", maxCapacity: 20, xPosition: 0.35, yPosition: 0.76, width: 0.30, height: 0.18, currentCount: 0, label: "Area 17" },
  { name: "Area 18", maxCapacity: 20, xPosition: 0.68, yPosition: 0.76, width: 0.30, height: 0.18, currentCount: 0, label: "Area 18" },
];

async function seed() {
  const db = getDb();
  console.log("Seeding database with 18 example areas...");

  const existing = await db.select().from(rooms);
  if (existing.length > 0) {
    console.log(`Found ${existing.length} existing rooms, clearing...`);
    await db.delete(rooms);
    console.log("Old rooms deleted.");
  }

  await db.insert(rooms).values(REAL_ROOMS);
  console.log(`Seeded ${REAL_ROOMS.length} example areas successfully:`);
  REAL_ROOMS.forEach((r, i) => {
    console.log(`  ${i + 1}. ${r.name} (capacity: ${r.maxCapacity})`);
  });
  process.exit(0);
}

seed();
