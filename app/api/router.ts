import { createRouter, publicQuery } from "./middleware";
import { footfallRouter } from "./routers/footfall";
import { vlmRouter } from "./routers/vlm";

export const appRouter = createRouter({
  ping: publicQuery.query(() => ({ ok: true, ts: Date.now() })),
  footfall: footfallRouter,
  vlm: vlmRouter,
});

export type AppRouter = typeof appRouter;
