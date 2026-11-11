import { useMemo } from 'react';
import { Clock } from 'lucide-react';
import { trpc } from '@/providers/trpc';

interface HourData {
  hour: number;
  count: number;
  color: string;
}

// 根据客流量数值返回颜色（值越大越暖色，值越小越冷色）
function getColorForCount(count: number, maxCount: number): string {
  if (maxCount === 0) return '#1a3a5a';
  const ratio = count / maxCount;
  if (ratio < 0.05) return '#1a3a5a';
  if (ratio < 0.15) return '#1a4a6a';
  if (ratio < 0.25) return '#1565c0';
  if (ratio < 0.35) return '#00b4d8';
  if (ratio < 0.45) return '#8BC34A';
  if (ratio < 0.55) return '#4CAF50';
  if (ratio < 0.65) return '#88cc00';
  if (ratio < 0.75) return '#ffb800';
  if (ratio < 0.85) return '#ff8800';
  if (ratio < 0.95) return '#ff6633';
  return '#ff3366';
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
}

function describeArc(cx: number, cy: number, innerR: number, outerR: number, startAngle: number, endAngle: number) {
  const startOuter = polarToCartesian(cx, cy, outerR, endAngle);
  const endOuter = polarToCartesian(cx, cy, outerR, startAngle);
  const startInner = polarToCartesian(cx, cy, innerR, endAngle);
  const endInner = polarToCartesian(cx, cy, innerR, startAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return [
    `M ${startOuter.x} ${startOuter.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 0 ${endOuter.x} ${endOuter.y}`,
    `L ${endInner.x} ${endInner.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 1 ${startInner.x} ${startInner.y}`,
    'Z',
  ].join(' ');
}

export default function ModuleTimeDistribution() {
  const { data: apiData = [] } = trpc.footfall.hourlyTrend.useQuery(undefined, {
    refetchInterval: 60 * 1000,
  });

  const data: HourData[] = useMemo(() => {
    // apiData 是完整24小时，索引 i 即为实际小时数（0-23）
    const businessData = apiData.filter((_, i) => i >= 9 && i <= 22);
    const maxCount = Math.max(1, ...businessData.map((d) => d.count));
    return apiData.map((d, i) => ({
      hour: i,
      count: Math.max(0, d.count),
      color: (i >= 9 && i <= 22) ? getColorForCount(d.count, maxCount) : '#1a3a5a',
    }));
  }, [apiData]);

  const total = useMemo(() => data.reduce((s, d) => s + d.count, 0), [data]);
  const peakHour = useMemo(() =>
    data.length > 0 ? data.reduce((m, d) => (d.count > m.count ? d : m), data[0]) : { hour: 0, count: 0, color: '#8BC34A' }
  , [data]);

  const cx = 125;
  const cy = 115;
  const outerR = 78;
  const innerR = 42;
  const connectR = 84;
  const labelR = 102;
  const gap = 1;

  const labelBlocks = useMemo(() => {
    const blocks = [];
    for (let start = 0; start < 24; start += 4) {
      const end = Math.min(start + 3, 23);
      const blockData = data.slice(start, end + 1);
      const blockTotal = blockData.reduce((s, d) => s + d.count, 0);
      const midHour = Math.floor((start + end) / 2);
      const midAngle = (midHour + 0.5) * (360 / 24);
      const labelPos = polarToCartesian(cx, cy, labelR, midAngle);
      const connectPos = polarToCartesian(cx, cy, connectR, midAngle);
      blocks.push({
        start,
        end,
        total: blockTotal,
        labelPos,
        connectPos,
        color: data[midHour]?.color ?? '#8BC34A',
      });
    }
    return blocks;
  }, [data]);

  return (
    <div className="panel h-full flex flex-col">
      <div className="panel-corner panel-corner-tl" />
      <div className="panel-corner panel-corner-tr" />
      <div className="panel-corner panel-corner-bl" />
      <div className="panel-corner panel-corner-br" />

      <div className="title-bar !py-2">
        <Clock size={20} />
        <span>到访时段分布</span>
        <span className="ml-auto text-[14px] text-[rgba(224,240,255,0.4)] font-normal">
          峰值 <span className="text-[#ffb800] font-mono-num font-bold">{String(peakHour.hour).padStart(2, '0')}:00</span>
          <span className="text-[#8BC34A] font-mono-num ml-1">{peakHour.count}人次</span>
        </span>
      </div>

      <div className="flex-1 m-1 min-h-0 flex items-center justify-center">
        <svg viewBox="0 0 250 230" width="100%" height="100%" style={{ maxHeight: '100%' }}>
          {/* Hour segments */}
          {data.map((d, i) => {
            const startAngle = i * (360 / 24) + gap / 2;
            const endAngle = (i + 1) * (360 / 24) - gap / 2;
            return (
              <path
                key={i}
                d={describeArc(cx, cy, innerR, outerR, startAngle, endAngle)}
                fill={d.color}
                opacity={0.9}
                stroke="rgba(10,14,26,0.5)"
                strokeWidth="0.5"
              />
            );
          })}

          {/* Hour numbers */}
          {data.map((d, i) => {
            const midAngle = (i + 0.5) * (360 / 24);
            const pos = polarToCartesian(cx, cy, (innerR + outerR) / 2, midAngle);
            return (
              <text
                key={`num-${i}`}
                x={pos.x}
                y={pos.y}
                textAnchor="middle"
                dominantBaseline="central"
                fill={d.count > 35 ? '#0a0e1a' : d.count > 15 ? '#e0f0ff' : 'rgba(224,240,255,0.55)'}
                fontSize={d.count > 40 ? '8' : '7'}
                fontWeight={d.count > 30 ? '700' : '500'}
                fontFamily="JetBrains Mono, monospace"
              >
                {d.hour}
              </text>
            );
          })}

          {/* Center */}
          <circle cx={cx} cy={cy} r={innerR - 3} fill="#0a0e1a" stroke="rgba(139,195,74,0.12)" strokeWidth="1" />
          <text x={cx} y={cy - 6} textAnchor="middle" fill="rgba(224,240,255,0.4)" fontSize="11" fontFamily="JetBrains Mono">24h 总计</text>
          <text x={cx} y={cy + 8} textAnchor="middle" fill="#8BC34A" fontSize="16" fontWeight="700" fontFamily="JetBrains Mono">{total}</text>

          {/* Outer labels with connecting lines */}
          {labelBlocks.map((block, i) => {
            const isRight = block.labelPos.x > cx;
            return (
              <g key={`block-${i}`}>
                <circle cx={block.connectPos.x} cy={block.connectPos.y} r="1.5" fill={block.color} opacity="0.7" />
                <line
                  x1={block.connectPos.x}
                  y1={block.connectPos.y}
                  x2={block.labelPos.x}
                  y2={block.labelPos.y}
                  stroke={block.color}
                  strokeWidth="0.7"
                  opacity="0.5"
                />
                <circle cx={block.labelPos.x} cy={block.labelPos.y} r="2" fill={block.color} />
                <text
                  x={block.labelPos.x + (isRight ? 5 : -5)}
                  y={block.labelPos.y - 3}
                  textAnchor={isRight ? 'start' : 'end'}
                  dominantBaseline="central"
                  fill="rgba(224,240,255,0.65)"
                  fontSize="12"
                  fontFamily="JetBrains Mono, monospace"
                >
                  {String(block.start).padStart(2, '0')}:00-{String(block.end).padStart(2, '0')}:00
                </text>
                <text
                  x={block.labelPos.x + (isRight ? 5 : -5)}
                  y={block.labelPos.y + 7}
                  textAnchor={isRight ? 'start' : 'end'}
                  dominantBaseline="central"
                  fill={block.color}
                  fontSize="12"
                  fontWeight="700"
                  fontFamily="JetBrains Mono, monospace"
                >
                  {block.total}人
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
