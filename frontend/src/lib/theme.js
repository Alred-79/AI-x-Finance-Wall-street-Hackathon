const KEY = 'sa-theme'

/** The pre-paint read lives in index.html / report.html; this is the write side. */
export function saveTheme(theme) {
  document.documentElement.dataset.theme = theme
  try { localStorage.setItem(KEY, theme) } catch { /* storage may be unavailable */ }
}

export function toggleTheme() {
  saveTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark')
}
