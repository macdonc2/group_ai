import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { applyWrestler, type WrestlerChoice } from '../lib/wrestlers';

type Theme = 'light' | 'dark' | 'system';
/** 'auto' scales the reading column with the viewport; 'full' uses every pixel. */
export type Layout = 'auto' | 'full';

interface ThemeState {
  theme: Theme;
  wrestler: WrestlerChoice;
  layout: Layout;
  setTheme: (theme: Theme) => void;
  setWrestler: (wrestler: WrestlerChoice) => void;
  setLayout: (layout: Layout) => void;
}

/** Hook for the chat layer: called after the user picks a wrestler (not on rehydrate). */
let onWrestlerChanged: ((wrestler: WrestlerChoice) => void) | null = null;
export function setWrestlerChangeListener(fn: ((wrestler: WrestlerChoice) => void) | null) {
  onWrestlerChanged = fn;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'system',
      wrestler: 'none',
      layout: 'auto',
      setTheme: (theme) => set({ theme }),
      setLayout: (layout) => set({ layout }),
      setWrestler: (wrestler) => {
        applyWrestler(wrestler);
        set({ wrestler });
        onWrestlerChanged?.(wrestler);
      },
    }),
    {
      name: 'theme-storage',
      onRehydrateStorage: () => (state) => {
        if (state) applyWrestler(state.wrestler ?? 'none');
      },
    }
  )
);

// Apply theme to document
export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  
  const isDark = theme === 'dark' || (theme === 'system' && systemDark);
  
  if (isDark) {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
}
