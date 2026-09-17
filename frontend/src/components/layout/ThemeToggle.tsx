import { useEffect } from 'react';
import { Moon, Sun, Monitor } from 'lucide-react';
import { useThemeStore, applyTheme } from '../../stores/themeStore';
import { cn } from '../../lib/utils';

export function ThemeToggle() {
  const { theme, setTheme } = useThemeStore();
  
  // Apply theme on mount and when it changes
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  
  // Listen for system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => {
      if (theme === 'system') {
        applyTheme('system');
      }
    };
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, [theme]);
  
  const options = [
    { value: 'light' as const, icon: Sun, label: 'Light' },
    { value: 'dark' as const, icon: Moon, label: 'Dark' },
    { value: 'system' as const, icon: Monitor, label: 'System' },
  ];
  
  // Phones: one button that cycles light → dark → system, so the header fits.
  const current = options.find((o) => o.value === theme) ?? options[2];
  const next = options[(options.findIndex((o) => o.value === theme) + 1) % options.length];
  const CurrentIcon = current.icon;

  return (
    <>
    <button
      onClick={() => setTheme(next.value)}
      className="sm:hidden p-2 rounded-md text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700"
      title={`Theme: ${current.label} (tap for ${next.label})`}
    >
      <CurrentIcon className="w-4 h-4" />
    </button>
    <div className="hidden sm:flex items-center gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-lg">
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          onClick={() => setTheme(value)}
          className={cn(
            'p-1.5 rounded-md transition-colors',
            theme === value
              ? 'bg-white dark:bg-slate-700 shadow-sm text-slate-900 dark:text-white'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          )}
          title={label}
        >
          <Icon className="w-4 h-4" />
        </button>
      ))}
    </div>
    </>
  );
}
