import { Box, Chip } from '@mui/material'
import KeyboardIcon from '@mui/icons-material/KeyboardOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'

import DetailDialog, { InfoNote } from '../data/DetailDialog'
import { dateText, Field, Section, useCopy } from '../data/DetailFields'
import { capLabel, isModifier, parseHotkey } from '../../utils/hotkeys'
import { ActiveChip, Keycaps, ProfilesSection } from './ControlBits'

/**
 * Tezkor tugma kartasi: client uni QANDAY o'qiydi (asosiy tugma +
 * modifikatorlar — `lockdown._parse_combo` bilan bir xil), qaysi
 * profillarda yoqilgan va nima uchun ishlamasligi mumkin.
 */
export default function HotkeyDetailDialog({ row, onEdit, onClose }) {
  const copy = useCopy()
  const parsed = parseHotkey(row.code)
  const main = parsed.parts.filter((part) => !isModifier(part))
  // Faqat modifikatordan iborat kod (`win`) — o'sha tugmaning O'ZI
  // bloklanadi (client: asosiy = oxirgi qism).
  const key = main[0] || parsed.parts[parsed.parts.length - 1]
  const required = parsed.parts.filter((part) => part !== key)

  const problems = []
  if (parsed.error) {
    problems.push({
      severity: 'error',
      text: `Client bu kodni tanimaydi (${parsed.error}) — tugma imtihonda BLOKLANMAYDI. Kodni tahrirlang.`,
    })
  }
  if (!row.is_active) {
    problems.push({
      severity: 'warning',
      text: 'Yozuv nofaol — profilda turgan bo‘lsa ham client’ga yuborilmaydi.',
    })
  }

  return (
    <DetailDialog
      icon={<KeyboardIcon />}
      tone={parsed.error ? 'error' : row.is_active ? 'primary' : 'neutral'}
      title={row.name}
      subtitle="Imtihon paytida bloklanadigan kombinatsiya"
      chips={<>
        <ActiveChip active={row.is_active} />
        {parsed.error && <Chip size="small" color="error" label="Client tanimaydi" />}
      </>}
      problems={problems}
      onEdit={onEdit}
      onClose={onClose}
      maxWidth="sm"
    >
      <Section title="Kombinatsiya">
        <Box sx={{ px: 2, py: 2.5, display: 'flex', justifyContent: 'center' }}>
          <Keycaps code={row.code} />
        </Box>
        <Field label="Kod (client shu satrni oladi)" value={row.code} mono onCopy={copy} />
        {!parsed.error && (
          <>
            <Field label="Bloklanadigan tugma" value={capLabel(key)} />
            <Field
              label="Shu tugmalar bosilgan holatda"
              value={required.map(capLabel).join(' + ')}
              hint="Har doim — modifikatorsiz ham"
            />
          </>
        )}
      </Section>

      <ProfilesSection profiles={row.profiles} what="kombinatsiya" />

      <InfoNote icon={<InfoIcon fontSize="small" />}>
        Client imtihon profilidagi ro‘yxatni oladi va u o‘z standart ro‘yxatini ALMASHTIRADI.
        Profilda birorta ham tugma tanlanmagan bo‘lsa, client mashinadagi standartni
        (<code>BLOCKED_HOTKEYS</code>) ishlatadi. <b>Ctrl+Q</b> hech qachon bloklanmaydi —
        bu dasturdan chiqishning yagona yo‘li.
      </InfoNote>

      <Section title="Yozuv">
        <Field label="Yaratilgan" value={dateText(row.created_at)} />
        <Field label="Oxirgi o‘zgarish" value={dateText(row.updated_at)} />
        <Field label="ID" value={row.id} mono />
      </Section>
    </DetailDialog>
  )
}
