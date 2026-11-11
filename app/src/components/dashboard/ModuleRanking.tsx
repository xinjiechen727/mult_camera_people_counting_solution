import { useState, useEffect, useMemo } from 'react';
import { BarChart3 } from 'lucide-react';
import { trpc } from '@/providers/trpc';

const PAGE_SIZE = 9;
const ROTATE_MS = 5000;

function rankColor(rank: number): string {
  if (rank === 1) return '#8BC34A';
  if (rank === 2) return '#4CAF50';
  if (rank === 3) return '#ffb800';
  return 'rgba(224,240,255,0.28)';
}

function barColor(pct: number): string {
  if (pct <= 0.3) return '#4CAF50';
  if (pct <= 0.5) return '#8BC34A';
  if (pct <= 0.7) return '#ffb800';
  if (pct <= 0.85) return '#ff6633';
  return '#ff3366';
}

interface RoomRank {
  rank: number;
  name: string;
  dailyTotal: number;
  maxCapacity: number;
  pct: number;
}

const FALLBACK_ROOMS = [
  { name: 'Area 01', dailyTotal: 170, maxCapacity: 20 },
  { name: 'Area 02', dailyTotal: 160, maxCapacity: 20 },
  { name: 'Area 03', dailyTotal: 150, maxCapacity: 20 },
  { name: 'Area 04', dailyTotal: 140, maxCapacity: 20 },
  { name: 'Area 05', dailyTotal: 130, maxCapacity: 20 },
  { name: 'Area 06', dailyTotal: 120, maxCapacity: 20 },
  { name: 'Area 07', dailyTotal: 110, maxCapacity: 20 },
  { name: 'Area 08', dailyTotal: 100, maxCapacity: 20 },
  { name: 'Area 09', dailyTotal: 90, maxCapacity: 20 },
  { name: 'Area 10', dailyTotal: 80, maxCapacity: 20 },
  { name: 'Area 11', dailyTotal: 70, maxCapacity: 20 },
  { name: 'Area 12', dailyTotal: 60, maxCapacity: 20 },
  { name: 'Area 13', dailyTotal: 50, maxCapacity: 20 },
  { name: 'Area 14', dailyTotal: 40, maxCapacity: 20 },
  { name: 'Area 15', dailyTotal: 30, maxCapacity: 20 },
  { name: 'Area 16', dailyTotal: 20, maxCapacity: 20 },
  { name: 'Area 17', dailyTotal: 10, maxCapacity: 20 },
];

export default function ModuleRanking() {
  const { data: roomsData } = trpc.footfall.roomDailyTotals.useQuery(undefined, {
    refetchInterval: 60000,
  });

  const ranks: RoomRank[] = useMemo(() => {
    const rooms = roomsData ?? FALLBACK_ROOMS;
    const sorted = [...rooms].sort((a, b) => b.dailyTotal - a.dailyTotal);
    const maxTotal = Math.max(...sorted.map((r) => r.dailyTotal), 1);
    return sorted.map((r, i) => ({
      rank: i + 1,
      name: r.name,
      dailyTotal: r.dailyTotal,
      maxCapacity: r.maxCapacity,
      pct: r.dailyTotal / maxTotal,
    }));
  }, [roomsData]);

  const pages = useMemo(() => {
    const result: RoomRank[][] = [];
    for (let i = 0; i < ranks.length; i += PAGE_SIZE) {
      result.push(ranks.slice(i, i + PAGE_SIZE));
    }
    return result.length > 0 ? result : [[]];
  }, [ranks]);

  const [pageIdx, setPageIdx] = useState(0);
  const [animating, setAnimating] = useState(false);

  useEffect(() => {
    if (pages.length <= 1) return;
    const t = setInterval(() => {
      setAnimating(true);
      setTimeout(() => {
        setPageIdx((p) => (p + 1) % pages.length);
        setAnimating(false);
      }, 380);
    }, ROTATE_MS);
    return () => clearInterval(t);
  }, [pages.length]);

  const currentPage = pages[Math.min(pageIdx, pages.length - 1)];

  return (
    <div className="panel h-full flex flex-col">
      <div className="panel-corner panel-corner-tl" />
      <div className="panel-corner panel-corner-tr" />
      <div className="panel-corner panel-corner-bl" />
      <div className="panel-corner panel-corner-br" />

      <div className="title-bar">
        <BarChart3 size={20} />
        <span>今日区域客流排行</span>
        {pages.length > 1 && (
          <span className="ml-auto text-xs text-[rgba(224,240,255,0.4)]">
            {pageIdx + 1} / {pages.length}
          </span>
        )}
      </div>

      <div
        className="flex-1 mx-2 mb-1 min-h-0 flex flex-col"
        style={{
          opacity: animating ? 0 : 1,
          transform: animating ? 'translateY(8px)' : 'translateY(0)',
          transition: 'opacity 0.35s ease, transform 0.35s ease',
        }}
      >
        {currentPage.map((room) => {
          const bc = barColor(room.pct);
          return (
            <div
              key={room.rank}
              className="flex items-center gap-1.5 py-1.5 min-h-0"
              style={{ borderLeft: `3px solid ${room.rank <= 3 ? bc : 'transparent'}` }}
            >
              <span
                className="w-6 text-center text-sm font-bold font-mono shrink-0"
                style={{ color: rankColor(room.rank) }}
              >
                {room.rank}
              </span>

              <span className="w-24 text-sm text-[rgba(224,240,255,0.85)] truncate shrink-0">
                {room.name}
              </span>

              <div className="flex-1 min-w-0 h-3 bg-[rgba(255,255,255,0.04)] relative overflow-hidden rounded-sm">
                <div
                  className="h-full rounded-sm"
                  style={{
                    width: `${room.pct * 100}%`,
                    backgroundColor: bc,
                    boxShadow: `0 0 4px ${bc}60`,
                    transition: 'width 0.8s ease',
                  }}
                />
              </div>

              <span
                className="w-12 text-right text-sm font-bold font-mono shrink-0"
                style={{ color: bc }}
              >
                {room.dailyTotal}
              </span>
            </div>
          );
        })}
      </div>

      {pages.length > 1 && (
        <div className="flex justify-center gap-1.5 pb-1.5 shrink-0">
          {pages.map((_, i) => (
            <div
              key={i}
              style={{
                width: i === pageIdx ? 16 : 6,
                height: 4,
                borderRadius: 2,
                background: i === pageIdx ? '#8BC34A' : 'rgba(139,195,74,0.25)',
                transition: 'width 0.3s ease, background 0.3s ease',
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
