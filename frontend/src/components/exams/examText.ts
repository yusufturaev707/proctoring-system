import dayjs from 'dayjs'

import type { ApiRecord } from '../../types/api'

/**
 * Imtihon sahifalari (jadval kataklari va tafsilot kartalari) uchun
 * umumiy matnlar — jadval va karta bir xil so'z bilan gapirsin.
 */

/** Daqiqani o'qiladigan shaklga: 180 → "3 soat", 150 → "2 soat 30 daq". */
export function durationText(minutes: number | null | undefined): string {
  const total = Number(minutes) || 0
  if (total <= 0) return '—'
  const hours = Math.floor(total / 60)
  const rest = total % 60
  if (!hours) return `${rest} daq`
  return rest ? `${hours} soat ${rest} daq` : `${hours} soat`
}

export type SchedulePhase = 'inactive' | 'upcoming' | 'open' | 'finished'

export interface SchedulePhaseInfo {
  phase: SchedulePhase
  label: string
  color: 'default' | 'success' | 'info' | 'warning'
  /** Kirish oynasi ochiladigan vaqt (`ExamSchedule.opens_at`). */
  opensAt: dayjs.Dayjs | null
}

/**
 * Seans hozir qaysi bosqichda.
 *
 * "Ochiq" ni server aytadi (`is_open` — `ExamSchedule.is_open`, client
 * oqimi ham shuni chaqiradi): panel brauzer soati bilan qayta hisoblasa,
 * soati noto'g'ri kompyuterda "ochiq" ko'rinib turgan seans clientda rad
 * etilardi. Brauzer soati faqat "hali ochilmagan" va "tugagan" ni
 * ajratish uchun — ikkalasi ham kirish yopiq degani.
 */
export function schedulePhase(row: ApiRecord): SchedulePhaseInfo {
  const opensAt = row.starts_at
    ? dayjs(row.starts_at).subtract(Number(row.checkin_lead_minutes) || 0, 'minute')
    : null
  if (!row.is_active) return { phase: 'inactive', label: 'Nofaol', color: 'default', opensAt }
  if (row.is_open) return { phase: 'open', label: 'Kirish ochiq', color: 'success', opensAt }
  if (row.ends_at && dayjs(row.ends_at).isBefore(dayjs())) {
    return { phase: 'finished', label: 'Tugagan', color: 'default', opensAt }
  }
  return { phase: 'upcoming', label: 'Kutilmoqda', color: 'info', opensAt }
}
