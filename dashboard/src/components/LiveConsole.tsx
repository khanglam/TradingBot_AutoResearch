import { useEffect, useRef, useState } from 'react';
import { Terminal } from 'lucide-react';
import { streamUrl } from '../api';

interface LogRecord {
  ts: number;
  run_id: string;
  iter: number;
  event: string;
  payload: Record<string, any>;
}

const EVENT_COLORS: Record<string, string> = {
  run_start: 'text-accent',
  run_end: 'text-accent',
  llm_call: 'text-warn',
  llm_chunk: 'text-muted',
  llm_response: 'text-muted',
  diff_applied: 'text-text',
  backtest_result: 'text-text',
  kept: 'text-good',
  discarded: 'text-muted',
  error: 'text-bad',
  iter_start: 'text-muted',
  iter_end: 'text-muted',
  config_loaded: 'text-muted',
};

const MAX_LINES = 800;

export function LiveConsole({ campaign }: { campaign: string }) {
  const [lines, setLines] = useState<LogRecord[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setLines([]);
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
    const es = new EventSource(streamUrl(campaign, true));
    esRef.current = es;
    es.onmessage = (ev) => {
      try {
        const rec = JSON.parse(ev.data) as LogRecord;
        setLines(prev => {
          const next = [...prev, rec];
          if (next.length > MAX_LINES) next.splice(0, next.length - MAX_LINES);
          return next;
        });
      } catch { /* skip malformed */ }
    };
    es.onerror = () => { /* silent reconnect */ };
    return () => { es.close(); esRef.current = null; };
  }, [campaign]);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="panel h-[80vh] flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Terminal size={14} /> live console · {campaign}
        </div>
        <span className="chip text-xs">{lines.length} events</span>
      </div>
      <div ref={ref} className="flex-1 overflow-y-auto font-mono text-xs px-3 py-2 leading-relaxed">
        {lines.length === 0 && (
          <div className="text-muted">waiting for events…</div>
        )}
        {lines.map((rec, i) => {
          const color = EVENT_COLORS[rec.event] ?? 'text-text';
          const ts = new Date(rec.ts * 1000).toISOString().slice(11, 19);
          const summary = formatPayload(rec.event, rec.payload);
          if (rec.event === 'llm_chunk') return null;
          return (
            <div key={i} className="flex gap-2 whitespace-pre-wrap break-all">
              <span className="text-muted">{ts}</span>
              <span className="text-muted">i{rec.iter}</span>
              <span className={color}>{rec.event}</span>
              {summary && <span className="text-text">{summary}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatPayload(event: string, p: Record<string, any>): string {
  if (!p) return '';
  if (event === 'backtest_result')
    return `score=${fmt(p.score)} sharpe=${fmt(p.sharpe)} dd=${fmt(p.max_dd)} trades=${p.trades} dsr=${fmt(p.dsr)}`;
  if (event === 'kept') return `score=${fmt(p.score)} sha=${p.sha ?? ''}`;
  if (event === 'discarded') return `reason=${p.reason} score=${fmt(p.score)}`;
  if (event === 'diff_applied') return `${p.mode} ${p.file}`;
  if (event === 'llm_response') return `chars=${p.chars}`;
  if (event === 'error') return `${p.kind}: ${p.message}`;
  if (event === 'config_loaded') return `today=${p.pinned_today} val=${p.val_start}..${p.val_end}`;
  return Object.entries(p).map(([k, v]) => `${k}=${v}`).join(' ');
}

function fmt(x: any): string {
  if (typeof x === 'number') return x.toFixed(4);
  return String(x);
}
