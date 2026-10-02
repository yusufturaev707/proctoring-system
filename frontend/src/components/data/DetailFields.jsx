import { Box, IconButton, Stack, Tooltip, Typography } from '@mui/material'
import CopyIcon from '@mui/icons-material/ContentCopyOutlined'

import { useUi } from '../../context/UiContext'
import { formatDateTime, fromNow } from '../../utils/labels'

/**
 * MD3 "ro'yxat kartasi" bloklari — tafsilot varaqlari va oynalari uchun.
 *
 * Qurilma varag'i (`DeviceDetailSheet`) va kompyuter kartasi
 * (`ComputerDetailDialog`) BIR XIL ko'rinishi uchun alohida faylda: ikki
 * nusxa bo'lsa, biri yangilanib ikkinchisi eski uslubda qolardi.
 */

/** Sana + nisbiy vaqt ("2026-09-30 14:05 · 3 daqiqa oldin"). */
export const dateText = (value) => (value ? `${formatDateTime(value)} · ${fromNow(value)}` : '')

/** Nusxalash + "Nusxalandi" xabari. */
export function useCopy() {
  const { notify } = useUi()
  return async (value) => {
    try {
      await navigator.clipboard.writeText(value)
      notify('Nusxalandi')
    } catch {
      notify('Nusxalab bo‘lmadi', 'warning')
    }
  }
}

/** Sarlavhali guruh: overline yorliq + oq, 16 px yumaloq karta. */
export function Section({ title, action, children }) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Stack direction="row" alignItems="center" sx={{ px: 1, mb: 0.5 }}>
        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ flex: 1, display: 'block', lineHeight: 2, fontWeight: 700 }}
        >
          {title}
        </Typography>
        {action}
      </Stack>
      <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden' }}>
        {children}
      </Box>
    </Box>
  )
}

/**
 * Bitta qator: yorliq + qiymat (+ nusxalash).
 *
 * Bo'sh qiymat o'rniga `hint` — "yo'q" ning SABABI ("client hali
 * yubormagan"), chunki bo'sh katak administratorga hech narsa aytmaydi.
 * `warn` — nomuvofiqlik (qizil yorliq, "· mos emas").
 */
export function Field({ label, value, mono, wrap, hint, onCopy, warn, icon }) {
  const empty = value == null || value === ''
  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1.5}
      sx={{
        px: 2, py: 1.25, minHeight: 56,
        '& + &': { borderTop: 1, borderColor: 'divider' },
      }}
    >
      {icon && (
        <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>{icon}</Box>
      )}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="caption" color={warn ? 'error' : 'text.secondary'} display="block">
          {label}{warn ? ' · mos emas' : ''}
        </Typography>
        <Typography
          component="div"
          variant="body2"
          color={empty ? 'text.disabled' : 'text.primary'}
          sx={{
            fontFamily: mono && !empty ? 'monospace' : undefined,
            fontSize: mono ? 12.5 : undefined,
            wordBreak: wrap || mono ? 'break-all' : undefined,
            whiteSpace: wrap ? 'pre-wrap' : undefined,
          }}
        >
          {empty ? (hint || '—') : value}
        </Typography>
      </Box>
      {onCopy && !empty && (
        <Tooltip title="Nusxalash">
          <IconButton size="small" onClick={() => onCopy(String(value))} aria-label={`${label}ni nusxalash`}>
            <CopyIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </Stack>
  )
}

/** Sarlavhadagi 48 px tonal belgi (MD3 "leading icon container"). */
export function HeaderIcon({ children, tone = 'primary' }) {
  const palette = {
    primary: { bgcolor: 'm3.primaryContainer', color: 'primary.main' },
    success: { bgcolor: 'success.light', color: 'success.dark' },
    warning: { bgcolor: 'warning.light', color: 'warning.dark' },
    error: { bgcolor: 'error.light', color: 'error.dark' },
    neutral: { bgcolor: 'm3.surfaceContainerHighest', color: 'text.secondary' },
  }[tone]
  return (
    <Box
      sx={{
        width: 48, height: 48, borderRadius: '16px', flexShrink: 0,
        display: 'grid', placeItems: 'center', ...palette,
      }}
    >
      {children}
    </Box>
  )
}
