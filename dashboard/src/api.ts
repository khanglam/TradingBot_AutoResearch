export interface FrozenMarker {
  campaign: string;
  val_metric: number;
  lockbox_sharpe: number;
  lockbox_trades: number;
  lockbox_dsr: number;
  ts: string;
  from_campaign_commit?: string;
}

export interface CampaignInfo {
  name: string;
  asset?: string;
  symbols?: string[];
  timeframe?: string;
  branch?: string;
  worktree?: string;
  frozen?: FrozenMarker | null;
  running?: { campaign: string; run_id: string; pid: number; alive: boolean } | null;
  error?: string;
}

export interface ResultRow {
  ts: string;
  run_id: string;
  iter: string;
  mutation_category: string;
  mutation_label: string;
  score: string;
  val_sharpe: string;
  val_sortino: string;
  val_calmar: string;
  val_max_drawdown: string;
  val_win_rate: string;
  val_total_trades: string;
  val_equity_final: string;
  val_psr: string;
  val_dsr: string;
  anchor_symbol: string;
  pinned_today: string;
  val_start: string;
  val_end: string;
  lockbox_start: string;
  lockbox_end: string;
  kept: string;
  discarded_reason: string;
  equity_uri: string;
  commit_sha: string;
}

export interface EquityPoint { t: string; v: number; }

export interface EquityCurve {
  campaign: string;
  run_id: string;
  iter: number;
  anchor_symbol: string;
  curve: EquityPoint[];
}

const API = '/api';

export async function getCampaigns(): Promise<CampaignInfo[]> {
  const r = await fetch(`${API}/campaigns`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getResults(campaign: string): Promise<ResultRow[]> {
  const r = await fetch(`${API}/results/${campaign}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getEquity(campaign: string, runId: string, iter: string): Promise<EquityCurve> {
  const r = await fetch(`${API}/equity/${campaign}/${runId}/${iter}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function startLoop(campaign: string, iters: number) {
  const r = await fetch(`${API}/loop/${campaign}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ iters }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function stopLoop(campaign: string) {
  const r = await fetch(`${API}/loop/${campaign}/stop`, { method: 'POST' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export function streamUrl(campaign: string, replay = false): string {
  return `${API}/stream/${campaign}${replay ? '?replay=1' : ''}`;
}
