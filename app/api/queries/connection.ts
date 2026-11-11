import { drizzle, type MySql2Database } from "drizzle-orm/mysql2";
import { env } from "../lib/env";
import * as schema from "@db/schema";
import * as relations from "@db/relations";
import mysql from "mysql2/promise";

const fullSchema = { ...schema, ...relations };

let instance: MySql2Database<typeof fullSchema>;

export function getDb() {
  if (!instance) {
    // 显式创建连接池：启用 keepAlive，防止 MariaDB 重启后连接失效
    const pool = mysql.createPool({
      uri: env.databaseUrl,
      waitForConnections: true,
      connectionLimit: 10,
      enableKeepAlive: true,
      keepAliveInitialDelay: 10000,
      timezone: "Z",
    });
    instance = drizzle({ client: pool, mode: "default", schema: fullSchema });
  }
  return instance;
}
