import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Alert, Slide, Snackbar } from '@mui/material'
import { DEFAULT_PALETTE, PALETTE_KEYS } from '../theme'

const UiContext = createContext(null)

const STORAGE_KEY = 'proctoring.ui'

const DEFAULTS = {
  palette: DEFAULT_PALETTE,
  mode: 'system',      // 'light' | 'dark' | 'system'
  density: 'comfortable',
  reduceMotion: false,
  // Yon panel yig'ilgan (faqat ikonkalar). Keng ekranda ham foydali:
  // jonli kuzatuv va jadval sahifalari ~190 px qo'shimcha joy oladi.
  sidebarCollapsed: false,
}

function loadPreferences() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return {
      palette: PALETTE_KEYS.includes(raw.palette) ? raw.palette : DEFAULTS.palette,
      mode: ['light', 'dark', 'system'].includes(raw.mode) ? raw.mode : DEFAULTS.mode,
      density: ['comfortable', 'compact'].includes(raw.density) ? raw.density : DEFAULTS.density,
      reduceMotion: Boolean(raw.reduceMotion),
      sidebarCollapsed: Boolean(raw.sidebarCollapsed),
    }
  } catch {
    return { ...DEFAULTS }
  }
}

export function UiProvider({ children }) {
  const [preferences, setPreferences] = useState(loadPreferences)
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  )
  const [toast, setToast] = useState(null)

  // Tizim rejimi tanlangan bo'lsa, OS sozlamasi o'zgarishini kuzatamiz.
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!query) return undefined
    const handler = (event) => setSystemDark(event.matches)
    query.addEventListener('change', handler)
    return () => query.removeEventListener('change', handler)
  }, [])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
  }, [preferences])

  const resolvedMode = preferences.mode === 'system' ? (systemDark ? 'dark' : 'light') : preferences.mode

  // Sahifa fonini theme yuklanishidan oldin ham to'g'ri qilish uchun
  // (birinchi renderde oq "chaqnash" bo'lmasligi kerak).
  useEffect(() => {
    document.documentElement.style.colorScheme = resolvedMode
  }, [resolvedMode])

  const setPreference = useCallback((key, value) => {
    setPreferences((prev) => ({ ...prev, [key]: value }))
  }, [])

  const toggleMode = useCallback(() => {
    setPreferences((prev) => ({
      ...prev,
      mode: (prev.mode === 'system' ? (systemDark ? 'dark' : 'light') : prev.mode) === 'light'
        ? 'dark'
        : 'light',
    }))
  }, [systemDark])

  const resetPreferences = useCallback(() => setPreferences({ ...DEFAULTS }), [])

  const notify = useCallback((message, severity = 'success') => {
    setToast({ message, severity, key: Date.now() })
  }, [])

  const notifyError = useCallback((error) => {
    setToast({
      message: error?.userMessage || error?.message || 'Kutilmagan xatolik',
      severity: 'error',
      key: Date.now(),
    })
  }, [])

  const value = useMemo(
    () => ({
      ...preferences,
      resolvedMode,
      systemDark,
      setPreference,
      toggleMode,
      resetPreferences,
      notify,
      notifyError,
    }),
    [preferences, resolvedMode, systemDark, setPreference, toggleMode, resetPreferences, notify, notifyError],
  )

  return (
    <UiContext.Provider value={value}>
      {children}
      <Snackbar
        key={toast?.key}
        open={Boolean(toast)}
        autoHideDuration={toast?.severity === 'error' ? 6000 : 3200}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        slots={{ transition: SlideUp }}
      >
        <Alert
          severity={toast?.severity || 'info'}
          variant="filled"
          onClose={() => setToast(null)}
          sx={{ minWidth: 300, boxShadow: 6 }}
        >
          {toast?.message}
        </Alert>
      </Snackbar>
    </UiContext.Provider>
  )
}

function SlideUp(props) {
  return <Slide {...props} direction="up" />
}

export const useUi = () => {
  const ctx = useContext(UiContext)
  if (!ctx) throw new Error('useUi UiProvider ichida ishlatilishi kerak')
  return ctx
}
