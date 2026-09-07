import { useMemo } from 'react'
import {
  Box, Card, CardHeader, Chip, Divider, IconButton, List, ListItemButton,
  ListItemText, Stack, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import ClearIcon from '@mui/icons-material/ClearAllOutlined'

import { SeverityChip } from '../StatusChip'
import { formatTime } from '../../utils/labels'
import {
  CATEGORY_META, CATEGORY_ORDER, categoryOf, collapseRepeats, countByCategory,
  eventDetail, eventLabel,
} from '../../utils/events'

/**
 * Jonli hodisa oqimi.
 *
 * Uchta qaror oqimni o'qib bo'ladigan qiladi:
 *
 *   1. GURUHLASH. Turlar ma'nosi bo'yicha to'rt turkumga bo'linadi
 *      (`utils/events.js`) va nishonlar orqali filtrlanadi. "Qurilma"
 *      turkumi birinchi turadi — u talabgorning xulqi emas, mashinaning
 *      holati haqida va aynan u chetlashtirish sababi bo'ladi.
 *
 *   2. TAKRORLARNI YIG'ISH. Alt+Tab yigirma marta bosilsa, oqimda
 *      yigirmata bir xil qator paydo bo'lib, qolgan hamma narsani
 *      surib chiqarardi. Endi u bitta qator va "×20" — ma'lumot
 *      yo'qolmaydi, takror sonining o'zi signalga aylanadi.
 *
 *   3. ISM. "Sessiya #4821" proktorga hech narsa demaydi; u talabgorni
 *      ism bo'yicha qidiradi va shu ism bilan qo'ng'iroq qiladi.
 *      Ro'yxat jadvaldagi qatorlardan olinadi — qo'shimcha so'rov yo'q.
 */
export default function EventStream({
  events,
  onClear,
  /** `{[session_id]: {name, zone}}` — jadvaldagi qatorlardan. */
  sessionIndex = {},
  onSelectSession,
  /**
   * Turkum filtri TASHQARIDAN boshqariladi.
   *
   * Sabab: butunlik banneridagi "Oqimda ko'rish" tugmasi shu filtrni
   * o'zgartiradi. Holat komponent ichida qolsa, ikki blok bir-birini
   * ko'rmasdi va tugma hech narsa qila olmasdi.
   */
  category = 'all',
  onCategoryChange,
  height = 660,
}) {
  const setCategory = (value) => onCategoryChange?.(value)

  const counts = useMemo(() => countByCategory(events), [events])

  const visible = useMemo(() => {
    const filtered =
      category === 'all'
        ? events
        : events.filter((event) => categoryOf(event.event_type) === category)
    // Yig'ish FILTRDAN KEYIN: aks holda filtr guruhni buzib, bitta
    // qatorda ko'rinadigan takrorlar sonini noto'g'ri ko'rsatardi.
    return collapseRepeats(filtered)
  }, [events, category])

  return (
    <Card sx={{ height, display: 'flex', flexDirection: 'column' }}>
      <CardHeader
        // Sarlavhada sanoq YO'Q: u pastdagi "Hammasi N" nishonida
        // allaqachon bor va `Badge` uni takrorlash bilan birga
        // sarlavha matnini bosib turardi.
        title={<Typography variant="h6">Hodisa oqimi</Typography>}
        subheader="Faqat o‘rta va undan yuqori darajali"
        action={
          <Tooltip title="Oqimni tozalash">
            <span>
              <IconButton onClick={onClear} disabled={events.length === 0}>
                <ClearIcon />
              </IconButton>
            </span>
          </Tooltip>
        }
        sx={{ pb: 1 }}
      />

      <Box sx={{ px: 2, pb: 1.5 }}>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          <Chip
            size="small"
            label={`Hammasi ${events.length}`}
            color={category === 'all' ? 'primary' : 'default'}
            variant={category === 'all' ? 'filled' : 'outlined'}
            onClick={() => setCategory('all')}
          />
          {CATEGORY_ORDER.map((key) => {
            const meta = CATEGORY_META[key]
            const count = counts[key]
            return (
              <Tooltip key={key} title={meta.full}>
                <Chip
                  size="small"
                  label={`${meta.label} ${count}`}
                  color={category === key ? meta.color : 'default'}
                  variant={category === key ? 'filled' : 'outlined'}
                  onClick={() => setCategory(category === key ? 'all' : key)}
                  // Bo'sh turkum o'chirilmaydi, xiralashtiriladi:
                  // yo'qolib qolgan nishon "bunday turkum yo'q" degan
                  // taassurot berardi.
                  sx={{ opacity: count === 0 ? 0.45 : 1 }}
                />
              </Tooltip>
            )
          })}
        </Stack>
      </Box>

      <Divider />

      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        {visible.length === 0 ? (
          <Box sx={{ p: 4, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {events.length === 0
                ? 'Hozircha hodisa yo‘q'
                : 'Bu turkumda hodisa yo‘q'}
            </Typography>
          </Box>
        ) : (
          <List dense disablePadding>
            {visible.map((event, index) => (
              <EventRow
                key={`${event.session_id}-${event.event_type}-${event.occurred_at}-${index}`}
                event={event}
                session={sessionIndex[event.session_id]}
                onClick={() => onSelectSession?.(event.session_id)}
              />
            ))}
          </List>
        )}
      </Box>
    </Card>
  )
}

function EventRow({ event, session, onClick }) {
  const category = categoryOf(event.event_type)
  const meta = CATEGORY_META[category]
  const detail = eventDetail(event.event_type, event.detail)

  const who = session?.name || `Sessiya #${event.session_id}`
  const where = session?.zone ? ` • ${session.zone}` : ''

  return (
    <ListItemButton
      divider
      onClick={onClick}
      sx={{
        // Chap chekkadagi rangli chiziq — turkumni bir qarashda
        // ajratadi va nishonni har qatorda takrorlash shart emas.
        borderLeft: 3,
        borderLeftColor:
          meta.color === 'default' ? 'divider' : `${meta.color}.main`,
        // Kritik hodisa fon bilan ham ajratiladi. Rang YAGONA belgi
        // emas: jiddiylik nishoni o'ng tomonda matn bilan turadi.
        bgcolor: (theme) =>
          event.severity >= 4
            ? alpha(theme.palette.error.main, theme.palette.mode === 'light' ? 0.07 : 0.16)
            : 'transparent',
      }}
    >
      <ListItemText
        primary={
          <Stack direction="row" spacing={0.75} alignItems="center">
            <Typography component="span" sx={{ fontSize: 14, fontWeight: 500 }}>
              {eventLabel(event.event_type)}
            </Typography>
            {event.repeats > 1 && (
              <Tooltip
                title={`Birinchisi ${formatTime(event.first_at)} da`}
              >
                <Chip
                  size="small"
                  label={`×${event.repeats}`}
                  sx={{ height: 18, fontSize: 11, fontWeight: 700 }}
                />
              </Tooltip>
            )}
          </Stack>
        }
        secondary={
          <>
            {detail && (
              <Typography
                component="span"
                variant="caption"
                sx={{ display: 'block', color: 'text.primary', fontWeight: 500 }}
              >
                {detail}
              </Typography>
            )}
            <Typography component="span" variant="caption" color="text.secondary">
              {who}
              {where} • {formatTime(event.occurred_at)}
            </Typography>
          </>
        }
        primaryTypographyProps={{ component: 'div' }}
        secondaryTypographyProps={{ component: 'span' }}
      />
      <SeverityChip severity={event.severity} />
    </ListItemButton>
  )
}
