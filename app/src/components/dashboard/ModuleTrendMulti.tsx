import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { TrendingUp } from 'lucide-react';
import { trpc } from '@/providers/trpc';

function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[rgba(0,10,20,0.95)] border border-[rgba(139,195,74,0.3)] px-3 py-2">
        <p className="text-[11px] text-[rgba(224,240,255,0.6)]">{label}</p>
        <p className="text-lg font-mono-num text-[#8BC34A] font-bold">
          {payload[0].value} 人
        </p>
      </div>
    );
  }
  return null;
}

export default function ModuleTrendMulti() {
  const { data: allData = [] } = trpc.footfall.hourlyTrend.useQuery(undefined, {
    refetchInterval: 60 * 1000,
  });

  // 只展示营业时间段 09:00-22:00（索引9-22），非营业时段不显示
  const data = allData.slice(9, 23);

  // 动态 Y 轴上限：取当日最大值，向上取整到"好看"的刻度
  const maxCount = Math.max(...data.map((d) => d.count), 10);
  const yMax = (() => {
    const magnitude = Math.pow(10, Math.floor(Math.log10(maxCount)));
    return Math.ceil(maxCount / magnitude) * magnitude;
  })();

  return (
    <div className="panel h-full flex flex-col">
      <div className="panel-corner panel-corner-tl" />
      <div className="panel-corner panel-corner-tr" />
      <div className="panel-corner panel-corner-bl" />
      <div className="panel-corner panel-corner-br" />

      <div className="title-bar !py-2">
        <TrendingUp size={20} />
        <span>今日客流趋势</span>
        <span className="ml-auto text-xs text-[rgba(224,240,255,0.4)]">09:00 - 22:00</span>
      </div>

      <div className="flex-1 m-2 min-h-0 relative">
        <div className="absolute inset-0">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 16, right: 10, left: 0, bottom: 20 }}>
            <defs>
              <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#8BC34A" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#8BC34A" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3,3" stroke="rgba(255,255,255,0.03)" vertical={false} />
            <XAxis
              dataKey="hour"
              tick={{ fill: 'rgba(224,240,255,0.4)', fontSize: 11, fontFamily: 'JetBrains Mono' }}
              tickLine={false}
              axisLine={{ stroke: 'rgba(139,195,74,0.1)' }}
              interval={3}
            />
            <YAxis
              tick={{ fill: 'rgba(224,240,255,0.35)', fontSize: 11, fontFamily: 'JetBrains Mono' }}
              tickLine={false}
              axisLine={false}
              width={40}
              domain={[0, yMax]}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="count"
              stroke="#8BC34A"
              strokeWidth={2}
              fill="url(#areaGrad)"
              dot={{ fill: '#8BC34A', r: 3 }}
              activeDot={{ r: 5, fill: '#8BC34A', stroke: '#fff', strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
