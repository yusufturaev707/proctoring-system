import type { ApiRecord } from '../../types/api'

/**
 * Server holati sahifasi uchun formatlash va daraja hisoblash.
 *
 * Chegaralar serverdan keladi (`status.thresholds`, backend
 * `monitoring/thresholds.py`) — ranglar va `problems` ro'yxati bir-biriga
 * zid gapirmasligi uchun frontendda ikkinchi nusxa YO'Q.
 */

export type Level = 'ok' | 'warning' | 'critical' | 'unknown'

export function levelOf(thresholds: ApiRecord | undefined, key: string, value: number | null | undefined): Level {
  const rule = thresholds?.[key]
  if (value == null || !rule) return 'unknown'
  if (rule.lower_is_worse) {
    if (value <= rule.critical) return 'critical'
    if (value <= rule.warning) return 'warning'
    return 'ok'
  }
  if (value >= rule.critical) return 'critical'
  if (value >= rule.warning) return 'warning'
  return 'ok'
}

const LEVEL_RANK: Record<Level, number> = { unknown: 0, ok: 1, warning: 2, critical: 3 }

export const worst = (...levels: Level[]): Level =>
  levels.reduce<Level>((acc, item) => (LEVEL_RANK[item] > LEVEL_RANK[acc] ? item : acc), 'unknown')

/** Daraja -> palitra rangi (`success.main` va h.k.). */
export const LEVEL_COLOR: Record<Level, 'success' | 'warning' | 'error' | 'info'> = {
  ok: 'success',
  warning: 'warning',
  critical: 'error',
  unknown: 'info',
}

export const LEVEL_LABEL: Record<Level, string> = {
  ok: 'Normal',
  warning: 'Ogohlantirish',
  critical: 'Kritik',
  unknown: 'Noma’lum',
}

const NUMBER = new Intl.NumberFormat('ru-RU')

export const num = (value: number | null | undefined, digits = 0): string =>
  value == null ? '—' : NUMBER.format(Number(value.toFixed(digits)))

export const pct = (value: number | null | undefined, digits = 1): string =>
  value == null ? '—' : `${Number(value).toFixed(digits)}%`

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

export function bytes(value: number | null | undefined, digits = 1): string {
  if (value == null) return '—'
  let size = Math.abs(value)
  let unit = 0
  while (size >= 1024 && unit < BYTE_UNITS.length - 1) {
    size /= 1024
    unit += 1
  }
  const sign = value < 0 ? '−' : ''
  return unit === 0 ? `${sign}${Math.round(size)} B` : `${sign}${size.toFixed(digits)} ${BYTE_UNITS[unit]}`
}

/** Disk va xotira oqimi — bayt/s. */
export const byteRate = (value: number | null | undefined): string =>
  value == null ? '—' : `${bytes(value)}/s`

/** Tarmoq — bit/s (tarmoq uskunalari shu birlikda ko'rsatadi). */
export function bitRate(bytesPerSecond: number | null | undefined): string {
  if (bytesPerSecond == null) return '—'
  const bits = bytesPerSecond * 8
  if (bits >= 1e9) return `${(bits / 1e9).toFixed(2)} Gbit/s`
  if (bits >= 1e6) return `${(bits / 1e6).toFixed(1)} Mbit/s`
  if (bits >= 1e3) return `${(bits / 1e3).toFixed(0)} kbit/s`
  return `${Math.round(bits)} bit/s`
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} s`
  const minutes = Math.floor(s / 60)
  if (minutes < 60) return `${minutes} daq`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} soat ${minutes % 60} daq`
  const days = Math.floor(hours / 24)
  return `${days} kun ${hours % 24} soat`
}

export const ms = (value: number | null | undefined): string => {
  if (value == null) return '—'
  if (value >= 10000) return `≥ ${(value / 1000).toFixed(0)} s`
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${value.toFixed(value < 10 ? 1 : 0)} ms`
}

export const clock = (unixSeconds: number): string => {
  const date = new Date(unixSeconds * 1000)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** Ilova ma'lumoti qaysi diskda (`host.data_paths`). */
export const DATA_LABEL: Record<string, string> = {
  screenshots: 'Skrinshot va dalillar',
  logs: 'Loglar',
  app: 'Ilova kodi',
  postgres: 'PostgreSQL',
}

export const VIRT_LABEL: Record<string, string> = {
  vmware: 'VMware ESXi',
  kvm: 'KVM',
  qemu: 'QEMU',
  microsoft: 'Hyper-V',
  oracle: 'VirtualBox',
  xen: 'Xen',
}
