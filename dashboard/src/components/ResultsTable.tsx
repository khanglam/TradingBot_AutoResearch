import { useMemo } from 'react';
import { Table } from 'lucide-react';
import type { ResultRow } from '../api';

interface Props {
  rows: ResultRow[];
  selectedRunIter: string | null;
  onSelect: (r: ResultRow) => void;
}

export function ResultsTable({ rows, selectedRunIter, onSelect }: Props) {
  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
  }, [rows]);

  const bestScore = sorted.find(r => r.kept === 'true')?.score;

  return (
    <div className="panel">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Table size={14} /> results · {rows.length} iterations
        </div>
      </div>
      <div className="overflow-x-auto max-h-[40vh] overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-panel z-10 text-muted">
            <tr className="text-left">
              <th className="px-3 py-2">iter</th>
              <th className="px-3 py-2">mutation</th>
              <th className="px-3 py-2 text-right">score</th>
              <th className="px-3 py-2 text-right">sharpe</th>
              <th className="px-3 py-2 text-right">dd</th>
              <th className="px-3 py-2 text-right">trades</th>
              <th className="px-3 py-2 text-right">dsr</th>
              <th className="px-3 py-2">kept</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-muted">
                no iterations yet
              </td></tr>
            )}
            {sorted.map(r => {
              const id = `${r.run_id}_${r.iter}`;
              const isSel = id === selectedRunIter;
              const isBest = r.kept === 'true' && r.score === bestScore;
              return (
                <tr
                  key={id}
                  onClick={() => onSelect(r)}
                  className={[
                    'border-t border-border cursor-pointer hover:bg-bg',
                    isSel ? 'bg-bg' : '',
                  ].join(' ')}
                >
                  <td className="px-3 py-1.5 font-mono">{r.iter}</td>
                  <td className="px-3 py-1.5">
                    <span className="chip mr-1">{r.mutation_category || '?'}</span>
                    <span className="text-muted">{r.mutation_label}</span>
                  </td>
                  <td className={['px-3 py-1.5 text-right font-mono', isBest ? 'text-good font-semibold' : ''].join(' ')}>
                    {fmt(r.score)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmt(r.val_sharpe)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtPct(r.val_max_drawdown)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{r.val_total_trades || '0'}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmt(r.val_dsr)}</td>
                  <td className="px-3 py-1.5">
                    {r.kept === 'true'
                      ? <span className="chip text-good">kept</span>
                      : <span className="chip text-muted" title={r.discarded_reason}>
                          {r.discarded_reason || 'discarded'}
                        </span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function fmt(x: string | undefined): string {
  if (!x) return '—';
  const n = Number(x);
  if (!isFinite(n)) return '—';
  return n.toFixed(3);
}
function fmtPct(x: string | undefined): string {
  if (!x) return '—';
  const n = Number(x);
  if (!isFinite(n)) return '—';
  return (n * 100).toFixed(2) + '%';
}
