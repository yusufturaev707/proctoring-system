import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  DragEvent, KeyboardEvent, MouseEvent, PointerEvent as ReactPointerEvent, ReactNode,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Autocomplete, Box, Button, Chip, CircularProgress, Dialog, Divider, IconButton,
  InputAdornment, Stack, TextField, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import type { Theme } from '@mui/material/styles'
import type { SystemStyleObject } from '@mui/system'
import AttachIcon from '@mui/icons-material/AddToQueueOutlined'
import PcIcon from '@mui/icons-material/DesktopWindowsOutlined'
import SeatIcon from '@mui/icons-material/EventSeatOutlined'
import CloseIcon from '@mui/icons-material/CloseRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import CheckIcon from '@mui/icons-material/CheckRounded'
import LockIcon from '@mui/icons-material/LockOutlined'
import PersonIcon from '@mui/icons-material/PersonRounded'
import HistoryIcon from '@mui/icons-material/HistoryRounded'
import BuildIcon from '@mui/icons-material/BuildCircleOutlined'
import ScreenIcon from '@mui/icons-material/CoPresentOutlined'
import DropIcon from '@mui/icons-material/OpenWithRounded'
import SelectAllIcon from '@mui/icons-material/SelectAllRounded'
import NextIcon from '@mui/icons-material/ChevronRightRounded'
import PrevIcon from '@mui/icons-material/ChevronLeftRounded'
import AllNextIcon from '@mui/icons-material/KeyboardDoubleArrowRightRounded'
import AllPrevIcon from '@mui/icons-material/KeyboardDoubleArrowLeftRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import ApartmentIcon from '@mui/icons-material/ApartmentOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'

import ConfirmDialog from '../ConfirmDialog'
import { HoverTip } from './SeatMap'
import { computerBookings as bookingsApi } from '../../api/endpoints'
import { useUi } from '../../context/UiContext'
import type { Option } from '../data/types'
import type { ApiRecord, Id } from '../../types/api'

/**
 * Kompyuterlarni test sessiyasiga QO'LDA biriktirish.
 *
 * «Joylarni yaratish» binoning HAMMA kompyuterini sessiyaga qo'shadi, lekin
 * zalda zaxira, boshqa imtihonga ajratilgan yoki shu kuni ishlatilmaydigan
 * mashinalar bo'ladi — erkin joylashuvda esa sessiyadagi har bo'sh stol
 * talabgor QABUL QILADI. Shuning uchun administrator ro'yxatni ko'zi bilan
 * tuzadi: viloyat → bino, chapda binoning sessiyaga kiritilmagan ishchi
 * kompyuterlari, o'ngda sessiyadagilar.
 *
 * Tanlash — fayl menejeridagidek: bosish (qo'shib/olib tashlaydi), Shift
 * bilan oraliq, sichqoncha bilan ramka (lasso), Ctrl+A. Tanlanganlar BIR
 * VAQTDA narigi panelga tortiladi yoki o'rtadagi tugmalar bilan o'tkaziladi
 * (sensorli ekranda HTML5 drag ishlamaydi — tugmalar majburiy).
 *
 * O'zgarishlar avval LOKAL (yashil «+», sariq «−» belgisi) va «Saqlash» da
 * bitta so'rov bilan ketadi (`zone-computers/` POST): 40 ta kompyuterni
 * ko'chirish 40 ta so'rov va 40 ta audit yozuvi bo'lmasligi kerak, xato
 * tanlovni esa saqlashdan oldin qaytarib olish mumkin.
 *
 * Talabgori bor, unda imtihon topshirilgan yoki hozir imtihon ketayotgan
 * joy QULFLANGAN (`lock`, server `bookings._seat_lock`) — uni sessiyadan
 * chiqarib bo'lmaydi; qoida serverda, bu yerda faqat ko'rsatiladi.
 */

type Side = 'pool' | 'session'
type Lock = '' | 'booked' | 'used' | 'in_exam'

/** `zone-computers/` qatori. */
interface PcRow {
  computer: number
  number: number | null
  label: string
  inventory_code: string
  decommissioned: boolean
  seat: Id | null
  seat_active: boolean | null
  lock: Lock
}

interface PendingSets {
  added: Set<number>
  removed: Set<number>
}

type Selection = Record<Side, Set<number>>

const EMPTY_ROWS: PcRow[] = []
const emptyPending = (): PendingSets => ({ added: new Set(), removed: new Set() })
const emptySelection = (): Selection => ({ pool: new Set(), session: new Set() })

const LOCK_HINT: Record<Exclude<Lock, ''>, string> = {
  booked: 'Talabgor biriktirilgan — sessiyadan olish uchun avval joyni bo‘shating',
  used: 'Bu joyda imtihon topshirilgan — tarix saqlanadi. Ishlatmaslik uchun xaritada «buzilgan» deb belgilang',
  in_exam: 'Kompyuterda imtihon ketmoqda',
}

/** Tile o'tkazilishi mumkinmi — qulflangan va hisobdan chiqarilgan o'tmaydi. */
const isMovable = (row: PcRow, side: Side, pending: PendingSets) =>
  side === 'session' ? !row.lock : (!row.decommissioned || pending.removed.has(row.computer))

const pcLabel = (row: PcRow) => (row.number != null ? String(row.number) : row.inventory_code || '—')

// --------------------------------------------------------------------------
// Dialog
// --------------------------------------------------------------------------
export interface SessionComputersDialogProps {
  schedule: Option
  regionOptions: Option[]
  zoneOptions: Option[]
  /** Xaritada ochiq turgan bino — oyna o'sha binodan boshlanadi. */
  initialZone?: Id | null
  onClose: () => void
}

export default function SessionComputersDialog({
  schedule, regionOptions, zoneOptions, initialZone, onClose,
}: SessionComputersDialogProps) {
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('md'))
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()

  // Bino sessiyasida bino QAT'IY: boshqa binoning kompyuteri bu sessiyaga
  // kira olmaydi (server `schedule_computers` ham rad etadi).
  const fixedZone: Id | null = schedule.zone ?? null

  // Viloyatlar — binolari bor bo'lganlari (viloyat xodimiga faqat o'ziniki).
  const regionChoices = useMemo(() => {
    const ids = new Set(zoneOptions.map((zone) => zone.region))
    return regionOptions.filter((region) => ids.has(region.value))
  }, [regionOptions, zoneOptions])

  const [regionId, setRegionId] = useState<Id | null>(null)
  const [zoneId, setZoneId] = useState<Id | null>(null)
  const [pending, setPending] = useState<PendingSets>(emptyPending)
  const [selection, setSelection] = useState<Selection>(emptySelection)
  const [drag, setDrag] = useState<{ from: Side; ids: number[] } | null>(null)
  const [confirmAction, setConfirmAction] = useState<(() => void) | null>(null)
  const [skipped, setSkipped] = useState<ApiRecord[]>([])

  // Boshlang'ich bino: sessiya binosi yoki xaritada ochiq turgani. Faqat
  // BIR MARTA — keyin operator tanlovi ustun.
  const initialized = useRef(false)
  useEffect(() => {
    // Viloyatlar ham kutiladi: aks holda yagona viloyat oldindan tanlanmasdi.
    if (initialized.current || ((!zoneOptions.length || !regionOptions.length) && !fixedZone)) return
    initialized.current = true
    const start = fixedZone ?? initialZone ?? null
    const option = zoneOptions.find((zone) => zone.value === start)
    if (fixedZone != null || option) {
      setZoneId(start)
      setRegionId(option?.region ?? null)
    } else if (regionChoices.length === 1) {
      setRegionId(regionChoices[0].value)
    }
  }, [zoneOptions, regionOptions, regionChoices, fixedZone, initialZone])

  const zoneChoices = useMemo((): Option[] => {
    if (fixedZone != null) {
      const label = schedule.zoneName || ''
      return [zoneOptions.find((zone) => zone.value === fixedZone) || { value: fixedZone, label, shortLabel: label }]
    }
    return regionId == null ? [] : zoneOptions.filter((zone) => zone.region === regionId)
  }, [zoneOptions, regionId, fixedZone, schedule.zoneName])

  const query = useQuery({
    queryKey: ['computer-bookings', 'zone-computers', schedule.value, zoneId],
    queryFn: () => bookingsApi.zoneComputers({ schedule: schedule.value, zone: zoneId }),
    enabled: zoneId != null,
  })
  const rows: PcRow[] = query.data?.results || EMPTY_ROWS
  const rowMap = useMemo(() => new Map(rows.map((row) => [row.computer, row])), [rows])

  const { pool, session } = useMemo(() => {
    const out: Record<Side, PcRow[]> = { pool: [], session: [] }
    for (const row of rows) {
      const inSession = pending.added.has(row.computer)
        || (row.seat != null && !pending.removed.has(row.computer))
      out[inSession ? 'session' : 'pool'].push(row)
    }
    return out
  }, [rows, pending])

  const dirty = pending.added.size + pending.removed.size > 0
  const resetLocal = () => {
    setPending(emptyPending())
    setSelection(emptySelection())
    setSkipped([])
  }
  // Saqlanmagan tanlov jimgina yo'qolmasin: bino almashishi va yopish
  // tasdiq so'raydi.
  const guard = (action: () => void) => (dirty ? setConfirmAction(() => action) : action())

  const changeRegion = (id: Id | null) => guard(() => {
    resetLocal()
    setRegionId(id)
    const zones = zoneOptions.filter((zone) => zone.region === id)
    setZoneId(zones.length === 1 ? zones[0].value : null)
  })
  const changeZone = (id: Id | null) => guard(() => {
    resetLocal()
    setZoneId(id)
  })
  const close = () => guard(onClose)

  /**
   * Kompyuterlarni narigi panelga o'tkazadi (LOKAL). Ortga qaytarilgan
   * kompyuter o'zgarish sifatida qolmaydi: qo'shilib, keyin olingan —
   * hech narsa qilinmagan.
   */
  const move = useCallback((ids: number[], to: Side) => {
    const moved = ids.filter((id) => {
      const row = rowMap.get(id)
      return row && (to === 'session' ? !row.decommissioned || pending.removed.has(id) : !row.lock)
    })
    if (!moved.length) return
    setPending((prev) => {
      const added = new Set(prev.added)
      const removed = new Set(prev.removed)
      for (const id of moved) {
        const row = rowMap.get(id) as PcRow
        if (to === 'session') {
          if (removed.has(id)) removed.delete(id)
          else if (row.seat == null) added.add(id)
        } else if (added.has(id)) {
          added.delete(id)
        } else if (row.seat != null) {
          removed.add(id)
        }
      }
      return { added, removed }
    })
    // O'tganlar narigi panelda TANLANGAN bo'lib turadi: qayerga
    // tushganini ko'rish va xato bo'lsa darhol qaytarish uchun.
    setSelection({ pool: to === 'pool' ? new Set(moved) : new Set(), session: to === 'session' ? new Set(moved) : new Set() })
  }, [rowMap, pending])

  const handleSelect = useCallback((side: Side, ids: Set<number>) => {
    // Bir vaqtda faqat bitta panelda tanlov: «→» va «←» qaysi to'plamni
    // o'tkazishi shunda bir ma'noli.
    setSelection(side === 'pool' ? { pool: ids, session: new Set() } : { pool: new Set(), session: ids })
  }, [])
  const handleDragStart = useCallback((from: Side, ids: number[]) => setDrag({ from, ids }), [])
  const handleDragEnd = useCallback(() => setDrag(null), [])
  // Joriy drag ref'da: o'tkazish state updater ichida bo'lsa StrictMode
  // uni ikki marta chaqirardi.
  const dragRef = useRef(drag)
  dragRef.current = drag
  const handleDrop = useCallback((to: Side) => {
    const current = dragRef.current
    setDrag(null)
    if (current && current.from !== to) move(current.ids, to)
  }, [move])

  const saveMutation = useMutation({
    mutationFn: () => bookingsApi.updateZoneComputers({
      schedule: schedule.value,
      zone: zoneId,
      add: [...pending.added],
      remove: [...pending.removed],
    }),
    retry: false,
    onSuccess: async (result: ApiRecord) => {
      // Avval shu binoning ro'yxati yangilanadi, keyin lokal o'zgarishlar
      // tozalanadi — aks holda tile'lar bir lahza eski joyiga sakrardi.
      await queryClient.invalidateQueries({
        queryKey: ['computer-bookings', 'zone-computers', schedule.value, zoneId],
      })
      queryClient.invalidateQueries({
        queryKey: ['computer-bookings'],
        predicate: (item) => item.queryKey[1] !== 'zone-computers',
      })
      setPending(emptyPending())
      setSelection(emptySelection())
      setSkipped(result.skipped || [])
      const parts = [
        result.added ? `${result.added} ta qo‘shildi` : '',
        result.removed ? `${result.removed} ta olindi` : '',
      ].filter(Boolean)
      notify(
        parts.length ? `Sessiya yangilandi: ${parts.join(', ')}` : 'Hech narsa o‘zgarmadi',
        result.skipped?.length ? 'warning' : 'success',
      )
    },
    onError: notifyError,
  })
  const saving = saveMutation.isPending

  const poolMovable = pool.filter((row) => isMovable(row, 'pool', pending)).map((row) => row.computer)
  const sessionMovable = session.filter((row) => !row.lock).map((row) => row.computer)
  const lockedCount = session.length - sessionMovable.length

  const transfer = (
    <TransferControls
      vertical={!mobile}
      disabled={zoneId == null || saving}
      toSession={selection.pool.size}
      toPool={selection.session.size}
      allToSession={poolMovable.length}
      allToPool={sessionMovable.length}
      onToSession={() => move([...selection.pool], 'session')}
      onToPool={() => move([...selection.session], 'pool')}
      onAllToSession={() => move(poolMovable, 'session')}
      onAllToPool={() => move(sessionMovable, 'pool')}
    />
  )

  const panelProps = {
    pending,
    loading: query.isLoading && zoneId != null,
    zoneChosen: zoneId != null,
    drag,
    onSelect: handleSelect,
    onDragStart: handleDragStart,
    onDragEnd: handleDragEnd,
    onDrop: handleDrop,
  }

  const freeSeating = schedule.bookingRequired === false

  return (
    <>
      <Dialog
        open
        onClose={saving ? undefined : close}
        fullScreen={mobile}
        maxWidth="xl"
        fullWidth
        PaperProps={{ sx: { height: { md: 'min(920px, calc(100% - 64px))' }, overflow: 'hidden' } }}
      >
        <Stack sx={{ height: '100%', minHeight: 0 }}>
          {/* Sarlavha */}
          <Stack direction="row" spacing={2} alignItems="center" sx={{ px: { xs: 2, sm: 3 }, pt: { xs: 2, sm: 2.5 }, pb: 1.5 }}>
            <Box
              sx={{
                width: 48, height: 48, borderRadius: '16px', display: 'grid', placeItems: 'center', flexShrink: 0,
                bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer',
              }}
            >
              <AttachIcon />
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h6" noWrap>Kompyuterlarni biriktirish</Typography>
              <Typography variant="body2" color="text.secondary" noWrap>{schedule.label}</Typography>
            </Box>
            <IconButton onClick={close} disabled={saving} aria-label="Yopish">
              <CloseIcon />
            </IconButton>
          </Stack>

          {/* Viloyat -> bino */}
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1.5}
            alignItems={{ sm: 'center' }}
            sx={{ px: { xs: 2, sm: 3 }, pt: 1, pb: 1.5 }}
          >
            <Autocomplete
              size="small"
              sx={{ width: { xs: '100%', sm: 260 } }}
              options={regionChoices}
              value={regionChoices.find((option) => option.value === regionId) || null}
              onChange={(_, option) => changeRegion(option ? option.value : null)}
              isOptionEqualToValue={(option, item) => option.value === item.value}
              getOptionLabel={(option) => option?.label || ''}
              disabled={fixedZone != null || saving}
              renderInput={(params) => <TextField {...params} label="Viloyat" />}
              noOptionsText="Viloyat topilmadi"
            />
            <Autocomplete
              size="small"
              sx={{ width: { xs: '100%', sm: 340 } }}
              options={zoneChoices}
              value={zoneChoices.find((option) => option.value === zoneId) || null}
              onChange={(_, option) => changeZone(option ? option.value : null)}
              isOptionEqualToValue={(option, item) => option.value === item.value}
              getOptionLabel={(option) => option?.shortLabel || option?.label || ''}
              disabled={fixedZone != null || (regionId == null && !zoneChoices.length) || saving}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Bino"
                  InputProps={{
                    ...params.InputProps,
                    startAdornment: (
                      <>
                        <InputAdornment position="start" sx={{ ml: 0.5 }}>
                          <ApartmentIcon fontSize="small" />
                        </InputAdornment>
                        {params.InputProps.startAdornment}
                      </>
                    ),
                  }}
                />
              )}
              noOptionsText="Bu viloyatda bino yo‘q"
            />
            <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ flex: 1, minWidth: 0, color: 'text.secondary' }}>
              <InfoIcon sx={{ fontSize: 18, mt: '1px' }} />
              <Typography variant="caption">
                {freeSeating
                  ? 'Erkin joylashuv: sessiyadagi har bir bo‘sh ishchi kompyuterda talabgor test topshira oladi.'
                  : 'Talabgorlar faqat sessiyadagi kompyuterlarga biriktiriladi.'}
              </Typography>
            </Stack>
          </Stack>

          {(skipped.length > 0 || query.data?.truncated) && (
            <Stack spacing={1} sx={{ px: { xs: 2, sm: 3 }, pb: 1.5 }}>
              {skipped.length > 0 && (
                <Alert severity="warning" onClose={() => setSkipped([])}>
                  <strong>{skipped.length} ta kompyuter o‘zgartirilmadi:</strong>
                  {skipped.slice(0, 4).map((item) => (
                    <Box key={item.computer} component="span" sx={{ display: 'block' }}>{item.message}</Box>
                  ))}
                  {skipped.length > 4 && <Box component="span" sx={{ display: 'block' }}>… yana {skipped.length - 4} ta</Box>}
                </Alert>
              )}
              {query.data?.truncated && (
                <Alert severity="warning">Binoda juda ko‘p kompyuter — birinchi 2000 tasi ko‘rsatilgan.</Alert>
              )}
            </Stack>
          )}

          {/* Ikki panel */}
          <Box
            sx={{
              flex: 1, minHeight: 0, px: { xs: 1.5, sm: 3 }, pb: 1.5,
              display: 'grid', gap: { xs: 1, md: 1.5 },
              gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'minmax(0, 1fr) auto minmax(0, 1fr)' },
              // Telefonda panellar ustma-ust va dialog o'zi suriladi: har panel
              // kamida ~3 qator o'rindiqni ko'rsatadi.
              gridTemplateRows: { xs: 'minmax(420px, auto) auto minmax(420px, auto)', md: 'minmax(0, 1fr)' },
              overflow: { xs: 'auto', md: 'hidden' },
            }}
          >
            <PcPanel
              side="pool"
              title="Binodagi kompyuterlar"
              caption="Ishchi, sessiyaga kiritilmagan"
              icon={<PcIcon />}
              rows={pool}
              selected={selection.pool}
              emptyTitle={zoneId == null ? 'Binoni tanlang' : 'Hammasi sessiyada'}
              emptyText={
                zoneId == null
                  ? 'Viloyat va binoni tanlang — shu binoning ishchi kompyuterlari shu yerda chiqadi.'
                  : 'Binoning barcha ishchi kompyuterlari shu test sessiyasiga kiritilgan.'
              }
              {...panelProps}
            />
            {transfer}
            <PcPanel
              side="session"
              title="Test sessiyasida"
              caption={lockedCount ? `${lockedCount} tasi band — o‘zgartirilmaydi` : 'Talabgor qabul qiladigan joylar'}
              icon={<SeatIcon />}
              rows={session}
              selected={selection.session}
              emptyTitle={zoneId == null ? 'Joylar shu yerda bo‘ladi' : 'Kompyuterlarni shu yerga torting'}
              emptyText={
                zoneId == null
                  ? 'Bino tanlangach, sessiyaga kiritilgan kompyuterlar o‘rindiq ko‘rinishida chiqadi.'
                  : 'Chapdan bir yoki bir nechtasini belgilab, shu yerga torting yoki «›» tugmasini bosing.'
              }
              {...panelProps}
            />
          </Box>

          {/* Pastki satr */}
          <Divider />
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1.5}
            alignItems={{ sm: 'center' }}
            sx={{ px: { xs: 2, sm: 3 }, py: 1.5 }}
          >
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ flex: 1, minWidth: 0 }}>
              {dirty ? (
                <>
                  {pending.added.size > 0 && (
                    <Chip size="small" color="success" variant="outlined" label={`+${pending.added.size} qo‘shiladi`} />
                  )}
                  {pending.removed.size > 0 && (
                    <Chip size="small" color="warning" variant="outlined" label={`−${pending.removed.size} olinadi`} />
                  )}
                  <Button size="small" color="inherit" startIcon={<UndoIcon />} disabled={saving} onClick={resetLocal}>
                    Qaytarish
                  </Button>
                </>
              ) : (
                <Typography variant="caption" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
                  Bosib belgilang (Shift — oraliq, sichqoncha bilan ramka chizish — bir nechtasi), keyin
                  narigi panelga torting.
                </Typography>
              )}
            </Stack>
            <Stack direction="row" spacing={1} justifyContent="flex-end">
              <Button onClick={close} disabled={saving}>Yopish</Button>
              <Button
                variant="contained"
                disabled={!dirty || saving}
                startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <CheckIcon />}
                onClick={() => saveMutation.mutate()}
              >
                Saqlash
              </Button>
            </Stack>
          </Stack>
        </Stack>
      </Dialog>

      <ConfirmDialog
        open={Boolean(confirmAction)}
        title="Saqlanmagan o‘zgarishlar"
        description="Tanlangan kompyuterlar hali saqlanmagan. Ular tashlab yuborilsinmi?"
        confirmLabel="Tashlab yuborish"
        color="warning"
        onConfirm={() => {
          const action = confirmAction
          setConfirmAction(null)
          action?.()
        }}
        onClose={() => setConfirmAction(null)}
      />
    </>
  )
}

// --------------------------------------------------------------------------
// O'tkazish tugmalari (MD3 tonal icon button'lar)
// --------------------------------------------------------------------------
interface TransferControlsProps {
  vertical: boolean
  disabled: boolean
  toSession: number
  toPool: number
  allToSession: number
  allToPool: number
  onToSession: () => void
  onToPool: () => void
  onAllToSession: () => void
  onAllToPool: () => void
}

function TransferControls({
  vertical, disabled, toSession, toPool, allToSession, allToPool,
  onToSession, onToPool, onAllToSession, onAllToPool,
}: TransferControlsProps) {
  // Telefonda panellar ustma-ust: strelkalar pastga/yuqoriga buriladi.
  const turn = vertical ? undefined : { transform: 'rotate(90deg)' }
  const buttons: { key: string; title: string; icon: ReactNode; count: number; strong?: boolean; onClick: () => void }[] = [
    { key: 'to', title: 'Tanlanganlarni sessiyaga qo‘shish', icon: <NextIcon sx={turn} />, count: toSession, strong: true, onClick: onToSession },
    { key: 'back', title: 'Tanlanganlarni sessiyadan olish', icon: <PrevIcon sx={turn} />, count: toPool, strong: true, onClick: onToPool },
    { key: 'all-to', title: 'Barchasini sessiyaga qo‘shish', icon: <AllNextIcon sx={turn} />, count: allToSession, onClick: onAllToSession },
    { key: 'all-back', title: 'Barchasini sessiyadan olish (band joylardan tashqari)', icon: <AllPrevIcon sx={turn} />, count: allToPool, onClick: onAllToPool },
  ]
  return (
    <Stack
      direction={vertical ? 'column' : 'row'}
      spacing={1}
      alignItems="center"
      justifyContent="center"
      sx={{ py: vertical ? 0 : 0.5 }}
    >
      {buttons.map((button, index) => (
        <Stack key={button.key} direction={vertical ? 'column' : 'row'} alignItems="center" spacing={1}>
          {index === 2 && <Divider flexItem orientation={vertical ? 'horizontal' : 'vertical'} sx={{ my: vertical ? 0.5 : 0, mx: vertical ? 0 : 0.5 }} />}
          <Tooltip title={button.count ? `${button.title} (${button.count})` : button.title} placement={vertical ? 'right' : 'top'}>
            <span>
              <IconButton
                aria-label={button.title}
                disabled={disabled || !button.count}
                onClick={button.onClick}
                sx={{
                  width: 44, height: 44, borderRadius: '14px',
                  bgcolor: button.strong && button.count ? 'primary.main' : 'm3.secondaryContainer',
                  color: button.strong && button.count ? 'primary.contrastText' : 'm3.onSecondaryContainer',
                  '&:hover': { bgcolor: button.strong && button.count ? 'primary.dark' : 'm3.surfaceContainerHighest' },
                  '&.Mui-disabled': { bgcolor: 'action.disabledBackground' },
                }}
              >
                {button.icon}
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      ))}
    </Stack>
  )
}

// --------------------------------------------------------------------------
// Panel — zal ko'rinishidagi kompyuterlar
// --------------------------------------------------------------------------
interface PcPanelProps {
  side: Side
  title: string
  caption: string
  icon: ReactNode
  rows: PcRow[]
  selected: Set<number>
  pending: PendingSets
  loading: boolean
  zoneChosen: boolean
  drag: { from: Side; ids: number[] } | null
  emptyTitle: string
  emptyText: string
  onSelect: (side: Side, ids: Set<number>) => void
  onDragStart: (side: Side, ids: number[]) => void
  onDragEnd: () => void
  onDrop: (side: Side) => void
}

interface LassoBox { x: number; y: number; w: number; h: number }

const TILE = { w: 58, h: 60, font: 16, icon: 15, aisle: 24 }
const GAP = 10

function PcPanel({
  side, title, caption, icon, rows, selected, pending, loading, zoneChosen, drag,
  emptyTitle, emptyText, onSelect, onDragStart, onDragEnd, onDrop,
}: PcPanelProps) {
  const theme = useTheme()
  const [search, setSearch] = useState('')
  const [over, setOver] = useState(false)
  const [lasso, setLasso] = useState<LassoBox | null>(null)
  const areaRef = useRef<HTMLDivElement | null>(null)
  const anchorRef = useRef<number | null>(null)
  const lassoRef = useRef<{ x: number; y: number; base: Set<number>; moved: boolean; additive: boolean } | null>(null)
  const frameRef = useRef(0)

  const needle = search.trim().toLowerCase()
  const visible = useMemo(
    () => (needle
      ? rows.filter((row) => `${row.number ?? ''} ${row.inventory_code} ${row.label}`.toLowerCase().includes(needle))
      : rows),
    [rows, needle],
  )

  // Ustunlar soni panelning haqiqiy kengligidan (`SeatGrid` bilan bir xil
  // qoida): juft son — yo'lak o'rtada.
  const [cols, setCols] = useState(4)
  useEffect(() => {
    const node = areaRef.current
    if (!node) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const fit = Math.floor((entry.contentRect.width - TILE.aisle + GAP) / (TILE.w + GAP))
      setCols(Math.max(2, Math.min(12, fit - (fit % 2))) || 2)
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  const half = cols / 2
  const tableRows = useMemo(() => {
    const out: PcRow[][] = []
    for (let i = 0; i < visible.length; i += cols) out.push(visible.slice(i, i + cols))
    return out
  }, [visible, cols])
  const styles = useMemo(() => tileStyles(theme), [theme])

  // Tile'larga BARQAROR funksiyalar (memo), joriy qiymatlar ref'da.
  const latest = useRef({ selected, visible, pending, onSelect, onDragStart })
  latest.current = { selected, visible, pending, onSelect, onDragStart }

  const handleClick = useCallback((row: PcRow, shift: boolean) => {
    const { selected: current, visible: list, pending: pend, onSelect: select } = latest.current
    const next = new Set(current)
    if (shift && anchorRef.current != null) {
      const a = list.findIndex((item) => item.computer === anchorRef.current)
      const b = list.findIndex((item) => item.computer === row.computer)
      if (a >= 0 && b >= 0) {
        for (const item of list.slice(Math.min(a, b), Math.max(a, b) + 1)) {
          if (isMovable(item, side, pend)) next.add(item.computer)
        }
        select(side, next)
        return
      }
    }
    if (!isMovable(row, side, pend)) return
    if (next.has(row.computer)) next.delete(row.computer)
    else next.add(row.computer)
    anchorRef.current = row.computer
    select(side, next)
  }, [side])

  const handleDragStart = useCallback((event: DragEvent<HTMLDivElement>, row: PcRow) => {
    const { selected: current, pending: pend, onSelect: select, onDragStart: start } = latest.current
    if (!isMovable(row, side, pend)) {
      event.preventDefault()
      return
    }
    // Tanlanmagan tile tortilsa — faqat o'zi (fayl menejeridagidek).
    const ids = current.has(row.computer) ? [...current] : [row.computer]
    if (!current.has(row.computer)) select(side, new Set(ids))
    event.dataTransfer.effectAllowed = 'move'
    // Firefox `setData` siz drag'ni boshlamaydi.
    event.dataTransfer.setData('text/plain', ids.join(','))
    setDragGhost(event, ids.length, theme)
    start(side, ids)
  }, [side, theme])

  // ---------------------------------------------------------------- lasso
  const toContent = (clientX: number, clientY: number) => {
    const area = areaRef.current as HTMLDivElement
    const rect = area.getBoundingClientRect()
    return { x: clientX - rect.left + area.scrollLeft, y: clientY - rect.top + area.scrollTop }
  }

  const hitTest = (box: LassoBox) => {
    const area = areaRef.current as HTMLDivElement
    const rect = area.getBoundingClientRect()
    const hits: number[] = []
    area.querySelectorAll<HTMLElement>('.pc[data-movable]').forEach((el) => {
      const r = el.getBoundingClientRect()
      const x = r.left - rect.left + area.scrollLeft
      const y = r.top - rect.top + area.scrollTop
      if (x < box.x + box.w && x + r.width > box.x && y < box.y + box.h && y + r.height > box.y) {
        hits.push(Number(el.dataset.id))
      }
    })
    return hits
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    // Faqat sichqoncha: barmoq bilan bu harakat — skroll.
    if (event.pointerType !== 'mouse' || event.button !== 0 || !rows.length) return
    if ((event.target as Element).closest('.pc, input, button')) return
    const additive = event.shiftKey || event.ctrlKey || event.metaKey
    lassoRef.current = {
      ...toContent(event.clientX, event.clientY),
      base: additive ? new Set(selected) : new Set(),
      moved: false,
      additive,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const state = lassoRef.current
    if (!state) return
    const point = toContent(event.clientX, event.clientY)
    if (!state.moved && Math.hypot(point.x - state.x, point.y - state.y) < 5) return
    state.moved = true
    const box = {
      x: Math.min(state.x, point.x), y: Math.min(state.y, point.y),
      w: Math.abs(point.x - state.x), h: Math.abs(point.y - state.y),
    }
    setLasso(box)
    // 500 tile'ning o'lchami har harakatda emas — kadrda bir marta.
    cancelAnimationFrame(frameRef.current)
    frameRef.current = requestAnimationFrame(() => {
      const next = new Set(state.base)
      for (const id of hitTest(box)) next.add(id)
      latest.current.onSelect(side, next)
    })
  }

  const endLasso = (event: ReactPointerEvent<HTMLDivElement>) => {
    const state = lassoRef.current
    if (!state) return
    lassoRef.current = null
    setLasso(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    // Bo'sh joyni bosish — tanlovni tozalaydi.
    if (!state.moved && !state.additive && selected.size) onSelect(side, new Set())
  }
  useEffect(() => () => cancelAnimationFrame(frameRef.current), [])

  // ------------------------------------------------------------ klaviatura
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.target as Element).closest('input')) return
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
      event.preventDefault()
      onSelect(side, new Set(visible.filter((row) => isMovable(row, side, pending)).map((row) => row.computer)))
    } else if (event.key === 'Escape' && selected.size) {
      // Dialog yopilmasin — avval tanlov tozalanadi.
      event.stopPropagation()
      onSelect(side, new Set())
    }
  }

  // ------------------------------------------------------------- drop zona
  const target = drag != null && drag.from !== side
  const dragging = drag?.from === side
  const selectAll = () => onSelect(
    side, new Set(visible.filter((row) => isMovable(row, side, pending)).map((row) => row.computer)),
  )

  const renderTile = (row: PcRow | null, index: number) => {
    if (!row) return <span key={`gap-${index}`} className="pc-gap" />
    const pend = side === 'session'
      ? (pending.added.has(row.computer) ? 'add' : null)
      : (pending.removed.has(row.computer) ? 'remove' : null)
    return (
      <PcTile
        key={row.computer}
        row={row}
        side={side}
        selected={selected.has(row.computer)}
        pending={pend}
        movable={isMovable(row, side, pending)}
        onTileClick={handleClick}
        onTileDragStart={handleDragStart}
        onTileDragEnd={onDragEnd}
      />
    )
  }

  return (
    <Box
      onDragOver={(event) => {
        if (!target) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
        if (!over) setOver(true)
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false)
      }}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        if (target) onDrop(side)
      }}
      onKeyDown={onKeyDown}
      sx={(t: Theme) => ({
        position: 'relative', minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column',
        borderRadius: '20px', bgcolor: 'm3.surfaceContainerLow',
        outline: `2px ${over ? 'solid' : 'dashed'} ${target ? t.palette.primary.main : 'transparent'}`,
        outlineOffset: -2,
        backgroundImage: target ? `linear-gradient(${alpha(t.palette.primary.main, over ? 0.12 : 0.05)}, ${alpha(t.palette.primary.main, over ? 0.12 : 0.05)})` : 'none',
        transition: t.transitions.create(['outline-color', 'background-image'], { duration: t.motion.fast }),
      })}
    >
      {/* Panel sarlavhasi */}
      <Stack spacing={1.25} sx={{ p: 1.75, pb: 1 }}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box
            sx={{
              width: 40, height: 40, borderRadius: '12px', display: 'grid', placeItems: 'center', flexShrink: 0,
              bgcolor: side === 'session' ? 'm3.primaryContainer' : 'm3.secondaryContainer',
              color: side === 'session' ? 'm3.onPrimaryContainer' : 'm3.onSecondaryContainer',
            }}
          >
            {icon}
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" fontWeight={700} noWrap>{title}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">{caption}</Typography>
          </Box>
          <Chip
            label={rows.length}
            sx={{ fontWeight: 800, fontVariantNumeric: 'tabular-nums', bgcolor: 'm3.surfaceContainerHighest' }}
          />
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            size="small"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Raqam yoki inventar kodi"
            disabled={!rows.length}
            sx={{ flex: 1, minWidth: 0, '& .MuiOutlinedInput-root': { borderRadius: 999, bgcolor: 'background.paper' } }}
            InputProps={{
              startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
              endAdornment: search ? (
                <InputAdornment position="end">
                  <IconButton size="small" aria-label="Tozalash" onClick={() => setSearch('')}>
                    <CloseIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : null,
            }}
          />
          {selected.size > 0 ? (
            <Chip
              color="primary"
              label={`${selected.size} ta tanlandi`}
              onDelete={() => onSelect(side, new Set())}
              sx={{ fontWeight: 700, flexShrink: 0 }}
            />
          ) : (
            <Tooltip title="Hammasini tanlash (Ctrl+A)">
              <span>
                <IconButton aria-label="Hammasini tanlash" disabled={!visible.length} onClick={selectAll}>
                  <SelectAllIcon />
                </IconButton>
              </span>
            </Tooltip>
          )}
        </Stack>
      </Stack>

      {/* Zal */}
      <Box
        ref={areaRef}
        data-dragging={dragging || undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endLasso}
        onPointerCancel={endLasso}
        sx={{
          position: 'relative', flex: 1, minHeight: 0, overflow: 'auto', px: 1.75, pb: 2,
          userSelect: 'none', ...styles,
        }}
      >
        <HoverTip containerRef={areaRef} selector=".pc" />
        {loading ? (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: `${GAP}px`, justifyContent: 'center', pt: 1 }}>
            {Array.from({ length: 18 }).map((_, index) => (
              <Box key={index} sx={{ width: TILE.w, height: TILE.h, borderRadius: '12px', bgcolor: 'action.hover' }} />
            ))}
          </Box>
        ) : !visible.length ? (
          <PanelEmpty
            side={side}
            target={target}
            title={needle ? `«${search.trim()}» topilmadi` : emptyTitle}
            text={needle ? 'Qidiruvni o‘zgartiring yoki tozalang.' : emptyText}
            muted={!zoneChosen}
          />
        ) : (
          <Stack spacing={1.5} alignItems="center" sx={{ minWidth: 'fit-content', mx: 'auto', pt: 0.5 }}>
            {/* Zalning OLDI — asosiy xaritadagi bilan bir xil yo'nalish belgisi. */}
            <Stack
              direction="row" spacing={1} alignItems="center" justifyContent="center"
              sx={{
                width: '100%', py: 0.5, borderRadius: 999, color: 'text.secondary',
                bgcolor: 'm3.surfaceContainerHigh', border: 1, borderColor: 'divider', borderStyle: 'dashed',
              }}
            >
              <ScreenIcon sx={{ fontSize: 16 }} />
              <Typography variant="caption" fontWeight={650} letterSpacing="0.04em">OLDI · PROKTOR STOLI</Typography>
            </Stack>
            {tableRows.map((row, rowIndex) => {
              const padded: (PcRow | null)[] = row.length < cols ? [...row, ...Array(cols - row.length).fill(null)] : row
              return (
                <div key={rowIndex} className="pc-row">
                  {padded.slice(0, half).map((item, index) => renderTile(item, index))}
                  <span className="pc-aisle">{rowIndex + 1}</span>
                  {padded.slice(half).map((item, index) => renderTile(item, half + index))}
                </div>
              )
            })}
          </Stack>
        )}
        {lasso && (
          <Box
            sx={(t: Theme) => ({
              position: 'absolute', left: lasso.x, top: lasso.y, width: lasso.w, height: lasso.h,
              border: `1.5px solid ${t.palette.primary.main}`, borderRadius: '6px',
              bgcolor: alpha(t.palette.primary.main, 0.12), pointerEvents: 'none', zIndex: 2,
            })}
          />
        )}
      </Box>

      {/* Tortib kelinayotganda — nima bo'lishini aytadigan yorliq */}
      {target && (
        <Box
          sx={{
            position: 'absolute', left: '50%', bottom: 16, transform: 'translateX(-50%)', zIndex: 3,
            pointerEvents: 'none', px: 2, py: 1, borderRadius: 999, boxShadow: 3, whiteSpace: 'nowrap',
            bgcolor: over ? 'primary.main' : 'm3.surfaceContainerHighest',
            color: over ? 'primary.contrastText' : 'text.primary',
            typography: 'body2', fontWeight: 650,
          }}
        >
          {drag?.ids.length} ta kompyuter {side === 'session' ? 'sessiyaga qo‘shiladi' : 'sessiyadan olinadi'}
        </Box>
      )}
    </Box>
  )
}

function PanelEmpty({
  side, target, title, text, muted,
}: { side: Side; target: boolean; title: string; text: string; muted: boolean }) {
  const drop = side === 'session' && !muted
  return (
    <Stack
      spacing={1.25}
      alignItems="center"
      justifyContent="center"
      sx={{
        height: '100%', minHeight: 220, textAlign: 'center', px: 3, py: 4,
        ...(drop && {
          border: 2, borderStyle: 'dashed', borderRadius: '16px', mt: 0.5,
          borderColor: target ? 'primary.main' : 'm3.outlineVariant',
        }),
      }}
    >
      <Box
        sx={{
          width: 64, height: 64, borderRadius: '20px', display: 'grid', placeItems: 'center',
          bgcolor: muted ? 'm3.surfaceContainerHighest' : 'm3.primaryContainer',
          color: muted ? 'text.secondary' : 'm3.onPrimaryContainer',
        }}
      >
        {drop ? <DropIcon sx={{ fontSize: 30 }} /> : side === 'session' ? <SeatIcon sx={{ fontSize: 30 }} /> : <PcIcon sx={{ fontSize: 30 }} />}
      </Box>
      <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 320 }}>{text}</Typography>
    </Stack>
  )
}

// --------------------------------------------------------------------------
// Tile — o'rindiq shakli (asosiy xarita `SeatMap.seatStyles` bilan bir xil)
// --------------------------------------------------------------------------
type TileState = 'outside' | 'retired' | 'seat' | 'booked' | 'broken'

const tileState = (row: PcRow, side: Side): TileState => {
  if (row.decommissioned) return 'retired'
  if (side === 'pool') return 'outside'
  if (row.seat_active === false) return 'broken'
  if (row.lock === 'booked' || row.lock === 'in_exam') return 'booked'
  return 'seat'
}

const TILE_ICON: Partial<Record<Lock, typeof PersonIcon>> = {
  booked: PersonIcon, in_exam: PersonIcon, used: HistoryIcon,
}

const tileHint = (row: PcRow, side: Side, pending: 'add' | 'remove' | null) => [
  row.label,
  row.decommissioned && 'Hisobdan chiqarilgan',
  side === 'session' && row.seat_active === false && 'Sessiyada buzilgan deb belgilangan',
  row.lock && LOCK_HINT[row.lock],
  pending === 'add' && 'Saqlanganda sessiyaga qo‘shiladi',
  pending === 'remove' && 'Saqlanganda sessiyadan olinadi',
].filter(Boolean).join(' · ')

interface PcTileProps {
  row: PcRow
  side: Side
  selected: boolean
  pending: 'add' | 'remove' | null
  movable: boolean
  onTileClick: (row: PcRow, shift: boolean) => void
  onTileDragStart: (event: DragEvent<HTMLDivElement>, row: PcRow) => void
  onTileDragEnd: () => void
}

/**
 * `<div role="button">`, `<button>` EMAS: Firefox `draggable` tugmani
 * tortmaydi. Klaviatura uchun Enter/Space qo'lda ulangan.
 */
const PcTile = memo(function PcTile({
  row, side, selected, pending, movable, onTileClick, onTileDragStart, onTileDragEnd,
}: PcTileProps) {
  const state = tileState(row, side)
  const Icon = side === 'session' ? (row.seat_active === false ? BuildIcon : TILE_ICON[row.lock]) : undefined
  return (
    <div
      role="button"
      tabIndex={0}
      className="pc"
      data-id={row.computer}
      data-state={state}
      data-selected={selected || undefined}
      data-pending={pending || undefined}
      data-movable={movable || undefined}
      draggable={movable}
      aria-pressed={selected}
      aria-disabled={!movable || undefined}
      aria-label={tileHint(row, side, pending)}
      onClick={(event: MouseEvent<HTMLDivElement>) => onTileClick(row, event.shiftKey)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onTileClick(row, event.shiftKey)
        }
      }}
      onDragStart={(event) => onTileDragStart(event, row)}
      onDragEnd={onTileDragEnd}
    >
      <span className="pc-shape" />
      <span className="pc-body">
        <span className="pc-num">{pcLabel(row)}</span>
        {Icon && <Icon className="pc-icon" fontSize="inherit" />}
      </span>
      {selected && <span className="pc-check"><CheckIcon fontSize="inherit" /></span>}
      {pending && <span className="pc-pending" data-kind={pending}>{pending === 'add' ? '+' : '−'}</span>}
      {!movable && !row.decommissioned && <span className="pc-lock"><LockIcon fontSize="inherit" /></span>}
    </div>
  )
})

/** Ikkala panelning barcha tile'lari uchun BITTA stil bloki (`seatStyles` naqshi). */
function tileStyles(theme: Theme): SystemStyleObject<Theme> {
  const { m3 } = theme.palette
  const primary = theme.palette.primary.main
  const error = theme.palette.error.main
  const paper = theme.palette.background.paper
  const badge = {
    position: 'absolute', top: 0, width: 20, height: 20, borderRadius: '50%', display: 'grid',
    placeItems: 'center', fontSize: 14, fontWeight: 800, lineHeight: 1, border: `2px solid ${paper}`,
  }
  return {
    '@keyframes pcIn': {
      from: { transform: 'scale(0.82)', opacity: 0 },
      to: { transform: 'scale(1)', opacity: 1 },
    },
    '& .pc-row': { display: 'flex', alignItems: 'center', gap: `${GAP}px` },
    '& .pc-gap': { width: TILE.w, flexShrink: 0 },
    '& .pc-aisle': {
      ...theme.typography.caption, width: TILE.aisle, textAlign: 'center', flexShrink: 0,
      color: theme.palette.text.disabled, fontWeight: 700,
    },
    '& .pc': {
      position: 'relative', display: 'block', flexShrink: 0, width: TILE.w, height: TILE.h,
      borderRadius: '12px', cursor: 'grab', outline: 0, WebkitTapHighlightColor: 'transparent',
    },
    '& .pc:not([data-movable])': { cursor: 'default' },
    // Panelga yangi tushgan (saqlanmagan) tile — yumshoq paydo bo'ladi.
    '& .pc[data-pending]': { animation: `pcIn ${theme.motion.base}ms ${theme.motion.easing}` },
    '& .pc-shape': {
      position: 'absolute', inset: '7px 0 0 0', borderRadius: '9px 9px 14px 14px',
      border: '2px solid', bgcolor: m3.surfaceContainerLowest, borderColor: m3.outline,
      transition: theme.transitions.create(['box-shadow', 'transform', 'background-color', 'opacity'], { duration: 140 }),
      '&::before': {
        content: '""', position: 'absolute', left: '14%', right: '14%', top: -8, height: 5,
        borderRadius: 999, bgcolor: m3.outlineVariant,
      },
    },
    // Sessiyadan TASHQARIDA — hali "o'rindiq" emas: uzuq kontur, fonsiz.
    '& .pc[data-state="outside"] .pc-shape, & .pc[data-state="retired"] .pc-shape': {
      borderStyle: 'dashed', bgcolor: 'transparent',
    },
    '& .pc[data-state="retired"]': { opacity: 0.55 },
    '& .pc[data-state="retired"] .pc-num': { textDecoration: 'line-through' },
    '& .pc[data-state="booked"] .pc-shape': {
      bgcolor: m3.primaryContainer, borderColor: primary, '&::before': { bgcolor: primary },
    },
    '& .pc[data-state="broken"] .pc-shape': {
      bgcolor: alpha(error, theme.palette.mode === 'light' ? 0.07 : 0.16),
      borderColor: error, borderStyle: 'dashed',
      backgroundImage: `repeating-linear-gradient(135deg, transparent 0 6px, ${alpha(error, 0.12)} 6px 8px)`,
      '&::before': { bgcolor: alpha(error, 0.55) },
    },
    '& .pc[data-movable]:hover .pc-shape': { transform: 'translateY(-2px)' },
    '& .pc:focus-visible .pc-shape': { boxShadow: `0 0 0 3px ${paper}, 0 0 0 5px ${alpha(primary, 0.5)}` },
    '& .pc[data-selected] .pc-shape': {
      bgcolor: alpha(primary, 0.16), borderColor: primary, borderStyle: 'solid',
      boxShadow: `0 0 0 3px ${paper}, 0 0 0 5px ${primary}`,
      '&::before': { bgcolor: primary },
    },
    '&[data-dragging] .pc[data-selected]': { opacity: 0.35 },
    '& .pc-body': {
      position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px', pt: '18px',
    },
    '& .pc-num': {
      fontFamily: theme.typography.fontFamily, fontSize: TILE.font, fontWeight: 800, lineHeight: 1,
      letterSpacing: '-0.02em', color: theme.palette.text.primary,
      maxWidth: TILE.w - 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .pc[data-state="outside"] .pc-num': { color: theme.palette.text.secondary },
    '& .pc[data-state="booked"] .pc-num': { color: m3.onPrimaryContainer },
    '& .pc[data-state="broken"] .pc-num': { color: error },
    '& .pc[data-selected] .pc-num': { color: primary },
    '& .pc-icon': { fontSize: TILE.icon, color: theme.palette.text.secondary },
    '& .pc[data-state="booked"] .pc-icon': { color: primary },
    '& .pc[data-state="broken"] .pc-icon': { color: error },
    '& .pc-check': { ...badge, left: -5, bgcolor: primary, color: theme.palette.primary.contrastText },
    '& .pc-pending': { ...badge, right: -5 },
    '& .pc-pending[data-kind="add"]': { bgcolor: theme.palette.success.main, color: theme.palette.success.contrastText },
    '& .pc-pending[data-kind="remove"]': { bgcolor: theme.palette.warning.main, color: theme.palette.warning.contrastText },
    '& .pc-lock': {
      ...badge, top: 'auto', bottom: -3, right: -5, width: 18, height: 18, fontSize: 11,
      bgcolor: m3.surfaceContainerHighest, color: theme.palette.text.secondary,
    },
  }
}

/**
 * Tortilayotgan narsa — "N ta kompyuter" yorlig'i (bir nechta bo'lsa
 * ustma-ust varaqlar). Brauzer standarti faqat bitta tile rasmini
 * ko'rsatardi va 30 tasi ham tortilayotgani ko'rinmasdi.
 */
function setDragGhost(event: DragEvent<HTMLDivElement>, count: number, theme: Theme) {
  const primary = theme.palette.primary.main
  const ghost = document.createElement('div')
  ghost.textContent = `${count} ta kompyuter`
  Object.assign(ghost.style, {
    position: 'fixed', top: '-200px', left: '-200px', padding: '8px 14px', borderRadius: '12px',
    background: primary, color: theme.palette.primary.contrastText, whiteSpace: 'nowrap',
    font: `650 13px ${theme.typography.fontFamily}`,
    boxShadow: count > 1
      ? `5px 5px 0 -1px ${alpha(primary, 0.55)}, 10px 10px 0 -2px ${alpha(primary, 0.3)}`
      : `0 4px 12px ${alpha('#000', 0.2)}`,
  })
  document.body.appendChild(ghost)
  event.dataTransfer.setDragImage(ghost, 18, 18)
  window.setTimeout(() => ghost.remove(), 0)
}
