import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'
import StarIcon from '@mui/icons-material/StarOutlineRounded'

import { capLabel, isModifier, parseHotkey } from '../../utils/hotkeys'
import { Field, Section } from '../data/DetailFields'

/**
 * Klaviatura tugmachalari: `ctrl+shift+i` -> [Ctrl] + [Shift] + [I].
 * Modifikator va asosiy tugma rangi farq qiladi — qaysi tugma "yutilishi"
 * (asosiy) ko'rinib tursin.
 */
export function Keycaps({ code, size = 'medium' }) {
  const { parts } = parseHotkey(code)
  if (!parts.length) return <Typography variant="body2" color="text.disabled">—</Typography>
  const small = size === 'small'
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" useFlexGap flexWrap="wrap" sx={{ minWidth: 0 }}>
      {parts.map((part, index) => (
        <Stack key={`${part}-${index}`} direction="row" spacing={0.5} alignItems="center">
          {index > 0 && <Typography variant="caption" color="text.disabled">+</Typography>}
          <Box
            component="kbd"
            sx={{
              fontFamily: 'inherit', fontWeight: 650, lineHeight: 1,
              fontSize: small ? 12 : 14,
              px: small ? 0.75 : 1.25, py: small ? 0.5 : 0.75,
              minWidth: small ? 24 : 32, textAlign: 'center', whiteSpace: 'nowrap',
              borderRadius: '8px', border: 1, borderBottomWidth: 3,
              borderColor: 'm3.outlineVariant',
              bgcolor: isModifier(part) ? 'm3.surfaceContainerHighest' : 'm3.secondaryContainer',
              color: isModifier(part) ? 'text.primary' : 'm3.onSecondaryContainer',
            }}
          >
            {capLabel(part)}
          </Box>
        </Stack>
      ))}
    </Stack>
  )
}

/**
 * Jadval katagi: yozuv qaysi sozlama profillarida yoqilgan.
 *
 * Profilga kirmagan dastur/tugma client'ga UMUMAN yetmaydi
 * (`controls.services._serialize`) — shuning uchun bo'sh holat
 * ogohlantirish rangida, "—" emas.
 */
export function ProfilesCell({ profiles }) {
  const list = profiles || []
  if (!list.length) {
    return (
      <Tooltip title="Client bu yozuvni olmaydi: uni «Client sozlamalari» dagi profilga qo‘shing">
        <Chip size="small" color="warning" variant="outlined" icon={<WarningIcon />} label="Hech bir profilda yo‘q" />
      </Tooltip>
    )
  }
  const [first, ...rest] = list
  return (
    <Tooltip title={list.map((item) => item.name + (item.is_default ? ' (global standart)' : '')).join(', ')}>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ minWidth: 0 }}>
        <Chip
          size="small"
          icon={first.is_default ? <StarIcon /> : undefined}
          label={first.name}
          sx={{ bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer', minWidth: 0 }}
        />
        {rest.length > 0 && <Chip size="small" variant="outlined" label={`+${rest.length}`} />}
      </Stack>
    </Tooltip>
  )
}

/** Tafsilot oynasidagi "Qaysi profillarda" bo'limi. */
export function ProfilesSection({ profiles, what }) {
  const list = profiles || []
  return (
    <Section title={`Sozlama profillari · ${list.length}`}>
      {list.length ? list.map((item) => (
        <Field
          key={item.id}
          icon={item.is_default ? <StarIcon fontSize="small" /> : undefined}
          label={item.is_default ? 'Global standart — o‘z profili yo‘q imtihonlar shu bilan ishlaydi' : 'Imtihon profili'}
          value={item.name}
        />
      )) : (
        <Field
          icon={<WarningIcon fontSize="small" color="warning" />}
          label="Hech bir profilga kiritilmagan"
          value={`Client bu ${what} haqida bilmaydi. «Client sozlamalari» sahifasida kerakli profilni oching va uni ro‘yxatga qo‘shing.`}
        />
      )}
    </Section>
  )
}

/** Faol / nofaol chip — tafsilot sarlavhalarida bir xil ko'rinish. */
export function ActiveChip({ active, on = 'Faol', off = 'Nofaol' }) {
  return (
    <Chip
      size="small"
      color={active ? 'success' : 'default'}
      variant={active ? 'filled' : 'outlined'}
      label={active ? on : off}
    />
  )
}
