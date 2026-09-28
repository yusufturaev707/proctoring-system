import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import {
  Alert, Box, Button, Card, CardContent, CircularProgress, InputAdornment,
  IconButton, Stack, TextField, Typography,
} from '@mui/material'
import ShieldIcon from '@mui/icons-material/GppGoodOutlined'
import VisibilityIcon from '@mui/icons-material/VisibilityOutlined'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOffOutlined'

import { useAuth } from '../context/AuthContext'

export default function Login() {
  const navigate = useNavigate()
  const { login, isAuthenticated, loading: authLoading } = useAuth()

  const [form, setForm] = useState({ username: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (authLoading) {
    return (
      <Box sx={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    )
  }
  if (isAuthenticated) return <Navigate to="/" replace />

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(form)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.userMessage || 'Kirishda xatolik')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        p: 2,
        // Fon TEMADAN: ilgari qattiq yozilgan ko'k gradient edi va
        // yashil sxemada kirish sahifasi boshqa mahsulotdek ko'rinardi.
        background: (theme) =>
          `radial-gradient(1200px 600px at 10% -10%, ${theme.palette.m3.primaryContainer} 0%, transparent 60%),
           radial-gradient(900px 500px at 110% 110%, ${theme.palette.m3.secondaryContainer} 0%, transparent 55%),
           ${theme.palette.background.default}`,
      }}
    >
      <Card sx={{ width: '100%', maxWidth: 420, borderRadius: '28px', bgcolor: 'm3.surfaceContainerLowest' }}>
        <CardContent sx={{ p: { xs: 3, sm: 4.5 }, '&:last-child': { pb: { xs: 3, sm: 4.5 } } }}>
          <Stack spacing={1} alignItems="center" sx={{ mb: 3.5 }}>
            <Box
              sx={{
                width: 56, height: 56, borderRadius: '16px', display: 'grid', placeItems: 'center', mb: 1,
                bgcolor: 'primary.main', color: 'primary.contrastText',
              }}
            >
              <ShieldIcon fontSize="large" />
            </Box>
            <Typography variant="h5" component="h1">Proctoring</Typography>
            <Typography variant="body2" color="text.secondary">
              Imtihon nazorati tizimiga kirish
            </Typography>
          </Stack>

          <form onSubmit={handleSubmit}>
            <Stack spacing={2.5}>
              {error && <Alert severity="error">{error}</Alert>}

              <TextField
                label="Login"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                autoFocus
                required
                autoComplete="username"
              />
              <TextField
                label="Parol"
                type={showPassword ? 'text' : 'password'}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
                autoComplete="current-password"
                InputProps={{
                  minLength: 3,
                  maxLength: 128,
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setShowPassword((p) => !p)} edge="end">
                        {showPassword ? <VisibilityOffIcon /> : <VisibilityIcon />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />

              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={submitting}
                startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
              >
                {submitting ? 'Tekshirilmoqda…' : 'Kirish'}
              </Button>
            </Stack>
          </form>
        </CardContent>
      </Card>
    </Box>
  )
}
