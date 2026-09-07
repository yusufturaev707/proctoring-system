import {
  Alert, AlertTitle, Box, Button, Chip, IconButton, Stack, Tooltip, Typography,
} from '@mui/material'
import DoneIcon from '@mui/icons-material/DoneOutlined'
import OpenIcon from '@mui/icons-material/OpenInNewOutlined'

import { formatTime } from '../../utils/labels'
import { eventDetail, eventLabel } from '../../utils/events'

/**
 * Qurilma butunligi ogohlantirishlari.
 *
 * NIMA UCHUN ALOHIDA BLOK: masofaviy boshqaruv, virtual mashina,
 * ikkinchi monitor va soxta kadr — talabgorning XULQI emas,
 * mashinaning HOLATI haqida. Ular oqimda `window_blur` bilan bir xil
 * qatorda tursa, proktor ularni o'nlab oddiy hodisa orasidan qidirishga
 * majbur bo'ladi. Bu esa aynan chetlashtirish qarori qabul qilinadigan
 * hodisalar.
 *
 * Blok yopiladigan qilingan (`Ko'rib chiqildi`) va bu MAJBURIY: doimiy
 * turadigan qizil banner bir soatdan keyin fon shovqiniga aylanadi va
 * proktor unga umuman qaramay qo'yadi. Yopilgandan keyin O'SHA sessiya
 * uchun YANGI hodisa kelsa, u qaytadan ko'rinadi.
 */
export default function IntegrityAlerts({
  items,
  sessionIndex = {},
  onAcknowledge,
  onSelectSession,
  onShowInStream,
  maxVisible = 4,
}) {
  if (!items.length) return null

  const visible = items.slice(0, maxVisible)
  const hidden = items.length - visible.length

  return (
    <Alert
      severity="error"
      variant="outlined"
      sx={{ mb: 2.5, alignItems: 'flex-start' }}
      action={
        onShowInStream && (
          <Button size="small" color="error" onClick={onShowInStream}>
            Oqimda ko‘rish
          </Button>
        )
      }
    >
      <AlertTitle sx={{ fontWeight: 700 }}>
        Qurilma butunligi — {items.length} ta sessiya
      </AlertTitle>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
        Bu hodisalar talabgorning xulqi emas, mashinaning holati haqida.
      </Typography>

      <Stack spacing={0.75}>
        {visible.map((item) => (
          <IntegrityRow
            key={item.session_id}
            item={item}
            session={sessionIndex[item.session_id]}
            onAcknowledge={() => onAcknowledge?.(item)}
            onSelect={() => onSelectSession?.(item.session_id)}
          />
        ))}
        {hidden > 0 && (
          <Typography variant="caption" color="text.secondary">
            va yana {hidden} ta sessiya — oqimda ko‘ring
          </Typography>
        )}
      </Stack>
    </Alert>
  )
}

function IntegrityRow({ item, session, onAcknowledge, onSelect }) {
  const detail = eventDetail(item.event_type, item.detail)
  const who = session?.name || `Sessiya #${item.session_id}`

  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <Chip
        size="small"
        color="error"
        variant="filled"
        label={eventLabel(item.event_type)}
        sx={{ fontWeight: 600 }}
      />

      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {who}
      </Typography>

      {session?.zone && (
        <Typography variant="caption" color="text.secondary">
          {session.zone}
        </Typography>
      )}

      {detail && (
        <Typography variant="caption" sx={{ fontWeight: 500 }}>
          {detail}
        </Typography>
      )}

      <Typography variant="caption" color="text.secondary">
        {formatTime(item.occurred_at)}
      </Typography>

      {/* Takror soni ham signal: bir marta aniqlangan RDP va yigirma
          marta aniqlangani bir xil emas. */}
      {item.repeats > 1 && (
        <Chip size="small" variant="outlined" label={`×${item.repeats}`} sx={{ height: 20 }} />
      )}

      <Box sx={{ flex: 1 }} />

      <Tooltip title="Sessiyani ochish">
        <IconButton size="small" onClick={onSelect}>
          <OpenIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Ko‘rib chiqildi — ro‘yxatdan olib tashlash">
        <IconButton size="small" onClick={onAcknowledge}>
          <DoneIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  )
}
