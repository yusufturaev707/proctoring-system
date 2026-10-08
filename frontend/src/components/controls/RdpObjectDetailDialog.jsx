import { Chip, Stack, Typography } from '@mui/material'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'

import DetailDialog, { InfoNote } from '../data/DetailDialog'
import { dateText, Field, Section } from '../data/DetailFields'
import { EVENT_LABEL } from '../../utils/labels'
import { ActiveChip, ProfilesSection } from './ControlBits'
import { CATEGORY_META, SIGNS, signsOf } from './rdpMeta'

/**
 * Taqiqlangan dastur kartasi: client uni NIMA bo'yicha taniydi
 * (belgilar ishonchlilik tartibida), topilganda NIMA bo'ladi (hodisa
 * turi, imtihon to'siladimi) va qaysi profillarda yoqilgan.
 */
export default function RdpObjectDetailDialog({ row, onEdit, onClose }) {
  const category = CATEGORY_META[row.category] || CATEGORY_META.remote
  const CategoryIcon = category.icon
  const { none, weakOnly } = signsOf(row)

  const problems = []
  if (none) {
    problems.push({ severity: 'error', text: 'Birorta aniqlash belgisi yo‘q — client bu dasturni topa olmaydi.' })
  } else if (weakOnly) {
    problems.push({
      severity: 'warning',
      text: 'Faqat fayl nomi kiritilgan: faylni qayta nomlash (AnyDesk.exe → notepad.exe) aniqlashni chetlab o‘tadi. Imzo egasi yoki asl fayl nomini qo‘shing.',
    })
  }
  if (!row.is_active) {
    problems.push({ severity: 'warning', text: 'Yozuv nofaol — profilda turgan bo‘lsa ham client’ga yuborilmaydi.' })
  }

  return (
    <DetailDialog
      icon={<CategoryIcon />}
      tone={none ? 'error' : !row.is_active ? 'neutral' : row.is_blocking ? 'warning' : 'primary'}
      title={row.name}
      subtitle={
        <Typography component="span" variant="body2" sx={{ fontFamily: 'monospace' }}>kod: {row.code}</Typography>
      }
      chips={<>
        <ActiveChip active={row.is_active} />
        <Chip size="small" variant="outlined" icon={<CategoryIcon />} label={category.label} />
        {row.is_blocking && <Chip size="small" color="error" icon={<BlockIcon />} label="Imtihonni to‘sadi" />}
      </>}
      problems={problems}
      onEdit={onEdit}
      onClose={onClose}
    >
      <InfoNote icon={<InfoIcon fontSize="small" />}>
        Topilganda client dasturni yopadi (avval xizmatini, keyin jarayonini) va
        «{EVENT_LABEL[category.event] || category.event}» hodisasini yozadi — yopilgani ham bayonnomaga tushadi.{' '}
        {row.is_blocking
          ? <>Yopib bo‘lmasa (masalan, administrator huquqi yetmasa) <b>imtihon boshlanmaydi</b> — profilda
            «tahdid imtihonni to‘sadi» yoqilgan bo‘lsa; o‘chiq bo‘lsa operatorga ogohlantirish chiqadi.</>
          : <>Yopib bo‘lmasa ham imtihon to‘xtamaydi — operator ogohlantiriladi, proktor hodisani ko‘radi.</>}
      </InfoNote>

      <Section title="Aniqlash belgilari · ishonchlilik tartibida">
        {SIGNS.map((sign) => {
          const values = row[sign.name] || []
          return (
            <Field
              key={sign.name}
              label={`${sign.label} · ${sign.strength}`}
              hint="Kiritilmagan"
              value={values.length ? (
                <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.25 }}>
                  {values.map((item, index) => (
                    <Chip
                      key={`${item}-${index}`}
                      size="small"
                      label={String(item)}
                      sx={{
                        fontFamily: 'monospace',
                        bgcolor: sign.strong ? 'm3.secondaryContainer' : 'm3.surfaceContainerHighest',
                        color: sign.strong ? 'm3.onSecondaryContainer' : 'text.primary',
                      }}
                    />
                  ))}
                </Stack>
              ) : ''}
            />
          )
        })}
      </Section>

      <ProfilesSection profiles={row.profiles} what="dastur" />

      <Section title="Yozuv">
        <Field label="Yaratilgan" value={dateText(row.created_at)} />
        <Field label="Oxirgi o‘zgarish" value={dateText(row.updated_at)} />
        <Field label="ID" value={row.id} mono />
      </Section>
    </DetailDialog>
  )
}
