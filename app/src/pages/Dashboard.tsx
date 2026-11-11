import { useState, useEffect } from 'react';
import ParticleBackground from '@/components/dashboard/ParticleBackground';
import ModuleCamera from '@/components/dashboard/ModuleCamera';
import ModuleVLM from '@/components/dashboard/ModuleVLM';
import ModuleHeatmap from '@/components/dashboard/ModuleHeatmap';
import ModuleTrendMulti from '@/components/dashboard/ModuleTrendMulti';
import ModulePieChart from '@/components/dashboard/ModulePieChart';
import ModuleRanking from '@/components/dashboard/ModuleRanking';
import ModuleInfoPanel from '@/components/dashboard/ModuleInfoPanel';
// Seeed Studio logo is displayed via <img> tag

export default function Dashboard() {
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);


  const formatTime = (d: Date) => {
    // UTC+8: 在UTC毫秒上加8小时，再用getUTC*取值，与本地timezone无关
    const beijing = new Date(d.getTime() + 8 * 3600 * 1000);
    const p = (n: number) => String(n).padStart(2, '0');
    return `${beijing.getUTCFullYear()}-${p(beijing.getUTCMonth() + 1)}-${p(beijing.getUTCDate())} `
         + `${p(beijing.getUTCHours())}:${p(beijing.getUTCMinutes())}:${p(beijing.getUTCSeconds())}`;
  };

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#0a0e1a]">
      {/* Background layers */}
      <ParticleBackground />
      <div className="absolute inset-0 grid-bg pointer-events-none z-[1]" />

      {/* Scan line */}

      {/* Main content */}
      <div className="relative z-10 w-full h-full flex flex-col p-4 gap-3">
        {/* Header */}
        <header className="shrink-0">
          <div
            className="relative py-4 flex items-center justify-center"
            style={{
              background: 'linear-gradient(180deg, rgba(139,195,74,0.18) 0%, rgba(10,14,26,0.6) 100%)',
            }}
          >
            {/* Decorative corners */}
            <div className="absolute top-2 left-4 w-6 h-6 border-t-2 border-l-2 border-[#8BC34A]" />
            <div className="absolute top-2 right-4 w-6 h-6 border-t-2 border-r-2 border-[#8BC34A]" />

            {/* Title */}
            <div className="flex items-center">
              <img
                src="/seeed-logo.png"
                alt="Seeed Studio"
                className="h-12 object-contain absolute left-10"
                style={{ filter: 'brightness(1.4) drop-shadow(0 0 8px rgba(139, 195, 74, 0.4))' }}
              />
              <h1
                className="text-3xl lg:text-4xl 2xl:text-5xl font-bold tracking-[0.15em] uppercase whitespace-nowrap leading-none"
                style={{
                  color: '#8BC34A',
                  textShadow: '0 0 20px rgba(139, 195, 74, 0.5), 0 0 40px rgba(139, 195, 74, 0.2)',
                }}
              >
                人员统计数据大屏
              </h1>
            </div>

            {/* Real-time clock */}
            <div className="absolute right-6 top-1/2 -translate-y-1/2">
              <span className="font-mono-num text-lg text-[#4CAF50] tracking-wider">
                {formatTime(currentTime)}
              </span>
            </div>
          </div>

          {/* Gradient line under title */}
          <div className="gradient-line" />
        </header>

        {/* Main grid */}
        <div className="flex-1 min-h-0 grid gap-3" style={{ gridTemplateColumns: 'minmax(0,28fr) minmax(0,44fr) minmax(0,28fr)' }}>
          {/* Left column */}
          <div className="flex flex-col gap-3 min-h-0">
            <div className="flex-[50] min-h-0">
              <ModuleCamera />
            </div>
            <div className="flex-[50] min-h-0">
              <ModuleVLM />
            </div>
          </div>

          {/* Center column */}
          <div className="flex flex-col gap-3 min-h-0">
            <div className="flex-[60] min-h-0">
              <ModuleHeatmap />
            </div>
            <div className="flex-[40] min-h-0">
              <ModuleTrendMulti />
            </div>
          </div>

          {/* Right column */}
          <div className="flex flex-col gap-3 min-h-0">
            <div className="flex-[35] min-h-0">
              <ModulePieChart />
            </div>
            <div className="flex-[35] min-h-0">
              <ModuleRanking />
            </div>
            <div className="flex-[30] min-h-0">
              <ModuleInfoPanel />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
