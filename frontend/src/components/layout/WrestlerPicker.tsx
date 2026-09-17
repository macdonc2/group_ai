import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Sparkles } from 'lucide-react';
import { cn } from '../../lib/utils';
import { WRESTLER_KEYS, WRESTLERS, getWrestler } from '../../lib/wrestlers';
import { useThemeStore } from '../../stores/themeStore';

/** Header control: pick which wrestler dresses the app and voices the agent. */
export function WrestlerPicker() {
  const wrestler = useThemeStore((s) => s.wrestler);
  const setWrestler = useThemeStore((s) => s.setWrestler);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = getWrestler(wrestler);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex items-center gap-1.5 pl-1 pr-1.5 py-1 rounded-lg text-sm transition-colors touch-manipulation shrink-0',
          current
            ? 'wt-chip'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
        )}
        title={current ? `Theme: ${current.name}` : 'Pick a wrestler theme'}
      >
        {current ? (
          <img src={current.icon} alt="" className="w-7 h-7 rounded-full object-cover wt-ring" />
        ) : (
          <Sparkles size={18} className="ml-1" />
        )}
        <span className="hidden xl:inline max-w-28 truncate">{current ? current.shortName : 'Theme'}</span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-72 bg-white dark:bg-gray-800 rounded-lg shadow-lg border dark:border-gray-700 py-1 z-50">
          <div className="px-3 py-2 text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">
            Wrestler theme
          </div>
          {WRESTLER_KEYS.map((key) => {
            const w = WRESTLERS[key];
            const active = wrestler === key;
            return (
              <button
                key={key}
                onClick={() => { setWrestler(key); setOpen(false); }}
                className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-gray-700"
              >
                <img src={w.icon} alt="" className="w-9 h-9 rounded-full object-cover border-2" style={{ borderColor: w.palette.glow }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">{w.name}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 truncate">{w.tagline}</div>
                </div>
                {active && <Check size={16} className="text-green-500 shrink-0" />}
              </button>
            );
          })}
          <div className="border-t dark:border-gray-700 my-1" />
          <button
            onClick={() => { setWrestler('none'); setOpen(false); }}
            className="w-full flex items-center gap-3 px-3 py-2 text-left text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-gray-700"
          >
            <span className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center"><Sparkles size={16} /></span>
            <span className="flex-1">No theme</span>
            {wrestler === 'none' && <Check size={16} className="text-green-500" />}
          </button>
          {current && (
            <div className="px-3 pt-1 pb-2 text-[10px] text-slate-400 dark:text-slate-500">{current.credit}</div>
          )}
        </div>
      )}
    </div>
  );
}
