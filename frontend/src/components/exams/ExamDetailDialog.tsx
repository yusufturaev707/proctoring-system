import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Chip, Skeleton, Stack } from '@mui/material'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import EventIcon from '@mui/icons-material/EventOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import LinkIcon from '@mui/icons-material/LinkOutlined'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import ImageIcon from '@mui/icons-material/ImageOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import GavelIcon from '@mui/icons-material/GavelOutlined'

import DetailDialog, { InfoNote, StatTiles } from '../data/DetailDialog'
import type { DetailProblem } from '../data/DetailDialog'
import type { DetailDialogBaseProps } from '../data/types'
import { dateText, Field, Section, useCopy } from '../data/DetailFields'
import { ActiveChip } from '../controls/ControlBits'
import { examSchedules as schedulesApi, exams as examsApi } from '../../api/endpoints'
import { formatDate, formatTime } from '../../utils/labels'
import { durationText, schedulePhase } from './examText'
import type { ApiRecord } from '../../types/api'

/** Kartada ko'rsatiladigan oxirgi seanslar soni — to'liq ro'yxat «Seanslar» sahifasida. */
const RECENT_SCHEDULES = 5

/**
 * Imtihon kartasi: tashqi platforma bilan bog'lanish (tekshiruv API,
 * sarlavha, resurs domenlari), proktorlik profili va oxirgi seanslar.
 *
 * Karta "nega ishlamayapti" savoliga birinchi javob beradi: sarlavha
 * sozlanmagan bo'lsa platforma so'rovni 401 bilan qaytaradi va operator
 * JSHSHIR tekshiruvida faqat umumiy xatoni ko'radi — sabab shu yerda.
 */
export default function ExamDetailDialog({ row, onEdit, onClose }: DetailDialogBaseProps) {
  const navigate = useNavigate()
  const copy = useCopy()
  const deleted = Boolean(row.deleted_at)

  const { data: fresh } = useQuery({
    queryKey: ['exams', 'detail', row.id],
    queryFn: () => examsApi.detail(row.id),
    enabled: !deleted,
  })
  const { data: schedulesPage, isLoading: schedulesLoading } = useQuery({
    queryKey: ['exam-schedules', 'by-exam', row.id],
    queryFn: () => schedulesApi.list({ exam: row.id, ordering: '-exam_date', page_size: RECENT_SCHEDULES }),
    enabled: !deleted,
  })

  const exam = { ...row, ...(fresh || {}) }
  const schedules: ApiRecord[] = schedulesPage?.results || []
  const schedulesCount = schedulesPage?.count ?? schedules.length
  const domains: string[] = exam.resource_domains || []

  const problems: DetailProblem[] = []
  if (deleted) {
    problems.push({ severity: 'error', text: `Imtihon o‘chirilgan (${dateText(exam.deleted_at)}). Tiklash — jadvaldagi «Tiklash» tugmasi.` })
  } else {
    if (!exam.is_active) {
      problems.push({
        severity: 'warning',
        text: 'Imtihon nofaol — operator uni client dasturda tanlay olmaydi.',
      })
    }
    if (!exam.site_header_masked) {
      problems.push({
        severity: 'warning',
        text: 'Platforma sarlavhasi (token) o‘rnatilmagan: platforma talab qilsa JSHSHIR tekshiruvi 401 bilan rad etiladi.',
      })
    }
    if (!exam.offer_title) {
      problems.push({
        severity: 'info',
        text: 'Oferta biriktirilmagan — talabgordan shaxsga doir ma’lumotlarni qayta ishlashga rozilik so‘ralmaydi.',
      })
    } else if (!exam.offer_is_active) {
      problems.push({
        severity: 'warning',
        text: `«${exam.offer_title}» ofertasi nofaol — talabgordan rozilik so‘ralmaydi. «Oferta» sahifasida yoqing.`,
      })
    }
    if (schedulesPage && !schedulesCount) {
      problems.push({
        severity: 'info',
        text: 'Seans yaratilmagan — kirish oynasi yo‘q. Jadval majburiy bo‘lsa (REQUIRE_EXAM_SCHEDULE) talabgor JSHSHIR kirita olmaydi.',
      })
    }
  }

  return (
    <DetailDialog
      icon={<SchoolIcon />}
      tone={deleted ? 'error' : exam.is_active ? 'primary' : 'neutral'}
      title={exam.name}
      subtitle={exam.exam_type_name || 'Turi belgilanmagan'}
      chips={<>
        {deleted ? <Chip size="small" color="error" label="O‘chirilgan" /> : <ActiveChip active={exam.is_active} />}
        <Chip size="small" variant="outlined" label={durationText(exam.duration_minutes)} />
        {exam.site_header_masked
          ? <Chip size="small" variant="outlined" color="success" icon={<KeyIcon />} label="Token o‘rnatilgan" />
          : <Chip size="small" variant="outlined" color="warning" icon={<KeyIcon />} label="Token yo‘q" />}
      </>}
      problems={problems}
      onEdit={deleted ? undefined : onEdit}
      onClose={onClose}
      actions={!deleted && <>
        <Button startIcon={<EventIcon />} onClick={() => navigate(`/exam-schedules?f.exam=${exam.id}`)}>
          Seanslar
        </Button>
        <Button startIcon={<HistoryIcon />} onClick={() => navigate(`/sessions?exam=${exam.id}`)}>
          Sessiyalar
        </Button>
      </>}
    >
      <StatTiles
        items={[
          // Davomiylik sarlavha chipida va «Sozlamalar» da bor — o'rniga oferta holati.
          { label: 'Oferta', value: exam.offer_title ? (exam.offer_is_active ? 'Bor' : 'Nofaol') : 'Yo‘q' },
          { label: 'Seanslar', value: schedulesLoading ? undefined : schedulesCount },
          { label: 'Sessiyalar', value: exam.sessions_count ?? 0 },
          { label: 'Resurs domenlari', value: domains.length },
        ]}
      />

      <Box sx={{ display: 'grid', columnGap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
        <Box sx={{ minWidth: 0 }}>
          <Section title="Asosiy">
            <Field label="Nomi" value={exam.name} />
            <Field label="Imtihon turi" value={exam.exam_type_name} hint="Belgilanmagan" />
            <Field label="Ichki kalit" value={exam.key} hint="Kiritilmagan" mono onCopy={copy} />
            <Field label="Tashqi platforma kodi" value={exam.external_code} hint="Kiritilmagan" mono onCopy={copy} />
          </Section>

          <Section title="Sozlamalar">
            <Field icon={<TuneIcon fontSize="small" />} label="Proktorlik profili" value={exam.setting_name} hint="Global standart qo‘llanadi" />
            <Field
              icon={<GavelIcon fontSize="small" />}
              label="Oferta — yuz tekshiruvidan oldin rozilik"
              value={exam.offer_title ? `${exam.offer_title}${exam.offer_is_active ? '' : ' (nofaol)'}` : ''}
              hint="Biriktirilmagan — rozilik so‘ralmaydi"
            />
            <Field label="Test davomiyligi — platforma vaqt bermasa shu ishlatiladi" value={durationText(exam.duration_minutes)} />
            <Field label="Yaratilgan" value={dateText(exam.created_at)} />
            <Field label="ID" value={exam.id} mono />
          </Section>
        </Box>

        <Box sx={{ minWidth: 0 }}>
          <Section title="Test platformasi">
            <Field
              icon={<LinkIcon fontSize="small" />}
              label="Tekshiruv API manzili (server chaqiradi)"
              value={exam.site_url}
              mono
              onCopy={copy}
            />
            <Field
              icon={<KeyIcon fontSize="small" />}
              label="Platforma sarlavhasi (niqoblangan)"
              value={exam.site_header_masked}
              hint="O‘rnatilmagan"
              mono
            />
            <Field
              icon={<ImageIcon fontSize="small" />}
              label="Resurs domenlari (rasm, shrift, CSS)"
              value={domains.length ? (
                <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
                  {domains.map((domain) => (
                    <Chip key={domain} size="small" variant="outlined" label={domain} sx={{ fontFamily: 'monospace' }} />
                  ))}
                </Stack>
              ) : ''}
              hint="Yo‘q — savol rasmlari faqat test sahifasi domenidan ochiladi"
            />
          </Section>

          {!deleted && (
            <Section title={`Oxirgi seanslar · ${schedulesLoading ? '…' : schedulesCount}`}>
              {schedulesLoading ? (
                <Box sx={{ p: 2 }}><Skeleton height={40} /></Box>
              ) : schedules.length ? schedules.map((schedule) => {
                const phase = schedulePhase(schedule)
                return (
                  <Field
                    key={schedule.id}
                    icon={<EventIcon fontSize="small" />}
                    label={`${phase.label} · ${schedule.zone_name || 'Barcha binolar'}`}
                    value={`${formatDate(schedule.exam_date)} · ${formatTime(schedule.starts_at).slice(0, 5)}–${formatTime(schedule.ends_at).slice(0, 5)}`}
                  />
                )
              }) : (
                <Field label="Seans" value="" hint="Hali yaratilmagan — «Imtihon jadvali» sahifasida qo‘shing" />
              )}
            </Section>
          )}
        </Box>
      </Box>

      <InfoNote icon={<InfoIcon fontSize="small" />}>
        JSHSHIR kiritilganda server tekshiruv API’siga <b>?imie=&lt;JSHSHIR&gt;</b> bilan so‘rov
        yuboradi va javobdagi test havolasini oladi — client platformaga o‘zi murojaat qilmaydi.
        Token faqat serverda shifrlangan holda saqlanadi.
      </InfoNote>
    </DetailDialog>
  )
}
