import { Avatar, Chip, Stack, Typography } from '@mui/material'
import WebIcon from '@mui/icons-material/WebOutlined'
import DesktopIcon from '@mui/icons-material/DesktopMacOutlined'

/**
 * Foydalanuvchi va rol jadvallari/kartalari uchun mayda bo'laklar —
 * `Users.jsx`, `Roles.jsx` va `UserDetailDialog` bir xil ko'rinishi uchun.
 */

/** "Qayerda ishlaydi": Admin panel / Desktop client (server `surfaces`). */
export function SurfaceChips({ panel, client, size = 'small' }) {
  if (!panel && !client) {
    return <Typography variant="body2" color="text.disabled">Hech qayerda</Typography>
  }
  return (
    <Stack direction="row" spacing={0.5}>
      {panel && <Chip size={size} icon={<WebIcon />} label="Panel" color="primary" variant="outlined" />}
      {client && <Chip size={size} icon={<DesktopIcon />} label="Client" color="secondary" variant="outlined" />}
    </Stack>
  )
}

/** Ism-familiyadan bosh harflar ("Toshmatov Ali" -> "AT"), bo'lmasa logindan. */
export function initialsOf(user) {
  const first = (user?.first_name || '').trim()
  const last = (user?.last_name || '').trim()
  if (first || last) return `${first[0] || ''}${last[0] || ''}`.toUpperCase()
  return (user?.username || '?').slice(0, 2).toUpperCase()
}

// Avatar rangi ID dan: bir xodim har joyda bir xil rangda (ro'yxat, karta).
const TONES = [
  ['m3.primaryContainer', 'm3.onPrimaryContainer'],
  ['m3.secondaryContainer', 'm3.onSecondaryContainer'],
  ['m3.surfaceContainerHighest', 'text.primary'],
]

export function UserAvatar({ user, size = 32 }) {
  const [bg, fg] = TONES[(Number(user?.id) || 0) % TONES.length]
  return (
    <Avatar
      sx={{
        width: size, height: size, bgcolor: bg, color: fg,
        fontSize: size * 0.4, fontWeight: 700,
        opacity: user?.is_active === false ? 0.5 : 1,
      }}
    >
      {initialsOf(user)}
    </Avatar>
  )
}
