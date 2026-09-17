import { useEffect, useRef, useState } from 'react';
import { Headphones, Loader2, Pause, Play, RefreshCw } from 'lucide-react';
import { api } from '../../lib/api';
import { cn } from '../../lib/utils';

interface ListenButtonProps {
  jobId: string;
  hasAudio: boolean;
  generating: boolean;
  canGenerate: boolean;
  onGenerated: () => void;
}

function fmt(s: number): string {
  if (!isFinite(s)) return '0:00';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export function ListenButton({ jobId, hasAudio, generating, canGenerate, onGenerated }: ListenButtonProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // A new job or freshly generated audio: reload the element's source.
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    setPlaying(false);
    setTime(0);
    if (hasAudio) el.load();
  }, [jobId, hasAudio]);

  const toggle = async () => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) { el.pause(); return; }
    try { await el.play(); } catch (e) { setErr('Could not play narration.'); console.error(e); }
  };

  const generate = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.narrateResearch(jobId);
      onGenerated();
    } catch (e) {
      setErr('Narration failed. Try again.');
      console.error(e);
    } finally {
      setBusy(false);
    }
  };

  if (!hasAudio) {
    return (
      <button
        onClick={generate}
        disabled={generating || busy || !canGenerate}
        className={cn(
          'inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border transition-colors touch-manipulation',
          'border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200',
          'hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed'
        )}
        title={generating ? 'Narration is being generated' : 'Generate narration'}
      >
        {generating || busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Headphones className="w-4 h-4" />}
        <span className="hidden sm:inline">{generating || busy ? 'Generating narration…' : 'Generate narration'}</span>
        {err && <span className="text-xs text-red-500">{err}</span>}
      </button>
    );
  }

  const pct = duration > 0 ? (time / duration) * 100 : 0;

  return (
    <div className="flex items-center gap-2">
      <audio
        ref={audioRef}
        src={api.researchAudioUrl(jobId)}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onError={() => setErr('Narration unavailable.')}
      />
      <button
        onClick={toggle}
        className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors touch-manipulation"
        title={playing ? 'Pause' : 'Listen'}
      >
        {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
        <span>{playing ? 'Pause' : 'Listen'}</span>
      </button>
      <div className="hidden sm:flex items-center gap-2 min-w-[140px]">
        <div
          className="h-1.5 flex-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden cursor-pointer"
          onClick={(e) => {
            const el = audioRef.current;
            if (!el || !duration) return;
            const rect = e.currentTarget.getBoundingClientRect();
            el.currentTime = ((e.clientX - rect.left) / rect.width) * duration;
          }}
        >
          <div className="h-full bg-blue-500" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs tabular-nums text-slate-500 dark:text-slate-400">{fmt(time)} / {fmt(duration)}</span>
      </div>
      <button
        onClick={generate}
        disabled={busy}
        className="p-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded transition-colors"
        title="Regenerate narration"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
      </button>
      {err && <span className="text-xs text-red-500">{err}</span>}
    </div>
  );
}
