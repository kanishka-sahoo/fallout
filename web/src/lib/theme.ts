import { useEffect, useState } from 'react'

export type ThemePref = 'light' | 'dark' | 'system'
const KEY = 'fallout-theme'
const media = () => window.matchMedia('(prefers-color-scheme: dark)')

// Returns the stored preference, a setter, and the theme actually in effect.
export function useTheme(): [ThemePref, (t: ThemePref) => void, 'light' | 'dark'] {
  const [pref, setPref] = useState<ThemePref>(() => (localStorage.getItem(KEY) as ThemePref) ?? 'system')
  const [systemDark, setSystemDark] = useState(() => media().matches)
  useEffect(() => {
    const m = media()
    const on = () => setSystemDark(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  const resolved = pref === 'system' ? (systemDark ? 'dark' : 'light') : pref
  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [resolved])
  return [pref, (t) => { localStorage.setItem(KEY, t); setPref(t) }, resolved]
}
