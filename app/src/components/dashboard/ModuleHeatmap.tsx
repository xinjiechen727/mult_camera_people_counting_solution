import { useMemo } from 'react';
import { MapPin, Users, BarChart3, Calendar } from 'lucide-react';
import { trpc } from '@/providers/trpc';

interface RoomData {
  id: number;
  name: string;
  count: number;
  max: number;
  d: string;
  labelX: number;
  labelY: number;
}

// 颜色等级按日累计人次绝对值：≤250浅绿 / ≤500黄绿 / ≤750黄 / ≤1000橙 / >1000红
function getFill(count: number): string {
  if (count === 0)    return 'rgba(76,175,80,0.15)';
  if (count <= 250)   return 'rgba(76,175,80,0.35)';
  if (count <= 500)   return 'rgba(139,195,74,0.50)';
  if (count <= 750)   return 'rgba(255,184,0,0.55)';
  if (count <= 1000)  return 'rgba(255,102,51,0.60)';
  return 'rgba(255,51,102,0.65)';
}

function getStroke(count: number): string {
  if (count === 0)    return 'rgba(139,195,74,0.20)';
  if (count <= 250)   return 'rgba(76,175,80,0.60)';
  if (count <= 500)   return 'rgba(139,195,74,0.75)';
  if (count <= 750)   return 'rgba(255,184,0,0.80)';
  if (count <= 1000)  return 'rgba(255,102,51,0.90)';
  return 'rgba(255,51,102,1.0)';
}

const AREAS: Omit<RoomData, 'count' | 'd'>[] = [
  { id: 1, name: 'Area 01', max: 20, labelX: 110, labelY: 125 },
  { id: 2, name: 'Area 02', max: 20, labelX: 320, labelY: 125 },
  { id: 3, name: 'Area 03', max: 20, labelX: 530, labelY: 125 },
  { id: 4, name: 'Area 04', max: 20, labelX: 740, labelY: 125 },
  { id: 5, name: 'Area 05', max: 20, labelX: 950, labelY: 125 },
  { id: 6, name: 'Area 06', max: 20, labelX: 110, labelY: 325 },
  { id: 7, name: 'Area 07', max: 20, labelX: 320, labelY: 325 },
  { id: 8, name: 'Area 08', max: 20, labelX: 530, labelY: 325 },
  { id: 9, name: 'Area 09', max: 20, labelX: 740, labelY: 325 },
  { id: 10, name: 'Area 10', max: 20, labelX: 950, labelY: 325 },
  { id: 11, name: 'Area 11', max: 20, labelX: 110, labelY: 525 },
  { id: 12, name: 'Area 12', max: 20, labelX: 320, labelY: 525 },
  { id: 13, name: 'Area 13', max: 20, labelX: 530, labelY: 525 },
  { id: 14, name: 'Area 14', max: 20, labelX: 740, labelY: 525 },
  { id: 15, name: 'Area 15', max: 20, labelX: 950, labelY: 525 },
  { id: 16, name: 'Area 16', max: 20, labelX: 267, labelY: 725 },
  { id: 17, name: 'Area 17', max: 20, labelX: 792, labelY: 725 },
];

const PATHS = [
  'M20,40 H200 V210 H20 Z',
  'M230,40 H410 V210 H230 Z',
  'M440,40 H620 V210 H440 Z',
  'M650,40 H830 V210 H650 Z',
  'M860,40 H1040 V210 H860 Z',
  'M20,240 H200 V410 H20 Z',
  'M230,240 H410 V410 H230 Z',
  'M440,240 H620 V410 H440 Z',
  'M650,240 H830 V410 H650 Z',
  'M860,240 H1040 V410 H860 Z',
  'M20,440 H200 V610 H20 Z',
  'M230,440 H410 V610 H230 Z',
  'M440,440 H620 V610 H440 Z',
  'M650,440 H830 V610 H650 Z',
  'M860,440 H1040 V610 H860 Z',
  'M20,640 H515 V810 H20 Z',
  'M545,640 H1040 V810 H545 Z',
];

const WALL_PATH = PATHS.join(' ');


export default function ModuleHeatmap() {
  const { data: dailyData } = trpc.footfall.roomsDaily.useQuery(undefined, { refetchInterval: 10000 });
  const { data: stats } = trpc.footfall.stats.useQuery(undefined, { refetchInterval: 30000 });

  const rooms: RoomData[] = useMemo(() => {
    return AREAS.map((area, i) => ({
      ...area,
      count: Number(dailyData?.find(r => r.roomName === area.name)?.total) || 0,
      d: PATHS[i],
    }));
  }, [dailyData]);

  const totalCount = Number(stats?.dayVisitors) || 0;
  const regionCount = dailyData?.length ?? AREAS.length;

  return (
    <div className="panel h-full flex flex-col">
      <div className="panel-corner panel-corner-tl" />
      <div className="panel-corner panel-corner-tr" />
      <div className="panel-corner panel-corner-bl" />
      <div className="panel-corner panel-corner-br" />

      <div className="flex items-stretch px-4 pt-3 pb-2 gap-3">
        <div className="flex-[2] flex flex-col items-center justify-center py-3 border-b-2 border-[#8BC34A] bg-[rgba(139,195,74,0.05)]">
          <div className="flex items-center gap-2 mb-1"><Users size={18} className="text-[#8BC34A]" /><span className="text-[15px] text-[rgba(224,240,255,0.6)] uppercase tracking-wider">总客流</span></div>
          <span className="text-5xl font-bold font-mono-num text-[#8BC34A]" style={{ textShadow: '0 0 20px rgba(139,195,74,0.3)' }}>{(Number(stats?.totalVisitors) || 0).toLocaleString()}</span>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center py-2 border-b-2 border-[#4CAF50]">
          <div className="flex items-center gap-1.5 mb-1"><BarChart3 size={14} className="text-[#4CAF50]" /><span className="text-[13px] text-[rgba(224,240,255,0.5)] uppercase tracking-wider">本年客流</span></div>
          <span className="text-3xl font-bold font-mono-num text-[#4CAF50]">{(Number(stats?.yearVisitors) || 0).toLocaleString()}</span>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center py-2 border-b-2 border-[#00e5ff]">
          <div className="flex items-center gap-1.5 mb-1"><Calendar size={14} className="text-[#00e5ff]" /><span className="text-[13px] text-[rgba(224,240,255,0.5)] uppercase tracking-wider">本月客流</span></div>
          <span className="text-3xl font-bold font-mono-num text-[#00e5ff]">{(Number(stats?.monthVisitors) || 0).toLocaleString()}</span>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center py-2 border-b-2 border-[#ffb800]">
          <div className="flex items-center gap-1.5 mb-1"><Calendar size={14} className="text-[#ffb800]" /><span className="text-[13px] text-[rgba(224,240,255,0.5)] uppercase tracking-wider">本周客流</span></div>
          <span className="text-3xl font-bold font-mono-num text-[#ffb800]">{(Number(stats?.weekVisitors) || 0).toLocaleString()}</span>
        </div>
      </div>

      <div className="title-bar !py-2">
        <MapPin size={16} /><span>各区域人流热力分布</span>
        <span className="ml-auto text-xs text-[rgba(224,240,255,0.5)] font-normal">
          今日累计：<span className="text-[#8BC34A] font-bold font-mono-num">{totalCount}</span> 人次
          <span className="ml-3 text-[rgba(224,240,255,0.3)]">|</span><span className="ml-3 text-[rgba(224,240,255,0.4)]">{regionCount}个统计区域</span>
        </span>
      </div>

      <div className="flex-1 m-1 relative overflow-hidden">
        <svg viewBox="-30 -20 1140 920" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
          <g transform="scale(1.05)">
            <path d={WALL_PATH} fill="none" stroke="rgba(139,195,74,0.30)" strokeWidth="2.5" />

            {rooms.map(room => (
              <path
                key={`f-${room.id}`}
                d={room.d}
                fill={getFill(room.count)}
                stroke={getStroke(room.count)}
                strokeWidth="2.5"
                style={{ transition: 'all 0.8s ease' }}
              />
            ))}

            {rooms.map(room => (
              <g key={`l-${room.id}`}>
                <text
                  x={room.labelX}
                  y={room.labelY - 18}
                  textAnchor="middle"
                  fill="#E0F0FF"
                  fontSize="24"
                  fontWeight="600"
                  fontFamily="Inter, sans-serif"
                  style={{ textShadow: '0 2px 6px rgba(0,0,0,0.9)' }}
                >{room.name}</text>
                <text
                  x={room.labelX}
                  y={room.labelY + 22}
                  textAnchor="middle"
                  fill="#fff"
                  fontSize="38"
                  fontWeight="700"
                  fontFamily="JetBrains Mono, monospace"
                  style={{ textShadow: '0 2px 6px rgba(0,0,0,0.9)' }}
                >{room.count}</text>
              </g>
            ))}
          </g>
        </svg>

        <div className="absolute bottom-3 right-3 bg-[rgba(0,5,15,0.92)] border border-[rgba(139,195,74,0.20)] p-3">
          <div className="text-[13px] text-[rgba(224,240,255,0.7)] mb-2 text-center uppercase tracking-wider">人流等级</div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-32 rounded-sm" style={{ background: 'linear-gradient(to top, #4CAF50 0%, #4CAF50 20%, #8BC34A 20%, #8BC34A 40%, #ffb800 40%, #ffb800 60%, #ff6633 60%, #ff6633 80%, #ff3366 80%, #ff3366 100%)' }} />
            <div className="flex flex-col justify-between h-32 text-[13px] font-mono-num">
              <span className="text-[#ff3366]">满载</span>
              <span className="text-[#ff6633]">繁忙</span>
              <span className="text-[#ffb800]">拥挤</span>
              <span className="text-[#8BC34A]">正常</span>
              <span className="text-[#4CAF50]">空闲</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
