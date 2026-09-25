import { useCallback, useMemo, useState } from 'react'
import { alpha } from '@mui/material/styles'
import {
  Alert, Box, Button, ButtonBase, Card, Chip, CircularProgress, Divider, Drawer, IconButton,
  InputAdornment, LinearProgress, Skeleton, Stack, Switch, TextField, Tooltip, Typography,
  useMediaQuery, useTheme,
} from '@mui/material'
import PersonIcon from '@mui/icons-material/Person'
import BuildIcon from '@mui/icons-material/BuildCircleOutlined'
import CloseIcon from '@mui/icons-material/CloseRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import ApartmentIcon from '@mui/icons-material/ApartmentOutlined'
import ScreenIcon from '@mui/icons-material/CoPresentOutlined'
import AssignIcon from '@mui/icons-material/PersonAddAltOutlined'
import ReleaseIcon from '@mui/icons-material/PersonRemoveOutlined'
import MoveIcon from '@mui/icons-material/SwapHorizRounded'
import WarningIcon from '@mui/icons-material/WarningAmberRounded'
import LockIcon from '@mui/icons-material/LockOutlined'

import { STATUS_LABEL } from '../../theme'
import { fromNow } from '../../utils/labels'

/**
 * Joylar xaritasi — poyezd bronlash naqshi.
 *
 * Nima uchun jadval emas: bron savoli FAZOVIY. Administrator "12-stol
 * bo'shmi, yonidagilar-chi?" deb o'ylaydi, operator talabgorni "uchinchi
 * qator, o'ngdan ikkinchi" deb yo'naltiradi — jadvaldagi qator bu
 * savolga javob bermaydi. Xarita esa zalni bir qarashda ko'rsatadi:
 * nechtasi bo'sh, buzilganlar qayerda, qaysi talabgor kelgan.
 *
 * Ikki qatlam, poyezddagi kabi:
 *
 *   ZoneRail   — "vagonlar": binolar, viloyat bo'yicha guruhlangan va
 *                har birining bandlik chizig'i bilan;
 *   SeatGrid   — "vagon ichi": o'rindiqlar raqam tartibida, qatorlarga
 *                bo'lingan, o'rtasida yo'lak.
 *
 * Holat UCH belgi bilan beriladi (rang + ikonka + shakl): rang
 * ko'rmaydigan odam ham farqni ko'rishi kerak — buzilgan joyda chiziq
 * va kalit, band joyda odam.
 */

// --------------------------------------------------------------------------
// Holat
// --------------------------------------------------------------------------
export const seatState = (seat) => {
  if (!seat.is_active) return seat.is_booked ? 'broken_booked' : 'broken'
  return seat.is_booked ? 'booked' : 'free'
}

/**
 * Talabgor HOZIR IMTIHONDA — sessiyasi yakunlanmagan.
 *
 * Server bunday joyni bo'shatishni ham, ko'chirishni ham rad etadi
 * (`seat_in_use`, `bookings.active_session`) — shart AYNAN o'sha:
 * yakunlanmagan har qanday holat, jumladan `ready` (kuzatuv rad etilib
 * FaceID sahifasida kutayotgan talabgor). Tugmalar shu yerda o'chiriladi,
 * himoya esa serverda.
 */
export const seatInExam = (seat) =>
  Boolean(seat?.is_booked && seat.session_status
    && !['finished', 'terminated', 'expired'].includes(seat.session_status))

export const IN_EXAM_HINT = 'Talabgor imtihonda — joyni bo‘shatib ham, ko‘chirib ham bo‘lmaydi'

/** Talabgor KELDIMI — sessiya holatidan (FaceID'dan o'tgan bo'lsa). */
const ARRIVAL = {
  in_progress: 'active',
  ready: 'active',
  face_check: 'active',
  technical_problem: 'active',
  finished: 'done',
  terminated: 'stopped',
}

const seatLabel = (seat) =>
  seat.computer_number != null ? String(seat.computer_number) : seat.inventory_code || '—'

// --------------------------------------------------------------------------
// "Vagonlar" — binolar
// --------------------------------------------------------------------------
export function ZoneRail({ zones, loading, value, onChange }) {
  const theme = useTheme()
  const compact = useMediaQuery(theme.breakpoints.down('md'))
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return needle
      ? zones.filter((zone) => `${zone.zone_name} ${zone.region_name}`.toLowerCase().includes(needle))
      : zones
  }, [zones, query])

  // Viloyat sarlavhasi faqat bir nechta viloyat bo'lsa — viloyat xodimi
  // uchun u har bir bino ustida takrorlanadigan shovqin bo'lardi.
  const multiRegion = new Set(zones.map((zone) => zone.region)).size > 1

  if (loading) {
    return (
      <Stack direction={compact ? 'row' : 'column'} spacing={1}>
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} variant="rounded" height={compact ? 56 : 76} width={compact ? 180 : '100%'} sx={{ borderRadius: '16px' }} />
        ))}
      </Stack>
    )
  }

  // TELEFONDA — gorizontal lenta (poyezd sxemasidagi vagon raqamlari):
  // vertikal ro'yxat zalni ekrandan pastga surib yuborardi.
  if (compact) {
    return (
      <Box
        sx={{
          display: 'flex', gap: 1, overflowX: 'auto', pb: 0.5, mx: -0.5, px: 0.5,
          scrollSnapType: 'x proximity', scrollbarWidth: 'none', '&::-webkit-scrollbar': { display: 'none' },
        }}
      >
        {zones.map((zone) => (
          <ZoneChip key={zone.zone} zone={zone} active={zone.zone === value} onClick={() => onChange(zone.zone)} />
        ))}
      </Box>
    )
  }

  let lastRegion = null
  return (
    <Card sx={{ p: 1.25, position: { lg: 'sticky' }, top: { lg: 24 } }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 1, pt: 0.5, pb: 1 }}>
        <ApartmentIcon fontSize="small" color="action" />
        <Typography variant="subtitle2" sx={{ flex: 1 }}>Binolar</Typography>
        <Chip size="small" label={zones.length} />
      </Stack>
      {zones.length > 6 && (
        <TextField
          size="small"
          placeholder="Bino yoki viloyat…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          sx={{ mb: 1, px: 0.5 }}
          InputProps={{
            startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
          }}
        />
      )}
      <Box sx={{ maxHeight: { lg: 'calc(100vh - 260px)' }, overflowY: 'auto', pr: 0.25 }}>
        {filtered.map((zone) => {
          const header = multiRegion && zone.region_name !== lastRegion
          lastRegion = zone.region_name
          return (
            <Box key={zone.zone}>
              {header && (
                <Typography
                  sx={{ px: 1.25, pt: 1.25, pb: 0.5, fontSize: 12, fontWeight: 650, color: 'text.secondary' }}
                >
                  {zone.region_name}
                </Typography>
              )}
              <ZoneItem zone={zone} active={zone.zone === value} onClick={() => onChange(zone.zone)} />
            </Box>
          )
        })}
        {!filtered.length && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2, textAlign: 'center' }}>
            Topilmadi
          </Typography>
        )}
      </Box>
    </Card>
  )
}

/** Bandlik chizig'i: band / bo'sh / buzilgan — uch bo'lak, bitta chiziq. */
function OccupancyBar({ zone, height = 6 }) {
  const total = Math.max(zone.total, 1)
  const part = (value) => `${(value / total) * 100}%`
  return (
    <Box sx={{ display: 'flex', height, borderRadius: 999, overflow: 'hidden', bgcolor: 'm3.surfaceContainerHighest' }}>
      <Box sx={{ width: part(zone.booked - zone.broken_booked), bgcolor: 'primary.main' }} />
      <Box sx={{ width: part(zone.broken), bgcolor: 'error.main' }} />
    </Box>
  )
}

function ZoneItem({ zone, active, onClick }) {
  const usable = zone.total - zone.broken
  return (
    <ButtonBase
      onClick={onClick}
      aria-current={active ? 'true' : undefined}
      sx={{
        width: '100%', display: 'block', textAlign: 'left', p: 1.25, mb: 0.5, borderRadius: '14px',
        bgcolor: active ? 'm3.secondaryContainer' : 'transparent',
        transition: (t) => t.transitions.create('background-color', { duration: t.motion.fast }),
        '&:hover': { bgcolor: active ? 'm3.secondaryContainer' : 'action.hover' },
      }}
    >
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 1 }}>
        <Box
          sx={{
            width: 34, height: 34, borderRadius: '10px', display: 'grid', placeItems: 'center', flexShrink: 0,
            bgcolor: active ? 'background.paper' : 'm3.surfaceContainerHigh',
            fontWeight: 750, fontSize: 13, color: 'm3.onSecondaryContainer',
          }}
        >
          {zone.zone_number ?? <ApartmentIcon sx={{ fontSize: 18 }} />}
        </Box>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography noWrap sx={{ fontSize: 13.5, fontWeight: active ? 700 : 600 }}>{zone.zone_name}</Typography>
          <Typography noWrap variant="caption" color="text.secondary" display="block">
            {zone.free} bo‘sh · {zone.booked}/{usable} band
          </Typography>
        </Box>
        {zone.broken_booked > 0 && (
          <Tooltip title={`${zone.broken_booked} ta talabgor buzilgan kompyuterda — ko‘chirish kerak`}>
            <WarningIcon color="error" sx={{ fontSize: 20 }} />
          </Tooltip>
        )}
      </Stack>
      <OccupancyBar zone={zone} />
    </ButtonBase>
  )
}

function ZoneChip({ zone, active, onClick }) {
  return (
    <ButtonBase
      onClick={onClick}
      sx={{
        flexShrink: 0, minWidth: 150, maxWidth: 220, p: 1.25, borderRadius: '14px', textAlign: 'left',
        display: 'block', scrollSnapAlign: 'start',
        border: 1, borderColor: active ? 'transparent' : 'divider',
        bgcolor: active ? 'm3.secondaryContainer' : 'm3.surfaceContainerLowest',
      }}
    >
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.75 }}>
        <Typography noWrap sx={{ fontSize: 13, fontWeight: 700, flex: 1 }}>{zone.zone_name}</Typography>
        {zone.broken_booked > 0 && <WarningIcon color="error" sx={{ fontSize: 16 }} />}
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
        {zone.free} bo‘sh · {zone.booked} band
      </Typography>
      <OccupancyBar zone={zone} height={4} />
    </ButtonBase>
  )
}

// --------------------------------------------------------------------------
// "Vagon ichi" — o'rindiqlar
// --------------------------------------------------------------------------
export function Legend({ counts }) {
  const items = [
    { key: 'free', label: 'Bo‘sh', value: counts.free },
    { key: 'booked', label: 'Band', value: counts.booked },
    { key: 'broken', label: 'Buzilgan', value: counts.broken },
  ]
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
      {items.map((item) => (
        <Stack key={item.key} direction="row" spacing={0.75} alignItems="center">
          <Box sx={{ width: 22, height: 20, position: 'relative' }}>
            <SeatShape state={item.key} mini />
          </Box>
          <Typography variant="body2" color="text.secondary">
            {item.label} <b>{item.value ?? 0}</b>
          </Typography>
        </Stack>
      ))}
      <Stack direction="row" spacing={0.75} alignItems="center">
        <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: 'success.main' }} />
        <Typography variant="body2" color="text.secondary">Talabgor keldi</Typography>
      </Stack>
    </Stack>
  )
}

/**
 * O'rindiq shakli: suyanchiq (tepadagi yoy) + o'rindiq.
 *
 * Shakl MUHIM: kvadrat plitkalar oddiy kalendar yoki klaviaturadek
 * ko'rinardi. Suyanchiq xaritani bir qarashda "zal" qiladi va
 * "Oldi" tomonini ham aytadi — suyanchiq doim orqada.
 */
function SeatShape({ state, selected, mini, dimmed }) {
  return (
    <Box
      aria-hidden
      sx={(theme) => {
        const tones = {
          free: {
            bg: theme.palette.m3.surfaceContainerLowest,
            border: theme.palette.m3.outline,
            back: theme.palette.m3.outlineVariant,
          },
          booked: {
            bg: theme.palette.m3.primaryContainer,
            border: theme.palette.primary.main,
            back: theme.palette.primary.main,
          },
          broken: {
            bg: alpha(theme.palette.error.main, theme.palette.mode === 'light' ? 0.07 : 0.16),
            border: theme.palette.error.main,
            back: alpha(theme.palette.error.main, 0.55),
          },
        }
        const tone = tones[state === 'broken_booked' ? 'broken' : state]
        const broken = state === 'broken' || state === 'broken_booked'
        return {
          position: 'absolute',
          inset: mini ? '3px 0 0 0' : '7px 0 0 0',
          borderRadius: mini ? '4px 4px 6px 6px' : '9px 9px 14px 14px',
          border: `${mini ? 1.5 : 2}px ${broken ? 'dashed' : 'solid'} ${tone.border}`,
          bgcolor: tone.bg,
          // Buzilgan joy — qiya chiziqlar: rangsiz ekranda ham ajraladi.
          backgroundImage: broken
            ? `repeating-linear-gradient(135deg, transparent 0 6px, ${alpha(theme.palette.error.main, 0.12)} 6px 8px)`
            : 'none',
          opacity: dimmed ? 0.35 : 1,
          boxShadow: selected ? `0 0 0 3px ${theme.palette.background.paper}, 0 0 0 5px ${theme.palette.primary.main}` : 'none',
          transition: theme.transitions.create(['box-shadow', 'opacity', 'transform'], { duration: 140 }),
          // Suyanchiq
          '&::before': {
            content: '""',
            position: 'absolute',
            left: '14%', right: '14%',
            top: mini ? -4 : -8,
            height: mini ? 3 : 5,
            borderRadius: 999,
            bgcolor: tone.back,
          },
        }
      }}
    />
  )
}

function SeatTile({ seat, selected, dimmed, pulse, onClick, size }) {
  const state = seatState(seat)
  const arrival = ARRIVAL[seat.session_status]
  const tooltip = [
    seat.computer_label,
    state === 'free' && 'Bo‘sh',
    (state === 'booked' || state === 'broken_booked') && `Band: ${seat.pinfl}`,
    (state === 'broken' || state === 'broken_booked') && 'Kompyuter buzilgan',
    seat.session_status && `Sessiya: ${STATUS_LABEL[seat.session_status] || seat.session_status}`,
    // Joy bir sessiyada bir necha talabgorga xizmat qiladi: clientda
    // «Yakunlash» bosilganda bron o'zi bo'shaydi (`release_after_session`).
    seat.finished_count > 0 && `Yakunlaganlar: ${seat.finished_count}`,
  ].filter(Boolean).join(' · ')

  return (
    <Tooltip title={tooltip} disableInteractive>
      <ButtonBase
        onClick={onClick}
        aria-label={tooltip}
        aria-pressed={selected}
        sx={{
          position: 'relative', width: size.w, height: size.h, borderRadius: '12px', flexShrink: 0,
          '&:hover .seat-shape, &:focus-visible .seat-shape': { transform: 'translateY(-2px)' },
          ...(pulse && {
            '@keyframes seatPulse': {
              '0%, 100%': { transform: 'scale(1)' },
              '50%': { transform: 'scale(1.07)' },
            },
            animation: 'seatPulse 1.6s ease-in-out infinite',
          }),
        }}
      >
        <Box className="seat-shape" sx={{ position: 'absolute', inset: 0, transition: 'transform 140ms' }}>
          <SeatShape state={state} selected={selected} dimmed={dimmed} />
        </Box>
        <Stack
          alignItems="center"
          spacing={0.25}
          sx={{ position: 'relative', pt: '7px', opacity: dimmed ? 0.45 : 1 }}
        >
          <Typography
            sx={{
              fontSize: size.font, fontWeight: 800, lineHeight: 1, letterSpacing: '-0.02em',
              color: state === 'free' ? 'text.primary' : state === 'booked' ? 'm3.onPrimaryContainer' : 'error.main',
              textDecoration: state === 'broken' ? 'line-through' : 'none',
              maxWidth: size.w - 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >
            {seatLabel(seat)}
          </Typography>
          {state === 'booked' && <PersonIcon sx={{ fontSize: size.icon, color: 'primary.main' }} />}
          {state === 'broken' && <BuildIcon sx={{ fontSize: size.icon, color: 'error.main' }} />}
          {state === 'broken_booked' && <WarningIcon sx={{ fontSize: size.icon, color: 'error.main' }} />}
        </Stack>
        {arrival && (
          <Box
            sx={{
              position: 'absolute', top: 3, right: -3, width: 12, height: 12, borderRadius: '50%',
              border: 2, borderColor: 'background.paper',
              bgcolor: arrival === 'active' ? 'success.main' : arrival === 'done' ? 'info.main' : 'error.main',
            }}
          />
        )}
      </ButtonBase>
    </Tooltip>
  )
}

/**
 * Zal: o'rindiqlar qatorlarga bo'linadi, o'rtada YO'LAK (qator raqami
 * bilan). Ustunlar soni ekranga qarab — telefonda 4 ta, keng ekranda 10
 * ta: zal kengligi haqiqiy xonani takrorlamaydi (bu ma'lumot bizda yo'q),
 * u faqat raqamlarni o'qiladigan tartibda joylaydi.
 */
export function SeatGrid({ seats, selectedId, onSelect, moveMode, highlightId }) {
  const theme = useTheme()
  const xs = useMediaQuery(theme.breakpoints.down('sm'))
  const size = xs ? { w: 56, h: 60, font: 16, icon: 16 } : { w: 62, h: 64, font: 17, icon: 17 }
  const gap = 10
  const aisle = xs ? 22 : 30

  // Ustunlar soni KARTANING haqiqiy kengligidan — ekran nuqtasidan emas:
  // yon panel yoyilgan/yig'ilgani va bino ro'yxati bir xil ekranda zalga
  // har xil joy qoldiradi. Ekran nuqtasiga qarab tanlanganda 1440 px da
  // 10 ustun sig'masdan o'ng qator kesilib qolgan edi.
  const [width, setWidth] = useState(0)
  const measureRef = useCallback((node) => {
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(node)
  }, [])
  const fit = Math.floor((width - aisle + gap) / (size.w + gap))
  // Juft son (yo'lak o'rtada), 4..12 oralig'ida.
  const cols = Math.max(4, Math.min(12, fit - (fit % 2))) || 4
  const half = cols / 2

  const rows = useMemo(() => {
    const out = []
    for (let i = 0; i < seats.length; i += cols) out.push(seats.slice(i, i + cols))
    return out
  }, [seats, cols])

  return (
    <Box ref={measureRef} sx={{ overflowX: 'auto', pb: 1 }}>
      <Stack spacing={1.75} alignItems="center" sx={{ minWidth: 'fit-content', mx: 'auto', pt: 1 }}>
        {/* Zalning OLDI — proktor stoli. Poyezd sxemasidagi "harakat
            yo'nalishi" bilan bir xil vazifa: operator talabgorga
            "oldidan uchinchi qator" deb aytadi. */}
        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          justifyContent="center"
          sx={{
            width: '100%', py: 0.75, mb: 0.5, borderRadius: 999, color: 'text.secondary',
            bgcolor: 'm3.surfaceContainerHigh', border: 1, borderColor: 'divider', borderStyle: 'dashed',
          }}
        >
          <ScreenIcon sx={{ fontSize: 18 }} />
          <Typography variant="caption" fontWeight={650} letterSpacing="0.04em">
            OLDI · PROKTOR STOLI
          </Typography>
        </Stack>

        {rows.map((row, rowIndex) => {
          // Oxirgi qator to'lmagan bo'lsa bo'sh katak bilan to'ldiriladi:
          // aks holda yo'lak chapga siljib, ustunlar qator-qator
          // mos kelmay qolardi.
          const padded = [...row, ...Array(cols - row.length).fill(null)]
          return (
            <Stack key={rowIndex} direction="row" spacing={1.25} alignItems="center">
              {padded.slice(0, half).map((seat, index) => renderSeat(seat, index))}
              {/* Yo'lak — qator raqami bilan. */}
              <Box sx={{ width: xs ? 22 : 30, textAlign: 'center', flexShrink: 0 }}>
                <Typography variant="caption" color="text.disabled" fontWeight={700}>
                  {rowIndex + 1}
                </Typography>
              </Box>
              {padded.slice(half).map((seat, index) => renderSeat(seat, half + index))}
            </Stack>
          )
        })}
      </Stack>
    </Box>
  )

  function renderSeat(seat, index) {
    if (!seat) return <Box key={`gap-${index}`} sx={{ width: size.w, flexShrink: 0 }} />
    const state = seatState(seat)
    const target = moveMode && state === 'free'
    return (
      <SeatTile
        key={seat.id}
        seat={seat}
        size={size}
        selected={seat.id === selectedId}
        // Ko'chirish rejimida faqat bo'sh joylar "tirik": qolganlari
        // xiralashadi, bo'shlar esa tebranadi — tanlash kerak bo'lgan
        // narsa o'zi ko'zga tashlanadi.
        dimmed={moveMode && !target && seat.id !== selectedId}
        pulse={target || seat.id === highlightId}
        onClick={() => onSelect(seat)}
      />
    )
  }
}

// --------------------------------------------------------------------------
// O'rindiq paneli
// --------------------------------------------------------------------------
/**
 * Tanlangan o'rindiq: ma'lumot va amallar.
 *
 * Kompyuterda o'ng panel, telefonda PASTDAN chiqadigan varaq (M3 bottom
 * sheet) — barmoq ekranning pastki qismiga yetadi, yuqori burchakka emas.
 *
 * Amallar ruxsatga qarab: `bookings.manage` bo'lmasa panel faqat
 * ma'lumot beradi va buni ochiq aytadi — tugmalarni yashirib, sababsiz
 * qoldirish "tizim buzilgan" degan taassurot berardi.
 */
export function SeatPanel({
  seat, zoneName, canManage, busy, onClose, onAssign, onRelease, onStartMove, onToggleActive,
}) {
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('md'))
  const [pinfl, setPinfl] = useState('')
  const open = Boolean(seat)
  const state = seat ? seatState(seat) : null
  const validPinfl = /^\d{14}$/.test(pinfl)

  const submit = () => {
    if (!validPinfl || busy) return
    onAssign(seat, pinfl)
    setPinfl('')
  }

  return (
    <Drawer
      anchor={mobile ? 'bottom' : 'right'}
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: mobile
          ? { borderRadius: '28px 28px 0 0', maxHeight: '85vh', pb: 'env(safe-area-inset-bottom)' }
          : { width: 400, borderRadius: '28px 0 0 28px' },
      }}
    >
      {seat && (
        <Stack sx={{ p: 3, gap: 2.5 }}>
          {mobile && (
            <Box sx={{ width: 36, height: 4, borderRadius: 999, bgcolor: 'text.disabled', mx: 'auto', mt: -1.5, opacity: 0.4 }} />
          )}
          <Stack direction="row" spacing={2} alignItems="center">
            <Box sx={{ position: 'relative', width: 64, height: 66, flexShrink: 0 }}>
              <SeatShape state={state} />
              <Typography
                sx={{
                  position: 'relative', pt: '18px', textAlign: 'center', fontSize: 22, fontWeight: 800,
                  color: state === 'free' ? 'text.primary' : state === 'booked' ? 'm3.onPrimaryContainer' : 'error.main',
                }}
              >
                {seatLabel(seat)}
              </Typography>
            </Box>
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography variant="h6" noWrap>{seat.computer_label}</Typography>
              <Typography variant="body2" color="text.secondary" noWrap>
                {zoneName || seat.zone_name}{seat.region_name ? ` · ${seat.region_name}` : ''}
              </Typography>
            </Box>
            <IconButton onClick={onClose} aria-label="Yopish" sx={{ alignSelf: 'flex-start' }}>
              <CloseIcon />
            </IconButton>
          </Stack>

          <StatePill state={state} />

          {seat.finished_count > 0 && (
            <Typography variant="body2" color="text.secondary">
              Bu joyda {seat.finished_count} talabgor testni yakunlagan
              {seat.last_finished_at ? ` · oxirgisi ${fromNow(seat.last_finished_at)}` : ''} — joy
              yakunda avtomatik bo‘shatiladi.
            </Typography>
          )}

          {(state === 'booked' || state === 'broken_booked') && (
            <Card variant="outlined" sx={{ p: 2, bgcolor: 'm3.surfaceContainerLow' }}>
              <Typography variant="caption" color="text.secondary">Talabgor (JSHSHIR)</Typography>
              <Typography sx={{ fontFamily: 'monospace', fontSize: 18, fontWeight: 700, letterSpacing: 1 }}>
                {seat.pinfl}
              </Typography>
              <Divider sx={{ my: 1.25 }} />
              <Info label="Sessiya" value={seat.session_status ? STATUS_LABEL[seat.session_status] : 'Hali kelmagan'} />
              <Info label="Biriktirilgan" value={seat.booked_at ? fromNow(seat.booked_at) : '—'} />
              {seat.booked_by_name && <Info label="Kim biriktirgan" value={seat.booked_by_name} />}
            </Card>
          )}

          {seatInExam(seat) && (
            <Alert severity="info" icon={<LockIcon />}>
              {IN_EXAM_HINT}. Kerak bo‘lsa sessiyani chetlashtiring — joy o‘zi bo‘shaydi. Talabgor
              «Yakunlash» ni bosganda ham joy avtomatik bo‘shaydi.
            </Alert>
          )}

          {state === 'broken_booked' && !seatInExam(seat) && (
            <Alert severity="error" icon={<WarningIcon />}>
              Kompyuter buzilgan — imtihon kuni client bu talabgorni qabul qilmaydi. Uni boshqa bo‘sh
              joyga ko‘chiring.
            </Alert>
          )}

          {!canManage ? (
            <Alert severity="info" icon={<LockIcon />}>
              Sizda faqat ko‘rish huquqi bor — bronni o‘zgartirish uchun «bookings.manage» kerak.
            </Alert>
          ) : (
            <>
              {state === 'free' && (
                <Stack spacing={1.25}>
                  <TextField
                    label="Talabgor JSHSHIR"
                    value={pinfl}
                    autoFocus={!mobile}
                    onChange={(event) => setPinfl(event.target.value.replace(/\D/g, '').slice(0, 14))}
                    onKeyDown={(event) => event.key === 'Enter' && submit()}
                    helperText={`${pinfl.length} / 14`}
                    inputProps={{ inputMode: 'numeric', style: { fontFamily: 'monospace', letterSpacing: 2 } }}
                  />
                  <Button
                    variant="contained"
                    size="large"
                    startIcon={busy ? <CircularProgress size={18} color="inherit" /> : <AssignIcon />}
                    disabled={!validPinfl || busy}
                    onClick={submit}
                  >
                    Shu joyga biriktirish
                  </Button>
                </Stack>
              )}

              {(state === 'booked' || state === 'broken_booked') && (
                <Stack spacing={1}>
                  <Button
                    variant={state === 'broken_booked' ? 'contained' : 'outlined'}
                    color={state === 'broken_booked' ? 'error' : 'primary'}
                    size="large"
                    startIcon={<MoveIcon />}
                    disabled={busy || seatInExam(seat)}
                    onClick={() => onStartMove(seat)}
                  >
                    Boshqa joyga ko‘chirish
                  </Button>
                  <Button
                    color="inherit"
                    startIcon={<ReleaseIcon />}
                    disabled={busy || seatInExam(seat)}
                    onClick={() => onRelease(seat)}
                  >
                    Joyni bo‘shatish
                  </Button>
                </Stack>
              )}

              <Divider />
              <Stack direction="row" alignItems="center" spacing={1.5}>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="subtitle2">Ishchi holatda</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Buzilgan kompyuterga talabgor biriktirilmaydi
                  </Typography>
                </Box>
                <Switch
                  checked={seat.is_active}
                  disabled={busy}
                  onChange={(event) => onToggleActive(seat, event.target.checked)}
                  inputProps={{ 'aria-label': 'Ishchi holatda' }}
                />
              </Stack>
            </>
          )}
          {busy && <LinearProgress sx={{ borderRadius: 999 }} />}
        </Stack>
      )}
    </Drawer>
  )
}

function StatePill({ state }) {
  const map = {
    free: { label: 'Bo‘sh — talabgor qabul qiladi', color: 'success' },
    booked: { label: 'Band', color: 'primary' },
    broken: { label: 'Buzilgan — ishlatilmaydi', color: 'error' },
    broken_booked: { label: 'Buzilgan, lekin band', color: 'error' },
  }[state]
  return <Chip label={map.label} color={map.color} variant="outlined" sx={{ alignSelf: 'flex-start' }} />
}

function Info({ label, value }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.25 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" fontWeight={600} sx={{ textAlign: 'right' }}>{value}</Typography>
    </Stack>
  )
}
