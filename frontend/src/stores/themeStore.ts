import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { applyWrestler, type WrestlerChoice } from '../lib/wrestlers';

type Theme = 'light' | 'dark' | 'system';

interface ThemeState {
  theme: Theme;
  wrestler: WrestlerChoice;
  setTheme: (theme: Theme) => void;
  setWrestler: (wrestler: WrestlerChoice) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'system',
      wrestler: 'none',
      setTheme: (theme) => set({ theme }),
      setWrestler: (wrestler) => {
        applyWrestler(wrestler);
        set({ wrestler });
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
