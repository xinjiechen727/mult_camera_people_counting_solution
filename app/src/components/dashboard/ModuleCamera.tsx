import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Camera, Maximize2, Minimize2 } from 'lucide-react';
import { trpc } from '@/providers/trpc';

// The iframe content needs a large viewport to render fully.
// We set a generous natural size and scale it down to fit the container.
const IFRAME_NATURAL_W = 1920;
const IFRAME_NATURAL_H = 1080;

export default function ModuleCamera() {
  const [iframeError, setIframeError] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [scale, setScale] = useState(1);

  const panelWrapRef = useRef<HTMLDivElement>(null);
  const fsWrapRef = useRef<HTMLDivElement>(null);
  const panelIframeRef = useRef<HTMLIFrameElement>(null);
  const fsIframeRef = useRef<HTMLIFrameElement>(null);

  // 直接从 reCamera 设备代理接口获取实时人数，1秒刷新，比经 DB 中转更快
  const { data: recameraData } = trpc.footfall.recameraCount.useQuery(undefined, { refetchInterval: 1000 });

  const reCount = recameraData?.count ?? 0;

  // 追踪 ID：根据真实人数生成稳定序列，不再随机跳变
  const trackingIds = useMemo(
    () => Array.from({ length: reCount }, (_, i) => 101 + i),
    [reCount]
  );

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const computeScale = useCallback(() => {
    const wrap = isFullscreen ? fsWrapRef.current : panelWrapRef.current;
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    const s = Math.min(rect.width / IFRAME_NATURAL_W, rect.height / IFRAME_NATURAL_H);
    setScale(s);
  }, [isFullscreen]);

  useEffect(() => {
    computeScale();
    const ro = new ResizeObserver(() => computeScale());
    const el = isFullscreen ? fsWrapRef.current : panelWrapRef.current;
    if (el) ro.observe(el);
    window.addEventListener('resize', computeScale);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', computeScale);
    };
  }, [isFullscreen, computeScale]);

  const handleIframeError = () => setIframeError(true);

  const refreshIframe = useCallback((ref: React.RefObject<HTMLIFrameElement | null>) => {
    if (ref.current) {
      ref.current.src = ref.current.src;
    }
  }, []);

  const toggleFullscreen = () => {
    setIsFullscreen(prev => {
      const next = !prev;
      setTimeout(() => {
        computeScale();
        refreshIframe(next ? fsIframeRef : panelIframeRef);
      }, 60);
      return next;
    });
  };

  const renderFallback = () => (
    <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0a0e1a]">
      <div className="relative w-full h-full overflow-hidden">
        {/* 本地 MP4 视频流（reCamera 离线时播放） */}
        <video
          src="/person.mp4"
          autoPlay
          loop
          muted
          playsInline
          className="absolute inset-0 w-full h-full object-cover"
          style={{ opacity: 0.9 }}
        />

        {trackingIds.map((id, i) => {
          const positions = [
            { top: '25%', left: '20%' },
            { top: '40%', left: '55%' },
            { top: '60%', left: '30%' },
            { top: '35%', left: '75%' },
          ];
          const pos = positions[i % positions.length];
          return (
            <div key={id} className="absolute" style={{ top: pos.top, left: pos.left }}>
              <div className="border-2 border-[#4CAF50] bg-[rgba(0,255,136,0.05)] px-1 py-2 w-16 h-20 relative">
                <span className="absolute -top-5 left-0 bg-[#4CAF50] text-[#0a0e1a] text-[14px] px-1.5 py-0.5 font-mono-num font-bold">
                  person {85 + i * 3}%
                </span>
                <span className="absolute -top-5 right-0 bg-[#8BC34A] text-[#0a0e1a] text-[14px] px-1.5 py-0.5 font-mono-num font-bold">
                  ID:{id}
                </span>
              </div>
            </div>
          );
        })}

        <div className="absolute top-3 left-3 bg-[rgba(0,0,0,0.7)] border border-[#8BC34A] px-3 py-2">
          <div className="text-[14px] text-[#8BC34A] uppercase tracking-wider">Person Count</div>
          <div className="text-2xl font-mono-num font-bold text-[#4CAF50]">{reCount}</div>
        </div>

        <div className="absolute bottom-3 right-3 text-[15px] font-mono-num text-[#8BC34A] bg-[rgba(0,0,0,0.6)] px-3 py-1.5">
          {currentTime.toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}
        </div>

        <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-[rgba(76,175,80,0.15)] border border-[#4CAF50] px-2 py-1">
          <span className="status-dot" />
          <span className="text-[13px] font-mono-num text-[#4CAF50]">LOCAL·AI</span>
        </div>
      </div>
    </div>
  );

  const renderIframe = (ref: React.RefObject<HTMLIFrameElement | null>) => (
    <div
      className="w-full h-full overflow-hidden relative bg-[#0a0e1a]"
      style={{ minHeight: 0 }}
    >
      {!iframeError ? (
        <div
          style={{
            width: IFRAME_NATURAL_W,
            height: IFRAME_NATURAL_H,
            transform: `scale(${scale})`,
            transformOrigin: '0 0',
          }}
        >
          <iframe
            ref={ref}
            src="http://192.168.42.1/#/dashboard"
            style={{
              width: IFRAME_NATURAL_W,
              height: IFRAME_NATURAL_H,
              border: 'none',
              display: 'block',
            }}
            onError={handleIframeError}
            sandbox="allow-scripts allow-same-origin allow-forms"
            title="reCamera Monitor"
          />
        </div>
      ) : null}
      {iframeError && renderFallback()}
    </div>
  );

  return (
    <>
      <div className="panel h-full flex flex-col">
        <div className="panel-corner panel-corner-tl" />
        <div className="panel-corner panel-corner-tr" />
        <div className="panel-corner panel-corner-bl" />
        <div className="panel-corner panel-corner-br" />

        <div className="title-bar">
          <Camera size={24} />
          <div className="flex-1 min-w-0 flex flex-col leading-tight">
            <span>本地AI隐私保护</span>
            <span className="text-xs opacity-50 font-normal tracking-normal">（基于reCamera）</span>
          </div>
          <button
            onClick={toggleFullscreen}
            className="shrink-0 flex items-center gap-1.5 px-2 py-1 text-sm text-[#8BC34A] border border-[rgba(139,195,74,0.3)] hover:bg-[rgba(139,195,74,0.1)] transition-colors"
          >
            <Maximize2 size={14} />
            全屏
          </button>
          <span className="status-dot" />
          <span className="text-sm text-[#4CAF50]">实时</span>
        </div>

        <div ref={panelWrapRef} className="flex-1 m-3 min-h-0">
          {renderIframe(panelIframeRef)}
        </div>

        <div className="px-4 py-2 border-t border-[rgba(139,195,74,0.1)] flex justify-between text-sm font-mono-num">
          <span className="text-[rgba(224,240,255,0.6)]">
            实时人数：<span className="text-[#4CAF50] font-bold">{reCount}人</span>
          </span>
          <span className="text-[rgba(224,240,255,0.6)]">
            追踪ID数量：<span className="text-[#8BC34A]">{trackingIds.length}个</span>
          </span>
        </div>
      </div>

      {isFullscreen && (
        <div className="fixed inset-0 z-[9999] bg-[#0a0e1a] flex flex-col">
          <div className="flex items-center justify-between px-6 py-3 border-b border-[rgba(139,195,74,0.2)]">
            <div className="flex items-center gap-3">
              <Camera size={24} className="text-[#8BC34A]" />
              <div className="min-w-0 flex flex-col leading-tight text-[#8BC34A]">
                <span className="text-sm font-semibold tracking-wider">本地AI隐私保护 - 全屏模式</span>
                <span className="text-xs opacity-50 font-normal tracking-normal">（基于reCamera）</span>
              </div>
              <span className="status-dot shrink-0" />
              <span className="shrink-0 text-sm text-[#4CAF50]">实时</span>
            </div>
            <button
              onClick={toggleFullscreen}
              className="shrink-0 flex items-center gap-2 px-3 py-1.5 text-sm text-[#8BC34A] border border-[rgba(139,195,74,0.3)] hover:bg-[rgba(139,195,74,0.1)] transition-colors"
            >
              <Minimize2 size={16} />
              退出全屏
            </button>
          </div>
          <div ref={fsWrapRef} className="flex-1 p-4 min-h-0">
            {renderIframe(fsIframeRef)}
          </div>
          <div className="px-6 py-2 border-t border-[rgba(139,195,74,0.1)] flex justify-between text-sm font-mono-num">
            <span className="text-[rgba(224,240,255,0.6)]">
              实时人数：<span className="text-[#4CAF50] font-bold">{reCount}人</span>
            </span>
            <span className="text-[rgba(224,240,255,0.6)]">
              缩放比例：<span className="text-[#8BC34A]">{(scale * 100).toFixed(0)}%</span>
            </span>
            <span className="text-[rgba(224,240,255,0.6)]">
              追踪ID数量：<span className="text-[#8BC34A]">{trackingIds.length}个</span>
            </span>
          </div>
        </div>
      )}
    </>
  );
}
