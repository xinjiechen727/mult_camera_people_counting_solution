import { useMemo, useEffect, useRef, useState } from 'react';
import { Info, MapPin, AlertTriangle } from 'lucide-react';
import { trpc } from '@/providers/trpc';

export default function ModuleInfoPanel() {
  const { data: roomsData } = trpc.footfall.rooms.useQuery(undefined, { refetchInterval: 3000 });
  const rooms = roomsData ?? [];

  const { data: peakData } = trpc.footfall.todayPeak.useQuery(undefined, { refetchInterval: 60000 });
  const { data: hourlyData } = trpc.footfall.hourlyChange.useQuery(undefined, { refetchInterval: 60000 });

  const totalPeople = rooms.reduce((s, r) => s + r.currentCount, 0);

  // 滞回防抖：只有新候选负载率高出当前焦点 10 个百分点才切换，
  // 且全场最高负载率 < 15% 时不展示焦点（场馆基本空闲）
  const HYSTERESIS = 0.10;
  const MIN_FOCUS_RATE = 0.15;
  const focusRef = useRef<typeof rooms[0] | null>(null);
  const [mostCrowded, setMostCrowded] = useState<typeof rooms[0] | null>(null);

  useEffect(() => {
    if (!rooms || rooms.length === 0) return;
    const best = rooms.reduce((max, r) =>
      r.currentCount / r.maxCapacity > max.currentCount / max.maxCapacity ? r : max
    , rooms[0]);
    const bestRate = best.currentCount / best.maxCapacity;
    if (bestRate < MIN_FOCUS_RATE) {
      focusRef.current = null;
      setMostCrowded(null);
      return;
    }
    const prev = focusRef.current;
    const prevRoom = prev ? rooms.find(r => r.name === prev.name) ?? null : null;
    const prevRate = prevRoom ? prevRoom.currentCount / prevRoom.maxCapacity : 0;
    if (!prev || bestRate - prevRate > HYSTERESIS) {
      focusRef.current = best;
      setMostCrowded(best);
    } else {
      // 保持当前焦点，但更新其 currentCount（反映最新人数）
      setMostCrowded(prevRoom);
    }
  }, [rooms]);

  const crowdedPct = mostCrowded ? Math.round((mostCrowded.currentCount / mostCrowded.maxCapacity) * 100) : 0;

  const topWarning = useMemo(() => {
    const list = rooms.filter(r => r.currentCount / r.maxCapacity >= 0.6)
      .sort((a, b) => (b.currentCount / b.maxCapacity) - (a.currentCount / a.maxCapacity));
    return list[0] ? { name: list[0].name, pct: Math.round((list[0].currentCount / list[0].maxCapacity) * 100) } : null;
  }, [rooms]);

  return (
    <div className="panel h-full flex flex-col overflow-hidden">
      <div className="panel-corner panel-corner-tl" />
      <div className="panel-corner panel-corner-tr" />
      <div className="panel-corner panel-corner-bl" />
      <div className="panel-corner panel-corner-br" />

      <div className="title-bar !py-1 shrink-0">
        <Info size={20} />
        <span>综合信息面板</span>
      </div>

      <div className="flex-1 min-h-0 m-1.5 flex flex-col gap-1.5 overflow-hidden">
        {/* Section 1: Key metrics - 3 columns */}
        <div className="flex gap-1.5 shrink-0">
          <div className="flex-1 min-w-0 bg-[rgba(139,195,74,0.05)] border border-[rgba(139,195,74,0.1)] p-1.5 text-center overflow-hidden">
            <div className="text-[11px] text-[rgba(224,240,255,0.5)] truncate">在场人数</div>
            <div className="text-lg font-mono-num font-bold text-[#8BC34A] leading-tight">{totalPeople}</div>
          </div>
          <div className="flex-1 min-w-0 bg-[rgba(0,255,136,0.05)] border border-[rgba(0,255,136,0.1)] p-1.5 text-center overflow-hidden">
            <div className="text-[11px] text-[rgba(224,240,255,0.5)] truncate">小时变化</div>
            {(() => {
              const cp = hourlyData?.changePercent;
              if (cp === undefined || cp === null) {
                return <div className="text-lg font-mono-num font-bold text-[rgba(224,240,255,0.3)] leading-tight">—</div>;
              }
              const color = cp > 0 ? '#4CAF50' : cp < 0 ? '#ff3366' : 'rgba(224,240,255,0.5)';
              const label = cp > 0 ? `+${cp}%` : `${cp}%`;
              return <div className="text-lg font-mono-num font-bold leading-tight" style={{ color }}>{label}</div>;
            })()}
          </div>
          <div className="flex-1 min-w-0 bg-[rgba(255,179,0,0.05)] border border-[rgba(255,179,0,0.1)] p-1.5 text-center overflow-hidden">
            <div className="text-[11px] text-[rgba(224,240,255,0.5)] truncate">今日峰值</div>
            <div className="text-lg font-mono-num font-bold text-[#ffb800] leading-tight">{peakData?.peak ?? '—'}</div>
          </div>
        </div>

        {/* Section 2: Heat focus + warning */}
        <div className="flex-1 min-h-0 bg-[rgba(255,179,0,0.05)] border border-[rgba(255,179,0,0.1)] p-2 flex flex-col justify-center overflow-hidden">
          <div className="flex items-center gap-2 mb-1 shrink-0">
            <MapPin size={16} className="text-[#ffb800] shrink-0" />
            <span className="text-[13px] text-[#ffb800] tracking-wider">热力焦点</span>
          </div>
          {mostCrowded ? (
            <>
              <div className="flex items-center justify-between gap-1 shrink-0">
                <div className="min-w-0">
                  <div className="text-[11px] text-[rgba(224,240,255,0.5)]">最密集</div>
                  <div className="text-base font-bold text-[#ffb800] truncate">{mostCrowded.name}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[11px] text-[rgba(224,240,255,0.5)]">负载率</div>
                  <div className={`text-base font-mono-num font-bold ${crowdedPct >= 80 ? 'text-[#ff3366]' : 'text-[#ffb800]'}`}>{crowdedPct}%</div>
                </div>
              </div>
              <div className="mt-1 h-1.5 bg-[rgba(255,255,255,0.05)] overflow-hidden shrink-0">
                <div className="h-full transition-all duration-500" style={{ width: `${Math.min(crowdedPct, 100)}%`, backgroundColor: crowdedPct >= 80 ? '#ff3366' : '#ffb800' }} />
              </div>
              {topWarning && (
                <div className="mt-1 flex items-center gap-1.5 shrink-0 min-w-0 overflow-hidden">
                  <AlertTriangle size={14} className="text-[#ff3366] shrink-0" />
                  <span className="text-[12px] text-[#ff3366] truncate">{topWarning.name} 负载 {topWarning.pct}%</span>
                </div>
              )}
            </>
          ) : (
            <div className="text-[13px] text-[rgba(224,240,255,0.3)] mt-1">全场人数较少，暂无热力焦点</div>
          )}
        </div>
      </div>
    </div>
  );
}
