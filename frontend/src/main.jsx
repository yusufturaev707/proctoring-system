import { StrictMode, useMemo } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CssBaseline, ThemeProvider } from '@mui/material'
// Shrift paket ichida: imtihon markazi tarmog'ida CDN ochilmasligi mumkin.
import '@fontsource-variable/inter'

import App from './App'
import { createAppTheme } from './theme'
import { AuthProvider } from './context/AuthContext'
import { UiProvider, useUi } from './context/UiContext'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Proktorlik ma'lumoti tez eskiradi, lekin har fokusda qayta so'rash
      // 100 ta ochiq dashboard uchun keraksiz yuklama.
      staleTime: 10_000,
      gcTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // 4xx — qayta urinish ma'nosiz (ruxsat yo'q, validatsiya xatosi).
        const status = error?.response?.status
        if (status >= 400 && status < 500) return false
        return failureCount < 2
      },
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
    mutations: { retry: false },
  },
})

function ThemedApp() {
  const { palette, resolvedMode, density } = useUi()

  const theme = useMemo(
    () => createAppTheme({ palette, mode: resolvedMode, density }),
    [palette, resolvedMode, density],
  )

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AuthProvider>
        <App />
      </AuthProvider>
    </ThemeProvider>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <UiProvider>
          <ThemedApp />
        </UiProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
