import { useState } from 'react';
import { Play, Square, AlertCircle } from 'lucide-react';
import { startLoop, stopLoop } from '../api';

interface Props {
  campaign: string;
  running: { alive: boolean; pid: number; run_id: string } | null;
  onStarted: () => void;
  onStopped: () => void;
}

export function Controls({ campaign, running, onStarted, onStopped }: Props) {
  const [iters, setIters] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onStart = async () => {
    setBusy(true); setError(null);
    try {
      await startLoop(campaign, iters);
      onStarted();
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    setBusy(true); setError(null);
    try {
      await stopLoop(campaign);
      onStopped();
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const isRunning = !!running?.alive;

  return (
    <div className="panel p-4">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-muted">iterations</span>
        <input
          type="number"
          min={1}
          max={1000}
          value={iters}
          onChange={e => setIters(Math.max(1, Math.min(1000, Number(e.target.value) || 1)))}
          disabled={isRunning || busy}
          className="input"
        />
        {isRunning ? (
          <button onClick={onStop} disabled={busy} className="btn btn-danger">
            <Square size={14} /> Stop
          </button>
        ) : (
          <button onClick={onStart} disabled={busy} className="btn btn-primary">
            <Play size={14} /> Start
          </button>
        )}
        {isRunning && (
          <span className="chip">
            pid <span className="font-mono ml-1">{running?.pid}</span>
            <span className="mx-2 text-muted">·</span>
            run <span className="font-mono">{running?.run_id?.slice(0,8)}</span>
          </span>
        )}
        {error && (
          <span className="chip text-bad">
            <AlertCircle size={12} className="mr-1" /> {error}
          </span>
        )}
      </div>
    </div>
  );
}
