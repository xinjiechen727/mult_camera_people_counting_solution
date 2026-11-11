import { getDb } from "../api/queries/connection";

async function fix() {
  const db = getDb();
  const tables = ['vlm_logs', 'daily_stats', 'event_logs', 'person_flow_records', 'rooms'];
  for (const t of tables) {
    try {
      await db.execute('DROP TABLE IF EXISTS `' + t + '`');
      console.log('Dropped ' + t);
    } catch(e: any) {
      console.log(t + ': ' + (e.message || 'ok'));
    }
  }
  console.log('Done');
  process.exit(0);
}

fix();
