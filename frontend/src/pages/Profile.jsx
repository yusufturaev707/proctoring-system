import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { alpha } from '@mui/material/styles'
import {
  Alert, Avatar, Box, Button, Card, CardContent, CardHeader, Chip, Divider,
  FormControlLabel, Grid, Stack, Switch, TextField, ToggleButton,
  ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckCircle'
import LightIcon from '@mui/icons-material/LightModeOutlined'
import DarkIcon from '@mui/icons-material/DarkModeOutlined'
import AutoIcon from '@mui/icons-material/BrightnessAutoOutlined'
import DensityLargeIcon from '@mui/icons-material/DensityMediumOutlined'
import DensitySmallIcon from '@mui/icons-material/DensitySmallOutlined'
import LockIcon from '@mui/icons-material/LockResetOutlined'
import RestoreIcon from '@mui/icons-material/SettingsBackupRestoreOutlined'
import PersonIcon from '@mui/icons-material/PersonOutline'

import PageHeader from '../components/PageHeader'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'
import { PALETTES } from '../theme'
import { users as usersApi } from '../api/endpoints'
import { formatDateTime } from '../utils/labels'

export default function Profile() {
  const { user } = useAuth()
  const {
    palette, mode, density, reduceMotion, resolvedMode,
    setPreference, resetPreferences, notify, notifyError,
  } = useUi()

  const [passwordForm, setPasswordForm] = useState({ password: '', confirm: '' })

  const passwordMutation = useMutation({
    mutationFn: (password) => usersApi.setPassword(user.id, password),
    retry: false,
    onSuccess: () => {
      notify('Parol yangilandi')
      setPasswordForm({ password: '', confirm: '' })
    },
    onError: notifyError,
  })

  const passwordMismatch =
    passwordForm.confirm.length > 0 && passwordForm.password !== passwordForm.confirm
  const passwordTooShort =
    passwordForm.password.length > 0 && passwordForm.password.length < 8

  return (
    <>
      <PageHeader
        title="Profil va sozlamalar"
        subtitle="Ko‘rinish sozlamalari faqat shu brauzerda saqlanadi"
        actions={
          <Button color="inherit" startIcon={<RestoreIcon />} onClick={resetPreferences}>
            Standartga qaytarish
          </Button>
        }
      />

      <Grid container spacing={2.5}>
        {/* ---------------- Foydalanuvchi ---------------- */}
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardHeader title="Hisob" />
            <CardContent>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2.5 }}>
                <Avatar sx={{ width: 60, height: 60, bgcolor: 'primary.main', fontSize: 24 }}>
                  {(user?.full_name || user?.username || '?').charAt(0).toUpperCase()}
                </Avatar>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="subtitle1" fontWeight={650} noWrap>
                    {user?.full_name || user?.username}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" noWrap>
                    @{user?.username}
                  </Typography>
                </Box>
              </Stack>

              <Stack spacing={1.25}>
                <InfoRow label="Rol" value={user?.role_name || 'Biriktirilmagan'} />
                <InfoRow label="Viloyat" value={user?.region_name || 'Barcha viloyatlar'} />
                <InfoRow label="Oxirgi kirish" value={formatDateTime(user?.last_login_at)} />
                <InfoRow label="IP" value={user?.last_login_ip || '—'} />
              </Stack>

              <Divider sx={{ my: 2 }} />

              {/* Superuser'da ruxsatlar ro'yxati `["*"]` — uni shundayligicha
                  ko'rsatish chalkash, chunki bu "1 ta ruxsat" degan
                  taassurot beradi. */}
              {user?.is_superuser || user?.permissions?.includes('*') ? (
                <>
                  <Typography variant="caption" color="text.secondary" fontWeight={600}>
                    RUXSATLAR
                  </Typography>
                  <Box sx={{ mt: 1 }}>
                    <Chip size="small" color="primary" label="Barcha ruxsatlar (superadmin)" />
                  </Box>
                </>
              ) : (
                <>
                  <Typography variant="caption" color="text.secondary" fontWeight={600}>
                    RUXSATLAR ({user?.permissions?.length || 0})
                  </Typography>
                  <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
                    {(user?.permissions || []).slice(0, 12).map((code) => (
                      <Chip key={code} size="small" variant="outlined" label={code} />
                    ))}
                    {(user?.permissions?.length || 0) > 12 && (
                      <Chip size="small" label={`+${user.permissions.length - 12}`} />
                    )}
                  </Stack>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* ---------------- Tema ---------------- */}
        <Grid item xs={12} md={8}>
          <Card sx={{ height: '100%' }}>
            <CardHeader
              title="Ko‘rinish"
              subheader="Rang sxemasi darhol qo‘llanadi — o‘zgarishni ko‘rish uchun saqlash shart emas"
            />
            <CardContent>
              <Typography variant="subtitle2" sx={{ mb: 1.5 }}>Rang sxemasi</Typography>
              <Grid container spacing={1.5} sx={{ mb: 3 }}>
                {Object.entries(PALETTES).map(([key, variant]) => (
                  <Grid item xs={6} sm={4} lg={2.4} key={key}>
                    <PaletteOption
                      variant={variant}
                      mode={resolvedMode}
                      selected={palette === key}
                      onSelect={() => setPreference('palette', key)}
                    />
                  </Grid>
                ))}
              </Grid>

              <Grid container spacing={3}>
                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>Yorug‘lik rejimi</Typography>
                  <ToggleButtonGroup
                    exclusive
                    fullWidth
                    value={mode}
                    onChange={(_, value) => value && setPreference('mode', value)}
                  >
                    <ToggleButton value="light"><LightIcon sx={{ mr: 0.75, fontSize: 18 }} />Kunduzgi</ToggleButton>
                    <ToggleButton value="dark"><DarkIcon sx={{ mr: 0.75, fontSize: 18 }} />Tungi</ToggleButton>
                    <Tooltip title="Operatsion tizim sozlamasiga ergashadi">
                      <ToggleButton value="system"><AutoIcon sx={{ mr: 0.75, fontSize: 18 }} />Avto</ToggleButton>
                    </Tooltip>
                  </ToggleButtonGroup>
                  {mode === 'system' && (
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: 'block' }}>
                      Hozir: {resolvedMode === 'dark' ? 'tungi' : 'kunduzgi'}
                    </Typography>
                  )}
                </Grid>

                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>Zichlik</Typography>
                  <ToggleButtonGroup
                    exclusive
                    fullWidth
                    value={density}
                    onChange={(_, value) => value && setPreference('density', value)}
                  >
                    <ToggleButton value="comfortable">
                      <DensityLargeIcon sx={{ mr: 0.75, fontSize: 18 }} />Keng
                    </ToggleButton>
                    <ToggleButton value="compact">
                      <DensitySmallIcon sx={{ mr: 0.75, fontSize: 18 }} />Ixcham
                    </ToggleButton>
                  </ToggleButtonGroup>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: 'block' }}>
                    Ixcham rejim bir ekranga ko‘proq qator sig‘diradi
                  </Typography>
                </Grid>
              </Grid>

              <Divider sx={{ my: 2.5 }} />

              <ThemePreview />
            </CardContent>
          </Card>
        </Grid>

        {/* ---------------- Parol ---------------- */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardHeader title="Parolni o‘zgartirish" subheader="Kamida 8 ta belgi" />
            <CardContent>
              <Stack spacing={2.5}>
                <Alert severity="info" icon={<LockIcon />}>
                  Parol o‘zgartirilgach, boshqa qurilmalardagi seanslar amal qilishda davom etadi.
                  Shubha bo‘lsa administratorga murojaat qiling.
                </Alert>

                <TextField
                  label="Yangi parol"
                  type="password"
                  value={passwordForm.password}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, password: event.target.value }))}
                  autoComplete="new-password"
                  error={passwordTooShort}
                  helperText={passwordTooShort ? 'Kamida 8 ta belgi' : ' '}
                />
                <TextField
                  label="Parolni tasdiqlang"
                  type="password"
                  value={passwordForm.confirm}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm: event.target.value }))}
                  autoComplete="new-password"
                  error={passwordMismatch}
                  helperText={passwordMismatch ? 'Parollar mos kelmadi' : ' '}
                />

                <Box>
                  <Button
                    variant="contained"
                    disabled={
                      passwordMutation.isPending ||
                      passwordForm.password.length < 8 ||
                      passwordMismatch ||
                      passwordForm.confirm.length === 0
                    }
                    onClick={() => passwordMutation.mutate(passwordForm.password)}
                  >
                    Parolni yangilash
                  </Button>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardHeader title="Qulaylik" />
            <CardContent>
              <Stack spacing={1}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={Boolean(reduceMotion)}
                      onChange={(event) => setPreference('reduceMotion', event.target.checked)}
                    />
                  }
                  label="Animatsiyalarni kamaytirish"
                />
                <Typography variant="body2" color="text.secondary">
                  Sahifa o‘tishlari va grafik animatsiyalari o‘chiriladi. Operatsion tizimda
                  «reduce motion» yoqilgan bo‘lsa, bu avtomatik qo‘llanadi.
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </>
  )
}

// --------------------------------------------------------------------------
function PaletteOption({ variant, mode, selected, onSelect }) {
  const colors = variant[mode] || variant.light

  return (
    <Tooltip title={variant.description}>
      <Box
        role="radio"
        aria-checked={selected}
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(event) => (event.key === 'Enter' || event.key === ' ') && onSelect()}
        sx={{
          cursor: 'pointer',
          borderRadius: 2.5,
          border: 2,
          borderColor: selected ? 'primary.main' : 'divider',
          overflow: 'hidden',
          position: 'relative',
          transition: (theme) => theme.transitions.create(['border-color', 'transform'], { duration: 140 }),
          '&:hover': { transform: 'translateY(-2px)', borderColor: 'primary.light' },
        }}
      >
        {/* Namuna: haqiqiy palitra ranglari bilan mini-interfeys */}
        <Box sx={{ bgcolor: colors.background.default, p: 1.25, pb: 1.5 }}>
          <Box
            sx={{
              height: 8, borderRadius: 999, mb: 0.75,
              bgcolor: colors.primary.main, width: '65%',
            }}
          />
          <Stack direction="row" spacing={0.5} sx={{ mb: 0.75 }}>
            <Box sx={{ height: 20, flex: 1, borderRadius: 1, bgcolor: colors.surface.raised, border: `1px solid ${colors.divider}` }} />
            <Box sx={{ height: 20, width: 20, borderRadius: 1, bgcolor: alpha(colors.primary.main, 0.85) }} />
          </Stack>
          <Stack direction="row" spacing={0.5}>
            <Box sx={{ height: 5, flex: 2, borderRadius: 999, bgcolor: alpha(colors.text.primary, 0.25) }} />
            <Box sx={{ height: 5, flex: 1, borderRadius: 999, bgcolor: colors.success.main }} />
          </Stack>
        </Box>

        <Box
          sx={{
            px: 1.25, py: 0.75,
            bgcolor: selected ? 'action.selected' : 'surface.subtle',
            borderTop: 1, borderColor: 'divider',
          }}
        >
          <Typography variant="caption" fontWeight={selected ? 700 : 500} noWrap display="block">
            {variant.label}
          </Typography>
        </Box>

        {selected && (
          <CheckIcon
            color="primary"
            sx={{
              position: 'absolute', top: 6, right: 6, fontSize: 20,
              bgcolor: 'background.paper', borderRadius: '50%',
            }}
          />
        )}
      </Box>
    </Tooltip>
  )
}

/** Tanlangan tema haqiqiy komponentlarda qanday ko'rinishini ko'rsatadi. */
function ThemePreview() {
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1.5 }}>Ko‘rinish namunasi</Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
        <Button variant="contained">Asosiy</Button>
        <Button variant="outlined">Ikkilamchi</Button>
        <Chip label="Jarayonda" color="success" />
        <Chip label="Yuqori xavf" color="warning" variant="outlined" />
        <Chip label="Chetlashtirilgan" color="error" />
        <Chip label="Ma’lumot" color="info" variant="outlined" />
        <Box sx={{ width: 120 }}>
          <Box sx={{ height: 7, borderRadius: 999, bgcolor: 'action.selected', overflow: 'hidden' }}>
            <Box sx={{ width: '68%', height: '100%', bgcolor: 'primary.main', borderRadius: 999 }} />
          </Box>
        </Box>
      </Stack>
    </Box>
  )
}

function InfoRow({ label, value }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" fontWeight={600} sx={{ textAlign: 'right' }} noWrap>
        {value}
      </Typography>
    </Stack>
  )
}
