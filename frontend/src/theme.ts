import { useCallback, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'

/** Same key the inline script in index.html reads before first paint. */
const STORAGE_KEY = 'stock-analyst.theme'

/** Dark unless the user explicitly picked light — never follows the OS. */
function readTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(readTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // Storage blocked (private mode): the theme still applies for this visit.
    }
  }, [theme])

  const toggleTheme = useCallback(() => setTheme((current) => (current === 'dark' ? 'light' : 'dark')), [])

  return { theme, toggleTheme }
}
