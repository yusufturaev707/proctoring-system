import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { auth } from '../api/endpoints'
import { tokens } from '../api/client'
import type { CurrentUser } from '../types/api'

export interface LoginCredentials {
  username: string
  password: string
}

export interface AuthContextValue {
  user: CurrentUser | null
  loading: boolean
  login: (credentials: LoginCredentials) => Promise<CurrentUser>
  logout: () => Promise<void>
  /** Ruxsat bormi (`*` va `guruh.*` ham). Faqat UI — himoya backendda. */
  can: (code: string) => boolean
  /** Umumiy (respublika darajasidagi) ma'lumotni o'zgartirish huquqi. */
  canShared: (code: string) => boolean
  lacksRegion: boolean
  hasPanelAccess: boolean
  isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!tokens.access()) {
      setLoading(false)
      return
    }
    auth
      .me()
      .then((data) => setUser(data as CurrentUser))
      .catch(() => tokens.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (credentials: LoginCredentials) => {
    // `surface: 'panel'` — server client rollariga (Operator) panel
    // tokenini bermaydi va aniq sabab qaytaradi (`panel_access_denied`).
    const data = await auth.login({ ...credentials, surface: 'panel' })
    tokens.set(data.access, data.refresh)
    setUser(data.user as CurrentUser)
    return data.user as CurrentUser
  }, [])

  const logout = useCallback(async () => {
    try {
      await auth.logout(tokens.refresh())
    } catch {
      // Server javob bermasa ham lokal sessiyani tozalaymiz.
    }
    tokens.clear()
    setUser(null)
  }, [])

  /**
   * Ruxsat tekshiruvi — backenddagi mantiq bilan bir xil bo'lishi shart.
   * `*` va `guruh.*` wildcard'lari qo'llab-quvvatlanadi.
   *
   * DIQQAT: bu faqat UI'ni yashirish uchun. Haqiqiy himoya backendda.
   */
  // Eski token (masalan Operator client'dagi hisobi bilan) — server
  // panelda hech narsa bermaydi (`HasPanelAccess`), UI ham hech narsa
  // ko'rsatmaydi. Maydon yo'q bo'lsa (eski backend) — ochiq deb olinadi.
  const hasPanelAccess = Boolean(user) && user?.has_panel_access !== false

  const can = useCallback(
    (code: string) => {
      if (!user || !hasPanelAccess) return false
      if (user.is_superuser) return true
      const list = user.permissions || []
      if (list.includes('*') || list.includes(code)) return true
      return list.includes(`${code.split('.')[0]}.*`)
    },
    [user, hasPanelAccess],
  )

  /**
   * UMUMIY ma'lumotni (rol, sozlama, imtihon, viloyatlar ro'yxati)
   * o'zgartirish — ruxsat kodi YETARLI EMAS, respublika darajasi ham
   * kerak (backend: `RepublicLevelWrite`). Viloyat xodimi bunday
   * sahifalarni o'qiydi, lekin «Qo'shish»/«Tahrirlash» ko'rmaydi —
   * aks holda har bir urinish 403 bilan qaytardi.
   */
  const canShared = useCallback(
    (code: string) => can(code) && !user?.is_region_scoped,
    [can, user],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login,
      logout,
      can,
      canShared,
      // Viloyat darajasidagi rol, lekin viloyat biriktirilmagan — server
      // bunday xodimga admin panelda hech narsa bermaydi.
      lacksRegion: Boolean(user?.lacks_region),
      hasPanelAccess,
      isAuthenticated: Boolean(user),
    }),
    [user, loading, login, logout, can, canShared, hasPanelAccess],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth AuthProvider ichida ishlatilishi kerak')
  return ctx
}
