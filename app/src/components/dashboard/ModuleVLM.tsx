import { useEffect, useRef } from 'react';
import { Brain, Wifi, WifiOff } from 'lucide-react';
import { trpc } from '@/providers/trpc';

interface LogEntry {
  id: number;
  time: string;
  message: string;
  type: 'info' | 'detect' | 'analyze' | 'count' | 'warning';
}

// 格式化时间为 HH:MM:SS，强制北京时区
function fmtTime(d: Date | string): string {
  const date = typeof d === 'string' ? new Date(d) : d;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

function normalizeVlmMessage(text: string): string {
  return text
    .replace(/社区咖啡厅/g, '咖啡厅');
}

export default function ModuleVLM() {
  const scrollRef = useRef<HTMLDivElement>(null);

  // 获取最新日志（每3秒刷新）
  const { data: rawLogs, isLoading } = trpc.vlm.latest.useQuery(
    { limit: 50 },
    { refetchInterval: 3000 }
  );

  // 转换为前端格式
  const logs: LogEntry[] = (rawLogs ?? []).map((log) => ({
    id: log.id,
    time: fmtTime(log.timestamp),
    message: normalizeVlmMessage(log.message),
    type: (log.eventType as LogEntry['type']) || 'info',
  }));

  // 有真实数据时显示真实数据，无数据时显示提示
  const hasRealData = logs.length > 0;

  // 有新数据时回到顶部，确保最新内容可见
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [logs.length]);

  const getTypeColor = (type: string) => {
    switch (type) {
      case 'warning': return 'text-[#ff3366]';
      case 'detect': return 'text-[#ffb800]';
      case 'analyze': return 'text-[#8BC34A]';
      case 'count': return 'text-[#4CAF50]';
      default: return 'text-[rgba(224,240,255,0.5)]';
    }
  };

  return (
    <div className="panel h-full flex flex-col">
      <div className="panel-corner panel-corner-tl" />
      <div className="panel-corner panel-corner-tr" />
      <div className="panel-corner panel-corner-bl" />
      <div className="panel-corner panel-corner-br" />

      <div className="title-bar">
        <Brain size={20} />
        <span>本地VLM实时分析展示</span>
        {hasRealData ? (
          <>
            <Wifi size={14} className="ml-auto text-[#4CAF50]" />
            <span className="text-sm text-[#4CAF50]">实时接入</span>
          </>
        ) : (
          <>
            <WifiOff size={14} className="ml-auto text-[#ffb800]" />
            <span className="text-sm text-[#ffb800]">等待数据</span>
          </>
        )}
      </div>

      <div className="flex-1 m-3 bg-[rgba(0,10,20,0.9)] overflow-hidden flex flex-col">
        {/* Terminal header */}
        <div className="px-3 py-1.5 border-b border-[rgba(76,175,80,0.1)] flex items-center justify-between shrink-0">
          <span className="text-sm text-[rgba(76,175,80,0.5)] font-mono-num">local-vlm@edge</span>
          <span className="text-sm text-[rgba(76,175,80,0.4)] font-mono-num">
            {hasRealData ? `${logs.length} 条记录` : '未接入'}
          </span>
        </div>

        {/* Log content */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto p-3 font-mono text-base leading-7 min-h-0"
          style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(76,175,80,0.2) transparent' }}
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-full text-sm text-[rgba(224,240,255,0.4)]">
              正在加载分析数据...
            </div>
          ) : !hasRealData ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <WifiOff size={32} className="text-[rgba(224,240,255,0.15)]" />
              <div className="text-sm text-[rgba(224,240,255,0.4)] text-center">
                暂无 VLM 分析数据<br />
                <span className="text-xs text-[rgba(224,240,255,0.25)]">
                  POST /api/trpc/vlm.report 上报数据后此处将实时显示
                </span>
              </div>
            </div>
          ) : (
            <>
              {logs.map((log) => (
                <div key={log.id} className="flex items-start gap-2">
                  <span className="text-[rgba(224,240,255,0.4)] shrink-0 text-sm">[{log.time}]</span>
                  <span className={`${getTypeColor(log.type)} shrink-0 text-sm font-bold`}>
                    [{log.type.toUpperCase()}]
                  </span>
                  <span className="text-[#4CAF50]">{log.message}</span>
                </div>
              ))}
              <span className="text-[#4CAF50] animate-pulse">_</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
