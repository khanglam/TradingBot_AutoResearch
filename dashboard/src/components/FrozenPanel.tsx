import { Snowflake } from 'lucide-react';
import type { CampaignInfo } from '../api';

export function FrozenPanel({ campaign }: { campaign: CampaignInfo | null }) {
  if (!campaign) return null;
  const f = campaign.frozen;
  return (
    <div className="panel p-4">
      <div className="flex items-center gap-2 text-sm text-muted mb-3">
        <Snowflake size={14} /> frozen strategy on <span className="font-mono">main</span>
      </div>
      {!f ? (
        <div className="text-sm text-muted italic">
          No strategy promoted yet. The first candidate clearing the lockbox floors will be promoted automatically.
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="val_metric" value={f.val_metric.toFixed(4)} />
          <Stat label="lockbox_sharpe" value={f.lockbox_sharpe.toFixed(4)} />
          <Stat label="lockbox_trades" value={String(f.lockbox_trades)} />
          <Stat label="lockbox_dsr" value={f.lockbox_dsr.toFixed(4)} />
          <div className="col-span-2 md:col-span-4 text-xs text-muted">
            promoted {new Date(f.ts).toLocaleString()}
            {f.from_campaign_commit && <span> · from <span className="font-mono">{f.from_campaign_commit}</span></span>}
          </div>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
        <span className="chip font-mono">{campaign.asset}</span>
        <span className="chip font-mono">{campaign.timeframe}</span>
        {campaign.symbols?.map(s => <span key={s} className="chip font-mono">{s}</span>)}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bg border border-border rounded-md px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className="font-mono text-sm mt-1">{value}</div>
    </div>
  );
}
