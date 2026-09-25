import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { auth } from '../api/endpoints'
import { tokens } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!tokens.access()) {
      setLoading(false)
      return
    }
    auth
      .me()
      .then(setUser)
      .catch(() => tokens.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (credentials) => {
    const data = await auth.login(credentials)
    tokens.set(data.access, data.refresh)
    setUser(data.user)
    return data.user
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
  const can = useCallback(
    (code) => {
      if (!user) return false
      if (user.is_superuser) return true
      const list = user.permissions || []
      if (list.includes('*') || list.includes(code)) return true
      return list.includes(`${code.split('.')[0]}.*`)
    },
    [user],
  )

  /**
   * UMUMIY ma'lumotni (rol, sozlama, imtihon, viloyatlar ro'yxati)
   * o'zgartirish — ruxsat kodi YETARLI EMAS, respublika darajasi ham
   * kerak (backend: `RepublicLevelWrite`). Viloyat xodimi bunday
   * sahifalarni o'qiydi, lekin «Qo'shish»/«Tahrirlash» ko'rmaydi —
   * aks holda har bir urinish 403 bilan qaytardi.
   */
  const canShared = useCallback(
    (code) => can(code) && !user?.is_region_scoped,
    [can, user],
  )

  const value = useMemo(
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
      isAuthenticated: Boolean(user),
    }),
    [user, loading, login, logout, can, canShared],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth AuthProvider ichida ishlatilishi kerak')
  return ctx
}
