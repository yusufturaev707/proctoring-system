import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Box, ButtonBase, Chip, CircularProgress, Stack, Typography,
} from '@mui/material'
import GavelIcon from '@mui/icons-material/GavelOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'

import DetailDialog, { InfoNote, StatTiles } from '../data/DetailDialog'
import type { DetailProblem } from '../data/DetailDialog'
import type { DetailDialogBaseProps } from '../data/types'
import { dateText, Section } from '../data/DetailFields'
import { offers as offersApi } from '../../api/endpoints'
import type { ApiRecord } from '../../types/api'
import OfferDocument from './OfferDocument'

/**
 * Oferta kartasi: qaysi testlarda so'ralishi, matn talabgor ko'radigan
 * ko'rinishda va versiyalar tarixi.
 *
 * TARIX — huquqiy savolga javob: "talabgor qaysi kuni qaysi matnga rozi
 * bo'lgan?". Har versiyada nechta rozilik borligi ko'rinadi va bosilsa
 * o'sha versiyaning AYNAN o'zi chiziladi (keyingi tahrirlar ta'sir qilmaydi).
 */
export default function OfferDetailDialog({ row, onEdit, onClose }: DetailDialogBaseProps) {
  const [selected, setSelected] = useState<ApiRecord | null>(null)
  const { data: revisions = [], isLoading } = useQuery({
    queryKey: ['offers', row.id, 'revisions'],
    queryFn: () => offersApi.revisions(row.id),
  })

  const shown = selected ?? { version: row.version, title: row.title, content: row.content }
  const isCurrent = shown.version === row.version
  const exams: ApiRecord[] = row.exam_list || []
  const deleted = Boolean(row.deleted_at)
  const asked = row.is_active && exams.length > 0 && !deleted

  const problems: DetailProblem[] = []
  if (deleted) {
    problems.push({ severity: 'error', text: `Oferta o‘chirilgan (${dateText(row.deleted_at)}). Tiklash — jadvaldagi «Tiklash» tugmasi.` })
  } else {
    if (!exams.length) {
      problems.push({
        severity: 'warning',
        text: 'Hech bir testga biriktirilmagan — talabgorlarga ko‘rsatilmaydi. «Tahrirlash» → «Testlar» da tanlang.',
      })
    }
    if (!row.is_active) {
      problems.push({
        severity: 'info',
        text: 'Oferta nofaol — biriktirilgan testlarda ham so‘ralmaydi. Yoqish uchun jadvaldagi kalitdan foydalaning.',
      })
    }
  }

  return (
    <DetailDialog
      icon={<GavelIcon />}
      tone={deleted ? 'error' : asked ? 'success' : 'neutral'}
      title={row.title}
      subtitle={`Oxirgi tahrir: ${dateText(row.updated_at)}${row.updated_by_name ? ` · ${row.updated_by_name}` : ''}`}
      chips={<>
        {row.is_active
          ? <Chip size="small" color="success" label="Faol" />
          : <Chip size="small" variant="outlined" label="Nofaol" />}
        <Chip size="small" variant="outlined" label={`Versiya ${row.version}`} />
      </>}
      problems={problems}
      onEdit={deleted ? undefined : onEdit}
      onClose={onClose}
    >
      <StatTiles
        items={[
          { label: 'Testlar', value: exams.length },
          { label: 'Joriy versiya', value: row.version },
          { label: 'Roziliklar', value: (row.consents_count ?? 0).toLocaleString('uz'), hint: 'barcha versiyalarga' },
          { label: 'Versiyalar', value: isLoading ? undefined : revisions.length },
        ]}
      />

      <InfoNote icon={<InfoIcon fontSize="small" />}>
        Biriktirilgan testlarda talabgor bu matnni JSHSHIR bo‘yicha topilgandan keyin, yuz tekshiruvidan <b>oldin</b> o‘qiydi va
        «Roziman» ni bosadi — rozilik siz shu yerda ko‘rib turgan versiyaga yoziladi. Matnni tahrirlash
        yangi versiya yaratadi, berilgan roziliklar eski versiyada o‘zgarmay qoladi.
      </InfoNote>

      <Section title={`Testlar · ${exams.length}`}>
        {exams.length ? (
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ p: 1.5 }}>
            {exams.map((exam) => (
              <Chip
                key={exam.id}
                icon={<SchoolIcon />}
                variant={exam.is_active ? 'filled' : 'outlined'}
                label={exam.is_active ? exam.name : `${exam.name} (nofaol)`}
                sx={{ bgcolor: exam.is_active ? 'm3.secondaryContainer' : undefined }}
              />
            ))}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 1.5 }}>
            Biriktirilmagan. Testni shu ofertaning formasidan yoki «Imtihonlar» sahifasidagi «Oferta» maydonidan tanlang.
          </Typography>
        )}
      </Section>

      <Section
        title={isCurrent ? 'Matn · talabgor shunday ko‘radi' : `Matn · ${shown.version}-versiya (tarixdan)`}
        action={!isCurrent ? (
          <Chip size="small" label="Joriy versiyaga qaytish" onClick={() => setSelected(null)} />
        ) : undefined}
      >
        <Box sx={{ px: { xs: 2, sm: 4 }, py: 3, maxHeight: '50vh', overflowY: 'auto' }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>{shown.title}</Typography>
          <OfferDocument html={shown.content} />
        </Box>
      </Section>

      <Section title="Versiyalar tarixi">
        {isLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}><CircularProgress size={24} /></Box>
        ) : (
          <Stack spacing={0.5} sx={{ p: 0.75 }}>
            {revisions.map((revision) => {
              const active = shown.version === revision.version
              return (
                <ButtonBase
                  key={revision.id}
                  onClick={() => setSelected(revision.version === row.version ? null : revision)}
                  sx={{
                    display: 'flex', alignItems: 'center', gap: 1.5, textAlign: 'left',
                    px: 1.5, py: 1, borderRadius: '12px', width: '100%',
                    bgcolor: active ? 'm3.secondaryContainer' : 'transparent',
                    '&:hover': { bgcolor: active ? 'm3.secondaryContainer' : 'action.hover' },
                  }}
                >
                  <HistoryIcon fontSize="small" color={active ? 'inherit' : 'action'} />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={600} noWrap>
                      {revision.version}-versiya · {revision.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap display="block">
                      {dateText(revision.created_at)}{revision.created_by_name ? ` · ${revision.created_by_name}` : ''}
                    </Typography>
                  </Box>
                  <Chip
                    size="small"
                    variant={revision.consents_count ? 'filled' : 'outlined'}
                    label={`${revision.consents_count ?? 0} rozilik`}
                  />
                </ButtonBase>
              )
            })}
          </Stack>
        )}
      </Section>
    </DetailDialog>
  )
}
