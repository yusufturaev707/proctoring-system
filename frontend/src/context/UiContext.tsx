import { createContext, forwardRef, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactElement, ReactNode, Ref } from 'react'
import { Alert, Slide, Snackbar } from '@mui/material'
import type { AlertColor } from '@mui/material'
import type { TransitionProps } from '@mui/material/transitions'
import { DEFAULT_PALETTE, PALETTE_KEYS } from '../theme'
import type { PaletteKey } from '../theme/palettes'
import type { DensityKey } from '../theme'

export type ModePreference = 'light' | 'dark' | 'system'

export interface UiPreferences {
  palette: PaletteKey
  mode: ModePreference
  density: DensityKey
  reduceMotion: boolean
  sidebarCollapsed: boolean
}

export interface UiContextValue extends UiPreferences {
  resolvedMode: 'light' | 'dark'
  systemDark: boolean
  setPreference: <K extends keyof UiPreferences>(key: K, value: UiPreferences[K]) => void
  toggleMode: () => void
  resetPreferences: () => void
  notify: (message: ReactNode, severity?: AlertColor) => void
  /** Axios xatosi (`userMessage`), oddiy `Error` yoki boshqa narsa. */
  notifyError: (error: unknown) => void
}

interface Toast {
  message: ReactNode
  severity: AlertColor
  key: number
}

const UiContext = createContext<UiContextValue | null>(null)

const STORAGE_KEY = 'proctoring.ui'

const DEFAULTS: UiPreferences = {
  palette: DEFAULT_PALETTE,
  mode: 'system',      // 'light' | 'dark' | 'system'
  density: 'comfortable',
  reduceMotion: false,
  // Yon panel yig'ilgan (faqat ikonkalar). Keng ekranda ham foydali:
  // jonli kuzatuv va jadval sahifalari ~190 px qo'shimcha joy oladi.
  sidebarCollapsed: false,
}

function loadPreferences(): UiPreferences {
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

export function UiProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<UiPreferences>(loadPreferences)
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  )
  const [toast, setToast] = useState<Toast | null>(null)

  // Tizim rejimi tanlangan bo'lsa, OS sozlamasi o'zgarishini kuzatamiz.
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!query) return undefined
    const handler = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    query.addEventListener('change', handler)
    return () => query.removeEventListener('change', handler)
  }, [])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
  }, [preferences])

  const resolvedMode: 'light' | 'dark' = preferences.mode === 'system' ? (systemDark ? 'dark' : 'light') : preferences.mode

  // Sahifa fonini theme yuklanishidan oldin ham to'g'ri qilish uchun
  // (birinchi renderde oq "chaqnash" bo'lmasligi kerak).
  useEffect(() => {
    document.documentElement.style.colorScheme = resolvedMode
  }, [resolvedMode])

  const setPreference = useCallback(<K extends keyof UiPreferences>(key: K, value: UiPreferences[K]) => {
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

  const notify = useCallback((message: ReactNode, severity: AlertColor = 'success') => {
    setToast({ message, severity, key: Date.now() })
  }, [])

  const notifyError = useCallback((error: unknown) => {
    const known = (error ?? {}) as { userMessage?: string; message?: string }
    setToast({
      message: known.userMessage || known.message || 'Kutilmagan xatolik',
      severity: 'error',
      key: Date.now(),
    })
  }, [])

  const value = useMemo<UiContextValue>(
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

// `forwardRef` — Snackbar o'tish komponentiga ref uzatadi (MUI shartnomasi).
const SlideUp = forwardRef(function SlideUp(
  props: TransitionProps & { children: ReactElement },
  ref: Ref<unknown>,
) {
  return <Slide {...props} ref={ref} direction="up" />
})

export const useUi = () => {
  const ctx = useContext(UiContext)
  if (!ctx) throw new Error('useUi UiProvider ichida ishlatilishi kerak')
  return ctx
}
