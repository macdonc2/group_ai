// Runs before first paint so the saved theme is applied without a flash.
// A separate file (not inline in index.html) so the Content-Security-Policy
// can forbid inline scripts outright.
(function() {
  try {
    const stored = localStorage.getItem('theme-storage');
    if (stored) {
      const { state } = JSON.parse(stored);
      const theme = state.theme;
      if (state.wrestler && state.wrestler !== 'none') {
        document.documentElement.setAttribute('data-wrestler', state.wrestler);
      }
      if (theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
      }
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.documentElement.classList.add('dark');
    }
  } catch (e) {
    // If anything fails, fall back to system preference
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.documentElement.classList.add('dark');
    }
  }
})();
