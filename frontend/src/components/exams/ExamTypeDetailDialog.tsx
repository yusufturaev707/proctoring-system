import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Chip, Skeleton } from '@mui/material'
import CategoryIcon from '@mui/icons-material/CategoryOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import KeyIcon from '@mui/icons-material/KeyOutlined'

import DetailDialog, { StatTiles } from '../data/DetailDialog'
import type { DetailProblem } from '../data/DetailDialog'
import type { DetailDialogBaseProps } from '../data/types'
import { dateText, Field, Section, useCopy } from '../data/DetailFields'
import { listAll } from '../data/useResource'
import { ActiveChip } from '../controls/ControlBits'
import { examTypes as examTypesApi, exams as examsApi } from '../../api/endpoints'
import { durationText } from './examText'

/**
 * Imtihon turi kartasi: tur nima, kaliti va unga qaysi imtihonlar
 * biriktirilgan. Imtihonlar ro'yxati shu yerda — turni o'chirish yoki
 * nofaol qilishdan oldin administrator nimaga ta'sir qilishini ko'rsin
 * (bog'langan imtihon bo'lsa server o'chirishni rad etadi, FK `PROTECT`).
 */
export default function ExamTypeDetailDialog({ row, onEdit, onClose }: DetailDialogBaseProps) {
  const navigate = useNavigate()
  const copy = useCopy()
  const deleted = Boolean(row.deleted_at)

  // Ro'yxat qatori eskirgan bo'lishi mumkin (boshqa admin tahrirladi).
  const { data: fresh } = useQuery({
    queryKey: ['exam-types', 'detail', row.id],
    queryFn: () => examTypesApi.detail(row.id),
    enabled: !deleted,
  })
  const { data: examsData, isLoading: examsLoading } = useQuery({
    queryKey: ['exams', 'by-type', row.id],
    queryFn: () => listAll(examsApi, { exam_type: row.id }),
    enabled: !deleted,
  })

  const type = { ...row, ...(fresh || {}) }
  const exams = examsData?.results || []
  const activeExams = exams.filter((exam) => exam.is_active).length
  const sessions = exams.reduce((sum, exam) => sum + (exam.sessions_count || 0), 0)

  const problems: DetailProblem[] = []
  if (deleted) {
    problems.push({ severity: 'error', text: `Tur o‘chirilgan (${dateText(type.deleted_at)}). Tiklash — jadvaldagi «Tiklash» tugmasi.` })
  } else if (!type.is_active) {
    problems.push({
      severity: 'warning',
      text: 'Tur nofaol — yangi imtihonga tanlash ro‘yxatida chiqmaydi. Biriktirilgan imtihonlar o‘zgarishsiz ishlayveradi.',
    })
  }

  return (
    <DetailDialog
      icon={<CategoryIcon />}
      tone={deleted ? 'error' : type.is_active ? 'primary' : 'neutral'}
      title={type.name}
      subtitle="Imtihon turi"
      chips={<>
        {deleted ? <Chip size="small" color="error" label="O‘chirilgan" /> : <ActiveChip active={type.is_active} />}
        <Chip size="small" variant="outlined" icon={<KeyIcon />} label={type.key} sx={{ fontFamily: 'monospace' }} />
      </>}
      problems={problems}
      onEdit={deleted ? undefined : onEdit}
      onClose={onClose}
      maxWidth="sm"
      actions={!deleted && (
        <Button startIcon={<SchoolIcon />} onClick={() => navigate(`/exams?f.exam_type=${type.id}`)}>
          Imtihonlar
        </Button>
      )}
    >
      <StatTiles
        items={[
          { label: 'Imtihonlar', value: type.exams_count ?? exams.length },
          { label: 'Faol imtihonlar', value: examsLoading ? undefined : activeExams },
          { label: 'Sessiyalar', value: examsLoading ? undefined : sessions },
        ]}
      />

      <Section title="Asosiy">
        <Field label="Nomi" value={type.name} />
        <Field
          label="Kalit — hisobot va integratsiyada kod sifatida ishlatiladi"
          value={type.key}
          mono
          onCopy={copy}
        />
      </Section>

      {!deleted && (
        <Section title={`Biriktirilgan imtihonlar · ${examsLoading ? '…' : exams.length}`}>
          {examsLoading ? (
            <Box sx={{ p: 2 }}><Skeleton height={40} /></Box>
          ) : exams.length ? exams.map((exam) => (
            <Field
              key={exam.id}
              icon={<SchoolIcon fontSize="small" />}
              label={[
                durationText(exam.duration_minutes),
                `${exam.sessions_count || 0} ta sessiya`,
                !exam.is_active && 'nofaol',
              ].filter(Boolean).join(' · ')}
              value={exam.name}
            />
          )) : (
            <Field label="Imtihon" value="" hint="Bu turga hali imtihon biriktirilmagan" />
          )}
        </Section>
      )}

      <Section title="Yozuv">
        <Field label="Yaratilgan" value={dateText(type.created_at)} />
        <Field label="ID" value={type.id} mono />
      </Section>
    </DetailDialog>
  )
}
