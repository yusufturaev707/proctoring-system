import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import BackIcon from '@mui/icons-material/ArrowBackRounded'
import ChevronIcon from '@mui/icons-material/ChevronRightRounded'
import RegionIcon from '@mui/icons-material/MapOutlined'

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
 *   ZoneRail   — "vagonlar": avval viloyatlar (DTM ID tartibida), keyin
 *                tanlangan viloyatning binolari; har birining bandlik
 *                chizig'i bilan;
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
// "Vagonlar" — viloyat -> bino
// --------------------------------------------------------------------------
/**
 * Binolar ro'yxatidan viloyat kesimi — bitta o'tishda, qo'shimcha
 * so'rovsiz (`zones/` allaqachon GROUP BY natijasi). Tartib — server
 * bergan DTM ID tartibi.
 */
export function groupRegions(zones) {
  const map = new Map()
  for (const zone of zones) {
    let region = map.get(zone.region)
    if (!region) {
      region = {
        region: zone.region, region_name: zone.region_name, region_dtm_id: zone.region_dtm_id,
        zones: 0, total: 0, booked: 0, free: 0, broken: 0, broken_booked: 0,
      }
      map.set(zone.region, region)
    }
    region.zones += 1
    for (const key of ['total', 'booked', 'free', 'broken', 'broken_booked']) region[key] += zone[key]
  }
  return [...map.values()].sort((a, b) => (a.region_dtm_id ?? 0) - (b.region_dtm_id ?? 0))
}

/**
 * Chap panel — IKKI BOSQICH: viloyatlar, keyin tanlangan viloyatning
 * binolari. Ilgari hamma binolar bitta ro'yxatda edi va umumiy sessiyada
 * yuzlab bino orasidan kerakligini topish uchun uzoq aylantirish kerak
 * edi. Viloyat bitta bo'lsa (viloyat xodimi) birinchi bosqich
 * o'tkazib yuboriladi — tanlaydigan narsa yo'q.
 */
export function ZoneRail({ zones, loading, regionId, zoneId, onRegion, onZone }) {
  const theme = useTheme()
  const compact = useMediaQuery(theme.breakpoints.down('md'))
  const [query, setQuery] = useState('')

  const regions = useMemo(() => groupRegions(zones), [zones])
  const region = regions.find((item) => item.region === regionId) || null
  const singleRegion = regions.length === 1
  const level = region ? 'zones' : 'regions'
  const regionZones = useMemo(
    () => (region ? zones.filter((zone) => zone.region === region.region) : []),
    [zones, region],
  )

  // Qidiruv faqat joriy bosqichda; bosqich almashsa tozalanadi.
  useEffect(() => setQuery(''), [level, regionId])
  const needle = query.trim().toLowerCase()
  const items = level === 'regions'
    ? regions.filter((item) => !needle || `${item.region_name} ${item.region_dtm_id}`.toLowerCase().includes(needle))
    : regionZones.filter((item) => !needle || `${item.zone_name} ${item.zone_number}`.toLowerCase().includes(needle))
  const count = level === 'regions' ? regions.length : regionZones.length

  if (loading) {
    return (
      <Stack direction={compact ? 'row' : 'column'} spacing={1}>
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} variant="rounded" height={compact ? 56 : 76} width={compact ? 180 : '100%'} sx={{ borderRadius: '16px' }} />
        ))}
      </Stack>
    )
  }

  const back = region && !singleRegion ? () => onRegion(null) : null

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
        {back && (
          <ButtonBase
            onClick={back}
            aria-label="Viloyatlarga qaytish"
            sx={{
              flexShrink: 0, px: 1.5, borderRadius: '14px', gap: 0.5, fontSize: 13, fontWeight: 650,
              bgcolor: 'm3.surfaceContainerHigh', color: 'text.secondary',
            }}
          >
            <BackIcon sx={{ fontSize: 18 }} /> {region.region_name}
          </ButtonBase>
        )}
        {level === 'regions'
          ? regions.map((item) => (
            <RailChip key={item.region} item={item} title={item.region_name} onClick={() => onRegion(item.region)} />
          ))
          : regionZones.map((item) => (
            <RailChip
              key={item.zone} item={item} title={item.zone_name}
              active={item.zone === zoneId} onClick={() => onZone(item.zone)}
            />
          ))}
      </Box>
    )
  }

  return (
    <Card sx={{ p: 1.25, position: { lg: 'sticky' }, top: { lg: 24 } }}>
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ px: 0.5, pt: 0.25, pb: 1, minHeight: 40 }}>
        {back ? (
          <Tooltip title="Viloyatlarga qaytish">
            <IconButton size="small" onClick={back} aria-label="Viloyatlarga qaytish">
              <BackIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : (
          <Box sx={{ width: 30, display: 'grid', placeItems: 'center' }}>
            {level === 'regions'
              ? <RegionIcon fontSize="small" color="action" />
              : <ApartmentIcon fontSize="small" color="action" />}
          </Box>
        )}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" noWrap>
            {level === 'regions' ? 'Viloyatlar' : region.region_name}
          </Typography>
          {level === 'zones' && (
            <Typography variant="caption" color="text.secondary" display="block" noWrap>
              Binoni tanlang
            </Typography>
          )}
        </Box>
        <Chip size="small" label={count} />
      </Stack>
      {count > 6 && (
        <TextField
          size="small"
          fullWidth
          placeholder={level === 'regions' ? 'Viloyat…' : 'Bino…'}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          sx={{ mb: 1, px: 0.5 }}
          InputProps={{
            startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
          }}
        />
      )}
      <Box sx={{ maxHeight: { lg: 'calc(100vh - 240px)' }, overflowY: 'auto', pr: 0.25 }}>
        {level === 'regions'
          ? items.map((item) => (
            <RailItem
              key={item.region}
              item={item}
              badge={item.region_dtm_id}
              title={item.region_name}
              meta={`${item.zones} bino · ${item.free} bo‘sh`}
              trailing={<ChevronIcon fontSize="small" sx={{ color: 'text.secondary' }} />}
              onClick={() => onRegion(item.region)}
            />
          ))
          : items.map((item) => (
            <RailItem
              key={item.zone}
              item={item}
              badge={item.zone_number ?? <ApartmentIcon sx={{ fontSize: 18 }} />}
              title={item.zone_name}
              meta={`${item.free} bo‘sh · ${item.booked}/${item.total - item.broken} band`}
              active={item.zone === zoneId}
              onClick={() => onZone(item.zone)}
            />
          ))}
        {!items.length && (
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

/** Ro'yxat qatori — viloyat ham, bino ham (MD3 list item + bandlik chizig'i). */
function RailItem({ item, badge, title, meta, trailing, active, onClick }) {
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
            minWidth: 34, height: 34, px: 0.5, borderRadius: '10px', display: 'grid', placeItems: 'center',
            flexShrink: 0, bgcolor: active ? 'background.paper' : 'm3.surfaceContainerHigh',
            fontWeight: 750, fontSize: 13, color: 'm3.onSecondaryContainer',
          }}
        >
          {badge}
        </Box>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography noWrap sx={{ fontSize: 13.5, fontWeight: active ? 700 : 600 }}>{title}</Typography>
          <Typography noWrap variant="caption" color="text.secondary" display="block">{meta}</Typography>
        </Box>
        {item.broken_booked > 0 && (
          <Tooltip title={`${item.broken_booked} ta talabgor buzilgan kompyuterda — ko‘chirish kerak`}>
            <WarningIcon color="error" sx={{ fontSize: 20 }} />
          </Tooltip>
        )}
        {trailing}
      </Stack>
      <OccupancyBar zone={item} />
    </ButtonBase>
  )
}

function RailChip({ item, title, active, onClick }) {
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
        <Typography noWrap sx={{ fontSize: 13, fontWeight: 700, flex: 1 }}>{title}</Typography>
        {item.broken_booked > 0 && <WarningIcon color="error" sx={{ fontSize: 16 }} />}
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
        {item.free} bo‘sh · {item.booked} band
      </Typography>
      <OccupancyBar zone={item} height={4} />
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

/**
 * O'rindiq TEZKOR YO'LDA chiziladi: 500 kompyuterli bino ham bir zumda.
 *
 * Ilgari har o'rindiq MUI `Tooltip` + `ButtonBase` (ripple bilan) +
 * to'rt-besh `sx` Box + `Typography` edi va har bosishda 500 tasi ham
 * qaytadan chizilardi: emotion har birining stilini qayta seriyalar,
 * har `Tooltip` o'z Popper tinglovchilarini ulardi. Endi:
 *
 *   * o'rindiq — oddiy `<button>` va data-atributlar; butun ko'rinish
 *     BITTA stil blokida (`seatStyles`, zal konteynerida, har holat uchun
 *     bir marta) - o'rindiq sonidan qat'i nazar;
 *   * `memo`: tanlov o'zgarsa faqat ikki o'rindiq (eski va yangi)
 *     qayta chiziladi;
 *   * tooltip BITTA (`HoverTip`), hodisa delegatsiyasi bilan;
 *   * ekrandan tashqaridagi qatorlar chizilmaydi (`content-visibility`).
 *
 * Ko'rinish `SeatShape` bilan AYNAN bir xil (belgilar paneli hali uni
 * ishlatadi) - rang yoki shaklni o'zgartirsangiz, ikkala joyda ham.
 */
const SEAT_ICON = { booked: PersonIcon, broken: BuildIcon, broken_booked: WarningIcon }

const seatTooltip = (seat, state) => [
  seat.computer_label,
  state === 'free' && 'Bo‘sh',
  (state === 'booked' || state === 'broken_booked') && `Band: ${seat.pinfl}`,
  (state === 'broken' || state === 'broken_booked') && 'Kompyuter buzilgan',
  seat.session_status && `Sessiya: ${STATUS_LABEL[seat.session_status] || seat.session_status}`,
  // Joy bir sessiyada bir necha talabgorga xizmat qiladi: clientda
  // «Yakunlash» bosilganda bron o'zi bo'shaydi (`release_after_session`).
  seat.finished_count > 0 && `Yakunlaganlar: ${seat.finished_count}`,
].filter(Boolean).join(' · ')

const SeatTile = memo(function SeatTile({ seat, selected, dimmed, pulse, onSelect }) {
  const state = seatState(seat)
  const Icon = SEAT_ICON[state]
  const arrival = ARRIVAL[seat.session_status]
  return (
    <button
      type="button"
      className="seat"
      data-state={state}
      data-selected={selected || undefined}
      data-dimmed={dimmed || undefined}
      data-pulse={pulse || undefined}
      aria-label={seatTooltip(seat, state)}
      aria-pressed={selected}
      onClick={() => onSelect(seat)}
    >
      <span className="seat-shape" />
      <span className="seat-body">
        <span className="seat-num">{seatLabel(seat)}</span>
        {Icon && <Icon className="seat-icon" fontSize="inherit" />}
      </span>
      {arrival && <span className="seat-dot" data-arrival={arrival} />}
    </button>
  )
})

/** Zalning barcha o'rindiqlari uchun BITTA stil bloki. */
function seatStyles(theme, size, rowWidth) {
  const { m3 } = theme.palette
  const error = theme.palette.error.main
  const brokenTone = {
    bgcolor: alpha(error, theme.palette.mode === 'light' ? 0.07 : 0.16),
    borderColor: error,
    borderStyle: 'dashed',
    // Buzilgan joy — qiya chiziqlar: rangsiz ekranda ham ajraladi.
    backgroundImage: `repeating-linear-gradient(135deg, transparent 0 6px, ${alpha(error, 0.12)} 6px 8px)`,
    '&::before': { bgcolor: alpha(error, 0.55) },
  }
  return {
    '@keyframes seatPulse': {
      '0%, 100%': { transform: 'scale(1)' },
      '50%': { transform: 'scale(1.07)' },
    },
    '& .seat-row': {
      display: 'flex', alignItems: 'center', gap: '10px',
      // Ekrandan tashqaridagi qator chizilmaydi; o'lchami oldindan
      // aytiladi - aks holda skroll chizig'i sakrardi.
      contentVisibility: 'auto',
      containIntrinsicSize: `auto ${rowWidth}px auto ${size.h}px`,
    },
    '& .seat-gap': { width: size.w, flexShrink: 0 },
    '& .seat-aisle': {
      ...theme.typography.caption, width: size.aisle, textAlign: 'center', flexShrink: 0,
      color: theme.palette.text.disabled, fontWeight: 700,
    },
    '& .seat': {
      position: 'relative', display: 'block', flexShrink: 0, width: size.w, height: size.h,
      p: 0, m: 0, border: 0, borderRadius: '12px', background: 'none', cursor: 'pointer',
      font: 'inherit', color: 'inherit', outline: 0, WebkitTapHighlightColor: 'transparent',
    },
    '& .seat[data-pulse]': { animation: 'seatPulse 1.6s ease-in-out infinite' },
    '& .seat-shape': {
      position: 'absolute', inset: '7px 0 0 0', borderRadius: '9px 9px 14px 14px',
      border: '2px solid', bgcolor: m3.surfaceContainerLowest, borderColor: m3.outline,
      transition: theme.transitions.create(['box-shadow', 'opacity', 'transform'], { duration: 140 }),
      // Suyanchiq
      '&::before': {
        content: '""', position: 'absolute', left: '14%', right: '14%', top: -8, height: 5,
        borderRadius: 999, bgcolor: m3.outlineVariant,
      },
    },
    '& .seat:hover .seat-shape, & .seat:focus-visible .seat-shape': { transform: 'translateY(-2px)' },
    '& .seat[data-state="booked"] .seat-shape': {
      bgcolor: m3.primaryContainer, borderColor: theme.palette.primary.main,
      '&::before': { bgcolor: theme.palette.primary.main },
    },
    '& .seat[data-state="broken"] .seat-shape, & .seat[data-state="broken_booked"] .seat-shape': brokenTone,
    '& .seat[data-selected] .seat-shape': {
      boxShadow: `0 0 0 3px ${theme.palette.background.paper}, 0 0 0 5px ${theme.palette.primary.main}`,
    },
    '& .seat[data-dimmed] .seat-shape': { opacity: 0.35 },
    '& .seat-body': {
      position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center',
      gap: '2px', pt: '7px',
    },
    '& .seat[data-dimmed] .seat-body': { opacity: 0.45 },
    '& .seat-num': {
      fontFamily: theme.typography.fontFamily, fontSize: size.font, fontWeight: 800, lineHeight: 1,
      letterSpacing: '-0.02em', color: theme.palette.text.primary,
      maxWidth: size.w - 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .seat[data-state="booked"] .seat-num': { color: m3.onPrimaryContainer },
    '& .seat[data-state="broken"] .seat-num, & .seat[data-state="broken_booked"] .seat-num': { color: error },
    '& .seat[data-state="broken"] .seat-num': { textDecoration: 'line-through' },
    '& .seat-icon': { fontSize: size.icon, color: error },
    '& .seat[data-state="booked"] .seat-icon': { color: theme.palette.primary.main },
    '& .seat-dot': {
      position: 'absolute', top: 3, right: -3, width: 12, height: 12, borderRadius: '50%',
      border: `2px solid ${theme.palette.background.paper}`, bgcolor: theme.palette.error.main,
    },
    '& .seat-dot[data-arrival="active"]': { bgcolor: theme.palette.success.main },
    '& .seat-dot[data-arrival="done"]': { bgcolor: theme.palette.info.main },
  }
}

/**
 * Zal uchun BITTA tooltip. Holati shu komponentda: sichqoncha
 * o'rindiqdan o'rindiqqa o'tganda zal (500 o'rindiq) qayta chizilmaydi.
 * Matn o'rindiqning `aria-label` idan — ekran o'quvchisi bilan bir manba.
 */
function HoverTip({ containerRef }) {
  const [tip, setTip] = useState(null)
  useEffect(() => {
    const node = containerRef.current
    if (!node) return undefined
    const show = (event) => {
      const el = event.target.closest?.('.seat')
      setTip((prev) => {
        if (!el) return null
        return prev?.el === el ? prev : { el, text: el.getAttribute('aria-label') }
      })
    }
    const hide = () => setTip(null)
    node.addEventListener('mouseover', show)
    node.addEventListener('focusin', show)
    node.addEventListener('mouseleave', hide)
    node.addEventListener('focusout', hide)
    node.addEventListener('scroll', hide, true)
    return () => {
      node.removeEventListener('mouseover', show)
      node.removeEventListener('focusin', show)
      node.removeEventListener('mouseleave', hide)
      node.removeEventListener('focusout', hide)
      node.removeEventListener('scroll', hide, true)
    }
  }, [containerRef])
  // O'rindiq ro'yxatdan chiqib ketsa (bino almashdi) - tooltip osilib qolmasin.
  const open = Boolean(tip?.el?.isConnected)
  return (
    <Tooltip
      open={open}
      title={tip?.text || ''}
      disableHoverListener
      disableFocusListener
      disableTouchListener
      slotProps={{ popper: { anchorEl: tip?.el } }}
    >
      <span style={{ position: 'absolute', width: 0, height: 0 }} />
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
  const size = useMemo(
    () => (xs
      ? { w: 56, h: 60, font: 16, icon: 16, aisle: 22 }
      : { w: 62, h: 64, font: 17, icon: 17, aisle: 30 }),
    [xs],
  )
  const gap = 10

  // Ustunlar soni KARTANING haqiqiy kengligidan — ekran nuqtasidan emas:
  // yon panel yoyilgan/yig'ilgani va bino ro'yxati bir xil ekranda zalga
  // har xil joy qoldiradi. Ekran nuqtasiga qarab tanlanganda 1440 px da
  // 10 ustun sig'masdan o'ng qator kesilib qolgan edi.
  //
  // Holatda USTUNLAR SONI saqlanadi, piksel kenglik emas: oyna
  // cho'zilganda har piksel uchun zalni qayta chizish shart emas.
  const containerRef = useRef(null)
  const [cols, setCols] = useState(4)
  useEffect(() => {
    const node = containerRef.current
    if (!node) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const fit = Math.floor((entry.contentRect.width - size.aisle + gap) / (size.w + gap))
      // Juft son (yo'lak o'rtada), 4..12 oralig'ida.
      setCols(Math.max(4, Math.min(12, fit - (fit % 2))) || 4)
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [size])
  const half = cols / 2
  const rowWidth = cols * size.w + cols * gap + size.aisle

  // Sahifa `onSelect` ni har chizishda yangidan yaratadi; o'rindiqlarga
  // BARQAROR funksiya beriladi, aks holda `memo` hech narsani to'smasdi.
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const select = useCallback((seat) => onSelectRef.current(seat), [])

  const rows = useMemo(() => {
    const out = []
    for (let i = 0; i < seats.length; i += cols) out.push(seats.slice(i, i + cols))
    return out
  }, [seats, cols])
  const styles = useMemo(() => seatStyles(theme, size, rowWidth), [theme, size, rowWidth])

  const renderSeat = (seat, index) => {
    if (!seat) return <span key={`gap-${index}`} className="seat-gap" />
    const target = moveMode && seatState(seat) === 'free'
    return (
      <SeatTile
        key={seat.id}
        seat={seat}
        selected={seat.id === selectedId}
        // Ko'chirish rejimida faqat bo'sh joylar "tirik": qolganlari
        // xiralashadi, bo'shlar esa tebranadi — tanlash kerak bo'lgan
        // narsa o'zi ko'zga tashlanadi.
        dimmed={Boolean(moveMode && !target && seat.id !== selectedId)}
        pulse={Boolean(target || seat.id === highlightId)}
        onSelect={select}
      />
    )
  }

  return (
    <Box ref={containerRef} sx={{ overflowX: 'auto', pb: 1, position: 'relative', ...styles }}>
      <HoverTip containerRef={containerRef} />
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
          const padded = row.length < cols ? [...row, ...Array(cols - row.length).fill(null)] : row
          return (
            <div key={rowIndex} className="seat-row">
              {padded.slice(0, half).map((seat, index) => renderSeat(seat, index))}
              {/* Yo'lak — qator raqami bilan. */}
              <span className="seat-aisle">{rowIndex + 1}</span>
              {padded.slice(half).map((seat, index) => renderSeat(seat, half + index))}
            </div>
          )
        })}
      </Stack>
    </Box>
  )
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
