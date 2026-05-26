import { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { getCampaigns, type CampaignInfo, type ResultRow, type EquityCurve, getResults, getEquity } from './api';
import { CampaignSelector } from './components/CampaignSelector';
import { Controls } from './components/Controls';
import { LiveConsole } from './components/LiveConsole';
import { ResultsTable } from './components/ResultsTable';
import { EquityCurveChart } from './components/EquityCurve';
import { FrozenPanel } from './components/FrozenPanel';

export default function App() {
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([]);
  const [selected, setSelected] = useState<string>('crypto');
  const [results, setResults] = useState<ResultRow[]>([]);
  const [selectedRow, setSelectedRow] = useState<ResultRow | null>(null);
  const [equity, setEquity] = useState<EquityCurve | null>(null);
  const [tick, setTick] = useState(0);

  // Initial + periodic campaign info
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const c = await getCampaigns();
        if (alive) setCampaigns(c);
      } catch (e) { console.error(e); }
    };
    load();
    const iv = setInterval(load, 5000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // Poll results
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await getResults(selected);
        if (alive) setResults(r);
      } catch (e) { console.error(e); }
    };
    load();
    const iv = setInterval(load, 4000);
    return () => { alive = false; clearInterval(iv); };
  }, [selected, tick]);

  // Fetch equity when row selected
  useEffect(() => {
    if (!selectedRow) { setEquity(null); return; }
    let alive = true;
    const run_id = selectedRow.run_id;
    const iter = selectedRow.iter;
    if (!run_id || !iter) { setEquity(null); return; }
    getEquity(selected, run_id, iter)
      .then(eq => { if (alive) setEquity(eq); })
      .catch(() => { if (alive) setEquity(null); });
    return () => { alive = false; };
  }, [selectedRow, selected]);

  const active = campaigns.find(c => c.name === selected) || null;

  return (
    <div className="min-h-screen p-4 md:p-6 max-w-[1600px] mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Activity className="text-accent" size={22} />
          <h1 className="text-lg font-semibold">TradingBot AutoResearch</h1>
        </div>
        <div className="flex items-center gap-3">
          <CampaignSelector
            campaigns={campaigns}
            selected={selected}
            onSelect={setSelected}
          />
        </div>
      </header>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-8 flex flex-col gap-4">
          <FrozenPanel campaign={active} />
          <Controls
            campaign={selected}
            running={active?.running ?? null}
            onStarted={() => setTick(t => t + 1)}
            onStopped={() => setTick(t => t + 1)}
          />
          <ResultsTable
            rows={results}
            selectedRunIter={selectedRow ? `${selectedRow.run_id}_${selectedRow.iter}` : null}
            onSelect={setSelectedRow}
          />
          <EquityCurveChart equity={equity} />
        </div>
        <div className="col-span-12 lg:col-span-4">
          <LiveConsole campaign={selected} />
        </div>
      </div>

      <footer className="text-xs text-muted mt-6 text-center">
        local-only · 127.0.0.1:8787 · {campaigns.length} campaigns
      </footer>
    </div>
  );
}
