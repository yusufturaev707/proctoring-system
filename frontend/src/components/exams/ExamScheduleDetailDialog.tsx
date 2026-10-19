import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Chip, Stack, Typography } from '@mui/material'
import EventIcon from '@mui/icons-material/EventOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'
import SeatIcon from '@mui/icons-material/EventSeatOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import LoginIcon from '@mui/icons-material/LoginOutlined'
import PlayIcon from '@mui/icons-material/PlayArrowOutlined'
import FlagIcon from '@mui/icons-material/FlagOutlined'

import DetailDialog, { StatTiles } from '../data/DetailDialog'
import type { DetailProblem } from '../data/DetailDialog'
import type { DetailDialogBaseProps } from '../data/types'
import { dateText, Field, Section } from '../data/DetailFields'
import { ActiveChip } from '../controls/ControlBits'
import { computerBookings as bookingsApi, examSchedules as schedulesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { formatDate, formatDateTime } from '../../utils/labels'
import { durationText, schedulePhase } from './examText'

/** Vaqt chizig'idagi bitta nuqta (MD3 "progress stepper"). */
function TimelineStep({
  icon, label, at, done, active,
}: { icon: ReactNode; label: string; at: dayjs.ConfigType; done: boolean; active?: boolean }) {
  return (
    <Stack alignItems="center" spacing={0.75} sx={{ flex: 1, minWidth: 0, textAlign: 'center' }}>
      <Box
        sx={{
          width: 40, height: 40, borderRadius: '50%', display: 'grid', placeItems: 'center',
          ...(active
            ? { bgcolor: 'primary.main', color: 'primary.contrastText' }
            : done
              ? { bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer' }
              : { bgcolor: 'm3.surfaceContainerHighest', color: 'text.secondary' }),
        }}
      >
        {icon}
      </Box>
      <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: '100%' }}>{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
        {at ? dayjs(at).format('HH:mm') : '—'}
      </Typography>
      {/* Sana ham: seans bir necha kunga cho'zilishi mumkin va faqat soat
          "23:05 → 00:05 → 23:55" ni bir kunda deb o'qitardi. */}
      <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
        {at ? dayjs(at).format('DD.MM.YYYY') : ''}
      </Typography>
    </Stack>
  )
}

const passed = (value: dayjs.ConfigType) => Boolean(value) && !dayjs(value).isAfter(dayjs())

/**
 * Imtihon seansi (test sessiyasi) kartasi: qachon va qayerda, kirish
 * oynasi qaysi bosqichda va bronlangan joylar soni.
 *
 * Joylar soni `computer-bookings/stats/` dan — «Kompyuter bronlari»
 * sahifasi bilan bitta manba, ya'ni ikki ekran hech qachon boshqa son
 * ko'rsatmaydi. Ruxsat (`bookings.view`) bo'lmasa plitkalar chizilmaydi.
 */
export default function ExamScheduleDetailDialog({ row, onEdit, onClose }: DetailDialogBaseProps) {
  const navigate = useNavigate()
  const { can } = useAuth()
  const canBookings = can('bookings.view')
  const deleted = Boolean(row.deleted_at)

  const { data: fresh } = useQuery({
    queryKey: ['exam-schedules', 'detail', row.id],
    queryFn: () => schedulesApi.detail(row.id),
    enabled: !deleted,
  })
  const { data: stats } = useQuery({
    queryKey: ['computer-bookings', 'stats', row.id],
    queryFn: () => bookingsApi.stats({ schedule: row.id }),
    enabled: canBookings && !deleted,
  })

  const schedule = { ...row, ...(fresh || {}) }
  const phase = schedulePhase(schedule)
  const shared = !schedule.zone

  const problems: DetailProblem[] = []
  if (deleted) {
    problems.push({ severity: 'error', text: `Seans o‘chirilgan (${dateText(schedule.deleted_at)}). Tiklash — jadvaldagi «Tiklash» tugmasi.` })
  } else {
    if (!schedule.is_active) {
      problems.push({ severity: 'warning', text: 'Seans nofaol — vaqti kelsa ham talabgor JSHSHIR kirita olmaydi.' })
    }
    if (stats && schedule.booking_required && !stats.total) {
      problems.push({
        severity: 'info',
        text: 'Bron rejimi yoqilgan, lekin seansga kompyuter biriktirilmagan — «Kompyuter bronlari» sahifasida joylarni yarating.',
      })
    }
    if (stats?.broken_booked) {
      problems.push({
        severity: 'warning',
        text: `${stats.broken_booked} ta talabgor nosoz kompyuterga biriktirilgan — ularni boshqa joyga ko‘chiring.`,
      })
    }
  }

  return (
    <DetailDialog
      icon={<EventIcon />}
      tone={deleted ? 'error' : phase.phase === 'open' ? 'success' : schedule.is_active ? 'primary' : 'neutral'}
      title={schedule.exam_name}
      subtitle={`${formatDate(schedule.exam_date)} · ${shared ? 'Barcha binolar' : [schedule.region_name, schedule.zone_name].filter(Boolean).join(' · ')}`}
      chips={<>
        {deleted
          ? <Chip size="small" color="error" label="O‘chirilgan" />
          : <Chip size="small" color={phase.color} variant={phase.phase === 'open' ? 'filled' : 'outlined'} label={phase.label} />}
        {!deleted && !schedule.is_active && <ActiveChip active={false} />}
        <Chip
          size="small"
          variant="outlined"
          label={schedule.booking_required ? 'Bron rejimi' : 'Erkin joylashuv'}
        />
        {shared && <Chip size="small" variant="outlined" color="info" label="Umumiy seans" />}
      </>}
      problems={problems}
      onEdit={deleted ? undefined : onEdit}
      onClose={onClose}
      actions={!deleted && <>
        {canBookings && (
          <Button startIcon={<SeatIcon />} onClick={() => navigate(`/computer-bookings?schedule=${schedule.id}`)}>
            Bronlar
          </Button>
        )}
        <Button
          startIcon={<HistoryIcon />}
          onClick={() => navigate(`/sessions?exam=${schedule.exam}&exam_date=${schedule.exam_date}`)}
        >
          Sessiyalar
        </Button>
      </>}
    >
      {/* Vaqt chizig'i: kirish ochiladi → imtihon boshlanadi → tugaydi. */}
      <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', p: 2, mb: 1.5 }}>
        <Stack direction="row" alignItems="flex-start">
          <TimelineStep
            icon={<LoginIcon fontSize="small" />}
            label="Kirish ochiladi"
            at={phase.opensAt?.toDate()}
            done={passed(phase.opensAt?.toDate())}
            active={phase.phase === 'open'}
          />
          <TimelineStep
            icon={<PlayIcon fontSize="small" />}
            label="Boshlanadi"
            at={schedule.starts_at}
            done={passed(schedule.starts_at)}
          />
          <TimelineStep
            icon={<FlagIcon fontSize="small" />}
            label="Tugaydi"
            at={schedule.ends_at}
            done={passed(schedule.ends_at)}
          />
        </Stack>
      </Box>

      {canBookings && !deleted && (
        <StatTiles
          items={[
            { label: 'Joylar', value: stats?.total },
            { label: 'Band', value: stats?.booked },
            { label: 'Bo‘sh', value: stats?.free },
            {
              label: 'Nosoz',
              value: stats?.broken,
              tone: stats?.broken_booked ? 'warning' : undefined,
              hint: stats?.broken_booked ? `${stats.broken_booked} tasi band` : '',
            },
            { label: 'Yakunlagan', value: stats?.finished },
          ]}
        />
      )}

      <Box sx={{ display: 'grid', columnGap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
        <Box sx={{ minWidth: 0 }}>
          <Section title="Imtihon va joy">
            <Field icon={<SchoolIcon fontSize="small" />} label="Imtihon" value={schedule.exam_name} />
            <Field
              icon={<PlaceIcon fontSize="small" />}
              label="Viloyat"
              value={schedule.region_name}
              hint={shared ? 'Barcha viloyatlar' : '—'}
            />
            <Field label="Bino" value={schedule.zone_name} hint="Barcha binolar (umumiy seans)" />
            <Field
              label="Joylashuv rejimi (imtihon profilidan)"
              value={schedule.booking_required
                ? 'Bron — talabgor faqat oldindan biriktirilgan kompyuterda'
                : 'Erkin — bo‘sh ishchi kompyuterda, joy test boshlanganda band qilinadi'}
            />
          </Section>
        </Box>

        <Box sx={{ minWidth: 0 }}>
          <Section title="Vaqt">
            <Field label="Sana" value={formatDate(schedule.exam_date)} />
            <Field label="Boshlanishi" value={formatDateTime(schedule.starts_at)} />
            <Field label="Tugashi" value={formatDateTime(schedule.ends_at)} />
            <Field
              label="Kirish oynasi"
              value={`Boshlanishdan ${schedule.checkin_lead_minutes} daq oldin${phase.opensAt ? ` · ${phase.opensAt.format('DD.MM.YYYY HH:mm')}` : ''}`}
            />
            <Field
              label="Seans davomiyligi"
              value={schedule.starts_at && schedule.ends_at
                ? durationText(dayjs(schedule.ends_at).diff(schedule.starts_at, 'minute'))
                : ''}
            />
          </Section>
        </Box>
      </Box>

      <Section title="Yozuv">
        <Field label="Yaratilgan" value={dateText(schedule.created_at)} />
        <Field label="ID" value={schedule.id} mono />
      </Section>
    </DetailDialog>
  )
}
