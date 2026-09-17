import { Maximize2, Minimize2 } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';

/** Auto (reading column scales with the screen) vs full width. Desktop only. */
export function LayoutToggle() {
  const layout = useThemeStore((s) => s.layout);
  const setLayout = useThemeStore((s) => s.setLayout);
  const full = layout === 'full';
  return (
    <button
      onClick={() => setLayout(full ? 'auto' : 'full')}
      className="hidden lg:inline-flex p-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
      title={full ? 'Comfortable width' : 'Full width'}
      aria-pressed={full}
    >
      {full ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
    </button>
  );
}
