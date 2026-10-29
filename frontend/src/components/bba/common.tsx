import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import CircleIcon from '@mui/icons-material/Circle'

import { BBA_JOB_STATUS_LABEL, BBA_STATUS_HINT, BBA_STATUS_LABEL, fromNow } from '../../utils/labels'
import type { ChipProps } from '@mui/material'
import type { ApiRecord } from '../../types/api'

type Tone = NonNullable<ChipProps['color']>

export const BBA_STATUS_TONE: Record<string, Tone> = {
  online: 'success',
  offline_graceful: 'default',
  offline_unexpected: 'error',
  unknown: 'default',
}

export const JOB_STATUS_TONE: Record<string, Tone> = {
  pending: 'default',
  sent: 'info',
  received: 'info',
  running: 'warning',
  done: 'success',
  failed: 'error',
  timeout: 'error',
  cancelled: 'default',
  error: 'error',
}

/** Kompyuter holati: rangli nuqta + matn; Console'dan chiqarilgani — alohida belgi. */
export function BbaStatus({ device, compact }: { device: ApiRecord; compact?: boolean }) {
  const status = device.status as string
  const tone = BBA_STATUS_TONE[status] || 'default'
  const changed = device.status_changed_at ? ` · ${fromNow(device.status_changed_at)}` : ''
  if (device.revoked_at) {
    return (
      <Tooltip title="Console’dan chiqarilgan — agent sertifikati bekor qilingan">
        <Chip size="small" color="error" label="Chiqarilgan" />
      </Tooltip>
    )
  }
  return (
    <Tooltip title={`${BBA_STATUS_HINT[status] || ''}${changed}`}>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ height: '100%', minWidth: 0 }}>
        <CircleIcon
          sx={{
            fontSize: 10,
            color: tone === 'default' ? 'text.disabled' : `${tone}.main`,
            ...(status === 'online' ? { filter: 'drop-shadow(0 0 3px currentColor)' } : {}),
          }}
        />
        <Typography variant="body2" noWrap fontWeight={status === 'online' ? 600 : 400}>
          {BBA_STATUS_LABEL[status] || status}
        </Typography>
        {!compact && device.is_visible === false && (
          <Chip size="small" variant="outlined" label="Console’da ko‘rinmayapti" />
        )}
      </Stack>
    </Tooltip>
  )
}

export function JobStatusChip({ status }: { status: string }) {
  return (
    <Chip
      size="small"
      color={JOB_STATUS_TONE[status] || 'default'}
      variant={status === 'done' || status === 'failed' || status === 'error' ? 'filled' : 'outlined'}
      label={BBA_JOB_STATUS_LABEL[status] || status}
    />
  )
}

/**
 * Job natijasi — terminal ko'rinishida: stdout, keyin stderr/xato/ma'lumot/
 * chiqish kodi (faqat borlari). Console UI'dagi `resultText` bilan bir xil.
 */
export function resultText(result: unknown): string {
  if (!result || typeof result !== 'object') return result ? String(result) : ''
  const value = result as ApiRecord
  const parts: string[] = []
  if (value.stdout) parts.push(String(value.stdout).replace(/[\r\n]+$/, ''))
  if (value.stderr) parts.push(`[stderr]\n${String(value.stderr).replace(/[\r\n]+$/, '')}`)
  if (value.error) parts.push(`[xato] ${value.error}`)
  if (value.data !== undefined && value.data !== null) parts.push(JSON.stringify(value.data, null, 2))
  if (typeof value.exit_code === 'number') parts.push(`[chiqish kodi ${value.exit_code}]`)
  return parts.length ? parts.join('\n\n') : '(natija yo‘q)'
}

export function Terminal({ text, maxHeight = 260 }: { text: string; maxHeight?: number }) {
  return (
    <Box
      component="pre"
      sx={{
        m: 0, p: 1.5, maxHeight, overflow: 'auto', borderRadius: '12px',
        bgcolor: '#0f172a', color: '#e2e8f0', fontSize: 12, lineHeight: 1.5,
        fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      }}
    >
      {text}
    </Box>
  )
}

/** Firmware to'ldiruvchisi — ko'p mashinada bir xil, ID emas (`apps/bba/identity.py`). */
const PLACEHOLDERS = new Set([
  'to be filled by o.e.m.', 'default string', 'system serial number', 'system product name',
  'system manufacturer', 'base board serial number', 'chassis serial number', 'not specified',
  'not applicable', 'none', 'o.e.m.', 'oem', 'invalid', '123456789',
  '00000000-0000-0000-0000-000000000000', 'ffffffff-ffff-ffff-ffff-ffffffffffff',
  '03000200-0400-0500-0006-000700080009',
])

export function isPlaceholderId(value: unknown): boolean {
  const text = String(value ?? '').trim().toLowerCase()
  const core = text.replace(/[-_.\s{}]/g, '')
  return !core || PLACEHOLDERS.has(text) || /^0+$/.test(core) || /^f+$/.test(core)
}

export function formatBytes(value: number | null | undefined): string {
  if (!value) return ''
  const gb = value / 1e9
  return gb >= 1 ? `${gb.toFixed(gb >= 100 ? 0 : 1)} GB` : `${(value / 1e6).toFixed(0)} MB`
}

export function uptime(lastBootAt: string | null | undefined): string {
  if (!lastBootAt) return ''
  const minutes = Math.floor((Date.now() - new Date(lastBootAt).getTime()) / 60000)
  if (minutes < 0) return ''
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  if (days) return `${days} kun ${hours} soat`
  if (hours) return `${hours} soat ${minutes % 60} daqiqa`
  return `${minutes} daqiqa`
}
