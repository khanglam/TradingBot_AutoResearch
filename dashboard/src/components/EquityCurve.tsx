import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { TrendingUp } from 'lucide-react';
import type { EquityCurve } from '../api';

export function EquityCurveChart({ equity }: { equity: EquityCurve | null }) {
  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-sm text-muted">
          <TrendingUp size={14} /> equity curve
          {equity && <span className="chip ml-2 font-mono">{equity.anchor_symbol}</span>}
        </div>
        {equity && (
          <span className="text-xs text-muted">
            run {equity.run_id.slice(0,8)} · iter {equity.iter} · {equity.curve.length} bars
          </span>
        )}
      </div>
      <div className="h-64">
        {!equity || equity.curve.length === 0 ? (
          <div className="h-full grid place-items-center text-muted text-sm">
            select a result row to render equity
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={equity.curve} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid stroke="#1f1f24" strokeDasharray="3 3" />
              <XAxis
                dataKey="t"
                tick={{ fontSize: 10, fill: '#8a8a93' }}
                tickFormatter={(t) => t.slice(0, 10)}
                minTickGap={50}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#8a8a93' }}
                domain={['auto', 'auto']}
                tickFormatter={(v) => v.toFixed(0)}
              />
              <Tooltip
                contentStyle={{ background: '#111114', border: '1px solid #1f1f24', fontSize: 12 }}
                labelStyle={{ color: '#8a8a93' }}
                formatter={(v: any) => Number(v).toFixed(2)}
              />
              <Line type="monotone" dataKey="v" stroke="#7c5cff" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
