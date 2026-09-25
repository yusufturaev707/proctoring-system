import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Autocomplete, Box, Button, Card, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, InputAdornment, LinearProgress, Paper, Stack, TextField, ToggleButton, ToggleButtonGroup,
  Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import SeatIcon from '@mui/icons-material/EventSeatOutlined'
import AssignIcon from '@mui/icons-material/PersonAddAltOutlined'
import ReleaseIcon from '@mui/icons-material/PersonRemoveOutlined'
import MoveIcon from '@mui/icons-material/SwapHorizOutlined'
import GenerateIcon from '@mui/icons-material/GridViewOutlined'
import AutoIcon from '@mui/icons-material/AutoAwesomeOutlined'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'
import MapIcon from '@mui/icons-material/GridOnRounded'
import ListIcon from '@mui/icons-material/ViewListRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import CloseIcon from '@mui/icons-material/CloseRounded'

import PageHeader from '../components/PageHeader'
import ResourcePage from '../components/data/ResourcePage'
import ConfirmDialog from '../components/ConfirmDialog'
import { StatusChip } from '../components/StatusChip'
import { useOptions } from '../components/data/useResource'
import { regionZoneFilters, useRegionOptions, useScheduleOptions, useZoneOptions } from './crud/shared'
import { computerBookings as bookingsApi } from '../api/endpoints'
import { useUi } from '../context/UiContext'
import { useAuth } from '../context/AuthContext'
import { fromNow } from '../utils/labels'
import {
  IN_EXAM_HINT, Legend, SeatGrid, SeatPanel, ZoneRail, seatInExam, seatState,
} from '../components/bookings/SeatMap'
import { EmptyState } from '../components/feedback/States'

const PINFL_RE = /^\d{14}$/

/**
 * Kompyuter bronlari.
 *
 * Bitta sahifa — bitta TEST SESSIYASI (imtihon jadvalidagi seans). Joylar
 * sessiya doirasidagi kompyuterlardan YIG'ILADI («Joylarni yaratish»):
 * bino jadvalida — o'sha bino, umumiy jadvalda — barcha viloyatlarning
 * barcha binolari (viloyat administratori uchun — o'z viloyati).
 *
 * Qator ikki MUSTAQIL holatga ega va ular ataylab ikki ustunda:
 *   «Ishchi»  — kompyuter shu sessiyada ishlaydimi (buzilgan bo'lsa o'chiriladi);
 *   «Talabgor» — joy kimga biriktirilgan.
 * «Buzilgan, lekin band» holati eng muhimi: o'sha talabgor imtihon kuni
 * `seat_out_of_service` bilan qaytariladi, shuning uchun ular alohida
 * ogohlantirishda sanaladi va bir bosishda ko'rsatiladi.
 */
export default function ComputerBookings() {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { can } = useAuth()
  const canManage = can('bookings.manage')
  const [searchParams, setSearchParams] = useSearchParams()
  // XARITA — standart: bron savoli fazoviy ("qaysi stol bo'sh?").
  // Jadval ham qoladi: eksport, JSHSHIR bo'yicha qidiruv va tashqi
  // tizimdan kelgan bronlarni tekshirish unda qulayroq.
  const view = searchParams.get('view') === 'list' ? 'list' : 'map'
  const setView = (next) =>
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev)
      if (next === 'map') params.delete('view')
      else params.set('view', next)
      return params
    }, { replace: true })

  const { options: scheduleOptions, isLoading: schedulesLoading } = useScheduleOptions()
  const { options: zoneOptions } = useZoneOptions()
  const { options: regionOptions } = useRegionOptions()

  const [scheduleId, setScheduleId] = useState(() => Number(searchParams.get('schedule')) || null)
  const [scope, setScope] = useState('all')
  const [assigning, setAssigning] = useState(null) // { seat?, move? }
  const [releasing, setReleasing] = useState(null)

  // Sessiya tanlanmagan bo'lsa — ENG MOS seans: hozir ochiq, bo'lmasa
  // eng yaqin kelgusi, bo'lmasa eng oxirgisi. Operator sahifani odatda
  // imtihon kuni ochadi va ro'yxatdan qidirib o'tirmasligi kerak.
  useEffect(() => {
    if (scheduleId || !scheduleOptions.length) return
    const now = Date.now()
    const open = scheduleOptions.find((option) => option.isOpen)
    const upcoming = [...scheduleOptions]
      .filter((option) => new Date(option.endsAt).getTime() > now)
      .sort((a, b) => new Date(a.startsAt) - new Date(b.startsAt))[0]
    setScheduleId((open || upcoming || scheduleOptions[0]).value)
  }, [scheduleId, scheduleOptions])

  const schedule = scheduleOptions.find((option) => option.value === scheduleId) || null

  const { data: stats } = useQuery({
    queryKey: ['computer-bookings', 'stats', scheduleId],
    queryFn: () => bookingsApi.stats({ schedule: scheduleId }),
    enabled: Boolean(scheduleId),
    refetchInterval: 30000,
  })

  // Prefiks: ro'yxat, sonlar va bo'sh joylar ro'yxati birga yangilanadi.
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['computer-bookings'] })

  const generateMutation = useMutation({
    mutationFn: () => bookingsApi.generate({ schedule: scheduleId }),
    retry: false,
    onSuccess: (result) => {
      notify(
        result.created
          ? `${result.created} ta yangi joy yaratildi (jami ${result.total} ta kompyuter)`
          : `Yangi kompyuter yo‘q — ${result.total} ta joy allaqachon bor`,
      )
      invalidate()
    },
    onError: notifyError,
  })

  const assignMutation = useMutation({
    mutationFn: (payload) => bookingsApi.assign({ schedule: scheduleId, ...payload }),
    retry: false,
    onSuccess: (row) => {
      const where = `${row.computer_label} · ${row.zone_name}`
      notify(row.moved_from ? `Talabgor ko‘chirildi → ${where}` : `Biriktirildi → ${where}`)
      setAssigning(null)
      invalidate()
    },
    onError: notifyError,
  })

  // Xaritadagi "Ishchi holatda" kaliti — jadvaldagi optimistik
  // toggle bilan bir xil PATCH (`is_active` — yagona yoziladigan maydon).
  const activeMutation = useMutation({
    mutationFn: ({ id, isActive }) => bookingsApi.update({ id, is_active: isActive }),
    retry: false,
    onSuccess: (row) => {
      notify(row.is_active ? 'Kompyuter ishchi holatga qaytarildi' : 'Kompyuter buzilgan deb belgilandi')
      invalidate()
    },
    onError: notifyError,
  })

  const releaseMutation = useMutation({
    mutationFn: (id) => bookingsApi.release(id),
    retry: false,
    onSuccess: () => {
      notify('Joy bo‘shatildi')
      setReleasing(null)
      invalidate()
    },
    onError: notifyError,
  })

  const scopeParams = {
    all: {},
    booked: { is_booked: true },
    free: { is_booked: false, is_active: true },
    broken: { is_active: false },
  }[scope]

  const columns = useMemo(
    () => [
      {
        // "Raqam", "№" EMAS: jadvalning o'z tartib ustuni allaqachon "№".
        field: 'computer_number', headerName: 'Raqam', width: 90,
        description: 'Xonadagi tartib raqami — stolga yozilgan',
        renderCell: (params) => <SeatNumber value={params.value} broken={!params.row.is_active} />,
      },
      { field: 'inventory_code', headerName: 'Inventar kodi', width: 140, sortable: false },
      { field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 150, sortable: false },
      { field: 'region_name', headerName: 'Viloyat', width: 160, sortable: false },
      {
        field: 'pinfl', headerName: 'Talabgor (JSHSHIR)', width: 190, sortable: false,
        exportValue: (value) => value || '',
        renderCell: (params) => (
          <Cell>
            {params.value ? (
              <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
                {params.value}
              </Typography>
            ) : (
              <Chip size="small" variant="outlined" label="Bo‘sh" />
            )}
          </Cell>
        ),
      },
      {
        // "Talabgor KELDIMI?" — FaceID'dan o'tgach sessiya paydo bo'ladi.
        field: 'session_status', headerName: 'Sessiya', width: 150, sortable: false,
        description: 'Talabgor FaceID’dan o‘tib sessiya ochganmi',
        renderCell: (params) => (
          <Cell>
            {params.value
              ? <StatusChip status={params.value} />
              : params.row.is_booked
                ? <Typography variant="body2" color="text.disabled">Hali kelmagan</Typography>
                : null}
          </Cell>
        ),
      },
      {
        field: 'booked_at', headerName: 'Biriktirilgan', width: 170,
        renderCell: (params) => (
          <Cell>
            {params.value ? (
              <Tooltip title={params.row.booked_by_name ? `Kim: ${params.row.booked_by_name}` : ''}>
                <Typography variant="body2">{fromNow(params.value)}</Typography>
              </Tooltip>
            ) : <Typography variant="body2" color="text.disabled">—</Typography>}
          </Cell>
        ),
      },
    ],
    [],
  )

  const headerActions = (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={view}
        onChange={(_, value) => value && setView(value)}
        aria-label="Ko‘rinish"
        // Ikki segment — surilmaydi, qator o'raladi (temadagi `minWidth: 0`
        // uzun guruhlar uchun; bu yerda u «Ro'yxat» ni kesib qo'yardi).
        sx={{ flexShrink: 0, minWidth: 'auto' }}
      >
        <ToggleButton value="map"><MapIcon fontSize="small" sx={{ mr: 0.75 }} />Xarita</ToggleButton>
        <ToggleButton value="list"><ListIcon fontSize="small" sx={{ mr: 0.75 }} />Ro‘yxat</ToggleButton>
      </ToggleButtonGroup>
      {canManage && (
        <>
          <Tooltip title="Sessiya doirasidagi har bir kompyuter uchun joy qo‘shadi. Takroriy bosish xavfsiz — mavjud bronlarga tegilmaydi.">
            <span>
              <Button
                variant="outlined"
                startIcon={<GenerateIcon />}
                disabled={!scheduleId || generateMutation.isPending}
                onClick={() => generateMutation.mutate()}
              >
                Joylarni yaratish
              </Button>
            </span>
          </Tooltip>
          <Button
            variant="contained"
            startIcon={<AssignIcon />}
            disabled={!scheduleId}
            onClick={() => setAssigning({})}
          >
            Biriktirish
          </Button>
        </>
      )}
    </Stack>
  )

  const dialogs = (
    <>
      {assigning && schedule && (
        <AssignDialog
          schedule={schedule}
          seat={assigning.seat}
          move={assigning.move}
          zoneOptions={zoneOptions}
          loading={assignMutation.isPending}
          onSave={(payload) => assignMutation.mutate(payload)}
          onClose={() => setAssigning(null)}
        />
      )}

      <ConfirmDialog
        open={Boolean(releasing)}
        title="Joyni bo‘shatish"
        description="Talabgor bu kompyuterdan olib tashlanadi. U boshqa joyga biriktirilmaguncha JSHSHIR tekshiruvida «hech qaysi kompyuterga biriktirilmagan» deb qaytariladi."
        details={
          releasing ? (
            <Stack spacing={0.5}>
              <Detail label="Kompyuter" value={`${releasing.computer_label} · ${releasing.zone_name}`} />
              <Detail label="JSHSHIR" value={releasing.pinfl} mono />
            </Stack>
          ) : null
        }
        confirmLabel="Bo‘shatish"
        color="error"
        loading={releaseMutation.isPending}
        onConfirm={() => releaseMutation.mutate(releasing.id)}
        onClose={() => setReleasing(null)}
      />
    </>
  )

  // Seans tanlanmaguncha jadval SO'RALMAYDI: `schedule` filtrisiz ro'yxat
  // barcha sessiyalarning joylarini aralashtirib yuborardi va sonlar
  // (band/bo'sh) hech qaysi seansga tegishli bo'lmasdi.
  if (!scheduleId) {
    return (
      <>
        <PageHeader title="Kompyuter bronlari" subtitle="Test sessiyasi bo‘yicha ish o‘rinlari" />
        {schedulesLoading ? (
          <LinearProgress sx={{ borderRadius: 2 }} />
        ) : (
          <Paper variant="outlined" sx={{ p: 5, borderRadius: '16px', textAlign: 'center' }}>
            <SeatIcon color="disabled" sx={{ fontSize: 48 }} />
            <Typography variant="h6" sx={{ mt: 1 }}>Imtihon jadvalida seans yo‘q</Typography>
            <Typography variant="body2" color="text.secondary">
              Bron test sessiyasiga bog‘lanadi — avval «Jadval» sahifasida seans yarating.
            </Typography>
          </Paper>
        )}
      </>
    )
  }

  const brokenAlert = stats?.broken_booked > 0 && (
    <Alert
      severity="error"
      icon={<WarningIcon />}
      action={
        view === 'list' ? (
          <Button color="inherit" size="small" onClick={() => setScope('broken')}>
            Ko‘rsatish
          </Button>
        ) : null
      }
    >
      <strong>{stats.broken_booked} ta talabgor</strong> buzilgan kompyuterga biriktirilgan —
      ularni boshqa joyga ko‘chiring, aks holda imtihon kuni client ularni qabul qilmaydi.
      {view === 'map' && ' Xaritada ular qizil «!» belgisi bilan ko‘rsatilgan.'}
    </Alert>
  )

  if (view === 'map') {
    return (
      <>
        <PageHeader
          title="Kompyuter bronlari"
          subtitle="Talabgor faqat o‘ziga biriktirilgan kompyuterda test topshiradi — JSHSHIR kiritilganda client tekshiradi"
          actions={headerActions}
        />
        <Stack spacing={2}>
          <ScheduleBar
            options={scheduleOptions}
            loading={schedulesLoading}
            value={schedule}
            onChange={(option) => setScheduleId(option?.value || null)}
          />
          {schedule && <StatsStrip stats={stats} />}
          {brokenAlert}
          <BookingMap
            scheduleId={scheduleId}
            canManage={canManage}
            busy={assignMutation.isPending || activeMutation.isPending}
            onAssign={(seat, pinfl) => assignMutation.mutate({ pinfl, computer: seat.computer })}
            onMove={(from, to) => assignMutation.mutate({ pinfl: from.pinfl, computer: to.computer })}
            onRelease={(seat) => setReleasing(seat)}
            onToggleActive={(seat, isActive) => activeMutation.mutate({ id: seat.id, isActive })}
            onGenerate={canManage ? () => generateMutation.mutate() : null}
          />
        </Stack>
        {dialogs}
      </>
    )
  }

  return (
    <>
      <ResourcePage
        title="Kompyuter bronlari"
        subtitle="Talabgor faqat o‘ziga biriktirilgan kompyuterda test topshiradi — JSHSHIR kiritilganda client tekshiradi"
        queryKey="computer-bookings"
        api={bookingsApi}
        permission="bookings.manage"
        canCreate={false}
        canEdit={false}
        deleteDescription="Joy shu test sessiyasidan olib tashlanadi. Band joyni o‘chirib bo‘lmaydi — avval bo‘shating."
        getRowLabel={(row) => row?.computer_label || `#${row?.id}`}
        searchPlaceholder="JSHSHIR, raqam yoki inventar kodi…"
        exportName="kompyuter-bronlari"
        columns={columns}
        fields={[]}
        height={640}
        refetchInterval={30000}
        staticParams={{ schedule: scheduleId, ...scopeParams }}
        toggleField="is_active"
        toggleLabel="Ishchi"
        filters={[
          ...regionZoneFilters({
            region: 'computer__zone__region', zone: 'computer__zone', regionOptions, zoneOptions,
          }),
        ]}
        emptyDescription={
          stats && stats.total === 0
            ? 'Bu test sessiyasida hali joy yo‘q — «Joylarni yaratish» ni bosing'
            : 'Bu shartlarga mos joy topilmadi'
        }
        banner={
          <Stack spacing={2}>
            <ScheduleBar
              options={scheduleOptions}
              loading={schedulesLoading}
              value={schedule}
              onChange={(option) => setScheduleId(option?.value || null)}
            />
            {schedule && (
              <StatsStrip
                stats={stats}
                // Holat filtri SONLAR yonida: "Buzilgan · 3" ni ko'rib, o'sha
                // yerning o'zida ro'yxatni toraytirish tabiiy harakat.
                scope={
                  <ToggleButtonGroup
                    size="small"
                    exclusive
                    value={scope}
                    onChange={(_, value) => value && setScope(value)}
                    // Telefonda segmentlar kenglikni TENG bo'lishadi: aks holda
                    // guruh 390 px ga sig'masdan "Buzilgan" kesilib qolardi.
                    sx={{
                      width: { xs: '100%', md: 'auto' },
                      '& .MuiToggleButton-root': { flex: { xs: 1, md: 'initial' }, px: { xs: 1, md: 1.75 } },
                    }}
                  >
                    <ToggleButton value="all">Barchasi</ToggleButton>
                    <ToggleButton value="booked">Band</ToggleButton>
                    <ToggleButton value="free">Bo‘sh</ToggleButton>
                    <ToggleButton value="broken">Buzilgan</ToggleButton>
                  </ToggleButtonGroup>
                }
              />
            )}
            {brokenAlert}
          </Stack>
        }
        actionsWidth={150}
        rowActions={(row) => (
          <Stack direction="row" spacing={0.5} alignItems="center">
            {!row.is_booked && row.is_active && (
              <Button size="small" startIcon={<AssignIcon />} onClick={() => setAssigning({ seat: row })}>
                Biriktirish
              </Button>
            )}
            {row.is_booked && (
              <>
                {/* `span` — o'chirilgan tugma tooltip ko'rsatmaydi, sabab esa
                    aynan shu holatda kerak. */}
                <Tooltip title={seatInExam(row) ? IN_EXAM_HINT : 'Boshqa kompyuterga ko‘chirish'}>
                  <span>
                    <IconButton
                      size="small"
                      color={row.is_active ? 'default' : 'error'}
                      aria-label="Boshqa kompyuterga ko‘chirish"
                      disabled={seatInExam(row)}
                      onClick={() => setAssigning({ move: row })}
                    >
                      <MoveIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={seatInExam(row) ? IN_EXAM_HINT : 'Joyni bo‘shatish'}>
                  <span>
                    <IconButton
                      size="small"
                      aria-label="Joyni bo‘shatish"
                      disabled={seatInExam(row)}
                      onClick={() => setReleasing(row)}
                    >
                      <ReleaseIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </>
            )}
          </Stack>
        )}
        headerActions={headerActions}
      />

      {dialogs}
    </>
  )
}

/**
 * Xarita ko'rinishi: binolar ("vagonlar") + tanlangan binoning zali.
 *
 * Tanlangan bino URL'da (`?zone=`): sahifa yangilanganda yoki havola
 * yuborilganda operator aynan o'sha zalga qaytadi.
 *
 * KO'CHIRISH — ikki bosqichli: panelda «Boshqa joyga ko'chirish», keyin
 * xaritada bo'sh o'rindiqni bosish. Bo'sh joylar tebranadi, qolganlari
 * xiralashadi; binoni almashtirib boshqa zalga ham ko'chirish mumkin.
 */
function BookingMap({
  scheduleId, canManage, busy, onAssign, onMove, onRelease, onToggleActive, onGenerate,
}) {
  const { notify, notifyError } = useUi()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedId, setSelectedId] = useState(null)
  const [moveFrom, setMoveFrom] = useState(null)
  const [highlightId, setHighlightId] = useState(null)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)

  const zonesQuery = useQuery({
    queryKey: ['computer-bookings', 'zones', scheduleId],
    queryFn: () => bookingsApi.zones({ schedule: scheduleId }),
    refetchInterval: 30000,
  })
  const zones = zonesQuery.data?.results || []

  const urlZone = Number(searchParams.get('zone')) || null
  const zoneId = zones.some((zone) => zone.zone === urlZone) ? urlZone : zones[0]?.zone ?? null
  const zone = zones.find((item) => item.zone === zoneId) || null

  const setZone = useCallback(
    (id) =>
      setSearchParams((prev) => {
        const params = new URLSearchParams(prev)
        params.set('zone', String(id))
        return params
      }, { replace: true }),
    [setSearchParams],
  )

  const seatsQuery = useQuery({
    queryKey: ['computer-bookings', 'seats', scheduleId, zoneId],
    queryFn: () => bookingsApi.seats({ schedule: scheduleId, zone: zoneId }),
    enabled: Boolean(zoneId),
    refetchInterval: 30000,
  })
  const seats = seatsQuery.data?.results || []
  const selected = seats.find((seat) => seat.id === selectedId) || null

  // Seans almashsa tanlov eskiradi: o'sha ID boshqa seansga tegishli.
  useEffect(() => {
    setSelectedId(null)
    setMoveFrom(null)
  }, [scheduleId])

  const counts = useMemo(() => {
    const result = { free: 0, booked: 0, broken: 0 }
    for (const seat of seats) {
      const state = seatState(seat)
      if (state === 'free') result.free += 1
      else if (state === 'booked') result.booked += 1
      else result.broken += 1
    }
    return result
  }, [seats])

  const handleSelect = (seat) => {
    if (moveFrom) {
      if (seat.id === moveFrom.id) return
      if (seatState(seat) !== 'free') {
        notify('Faqat bo‘sh va ishchi joyni tanlang', 'warning')
        return
      }
      onMove(moveFrom, seat)
      setMoveFrom(null)
      setSelectedId(seat.id)
      setHighlightId(null)
      return
    }
    setSelectedId(seat.id)
    setHighlightId(null)
  }

  /**
   * Qidiruv: 14 raqam — JSHSHIR (butun sessiya bo'yicha, bino
   * avtomatik almashadi), aks holda — shu zaldagi kompyuter raqami.
   */
  const search = async () => {
    const value = query.trim()
    if (!value) return
    if (/^\d{14}$/.test(value)) {
      setSearching(true)
      try {
        const data = await bookingsApi.list({ schedule: scheduleId, pinfl: value, page_size: 1 })
        const row = data?.results?.[0]
        if (!row) {
          notify('Bu JSHSHIR shu sessiyada hech qaysi joyga biriktirilmagan', 'warning')
          return
        }
        setZone(row.zone)
        setSelectedId(row.id)
        setHighlightId(row.id)
      } catch (error) {
        notifyError(error)
      } finally {
        setSearching(false)
      }
      return
    }
    const seat = seats.find(
      (item) => String(item.computer_number) === value || item.inventory_code === value,
    )
    if (seat) {
      setSelectedId(seat.id)
      setHighlightId(seat.id)
    } else {
      notify(`«${value}» bu zalda topilmadi`, 'warning')
    }
  }

  if (!zonesQuery.isLoading && zones.length === 0) {
    return (
      <Card>
        <EmptyState
          title="Bu test sessiyasida hali joy yo‘q"
          description="Joylar sessiya doirasidagi kompyuterlardan yig‘iladi — «Joylarni yaratish» ni bosing."
          actionLabel={onGenerate ? 'Joylarni yaratish' : undefined}
          onAction={onGenerate || undefined}
        />
      </Card>
    )
  }

  return (
    <Box
      sx={{
        display: 'grid',
        gap: 2,
        gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: '300px minmax(0, 1fr)' },
        alignItems: 'start',
      }}
    >
      <ZoneRail zones={zones} loading={zonesQuery.isLoading} value={zoneId} onChange={setZone} />

      <Card sx={{ overflow: 'visible' }}>
        <Stack spacing={2} sx={{ p: { xs: 2, sm: 2.5 } }}>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1.5}
            alignItems={{ xs: 'stretch', sm: 'center' }}
          >
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography variant="h6" noWrap>{zone?.zone_name || '—'}</Typography>
              <Typography variant="body2" color="text.secondary" noWrap>
                {zone ? `${zone.region_name} · ${zone.total} ta joy` : ''}
              </Typography>
            </Box>
            <TextField
              size="small"
              value={query}
              onChange={(event) => setQuery(event.target.value.replace(/\s/g, ''))}
              onKeyDown={(event) => event.key === 'Enter' && search()}
              placeholder="JSHSHIR yoki kompyuter raqami"
              sx={{ width: { xs: '100%', sm: 280 } }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>
                ),
                endAdornment: (
                  <InputAdornment position="end">
                    <Button size="small" onClick={search} disabled={!query.trim() || searching}>
                      Topish
                    </Button>
                  </InputAdornment>
                ),
              }}
            />
          </Stack>

          <Legend counts={counts} />

          {moveFrom && (
            <Alert
              severity="info"
              icon={<MoveIcon />}
              action={
                <IconButton size="small" color="inherit" aria-label="Ko‘chirishni bekor qilish" onClick={() => setMoveFrom(null)}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              }
            >
              <strong>{moveFrom.pinfl}</strong> ({moveFrom.computer_label}) uchun yangi bo‘sh joyni
              bosing. Boshqa binoni ham tanlash mumkin.
            </Alert>
          )}

          {seatsQuery.data?.truncated && (
            <Alert severity="warning">
              Binoda juda ko‘p kompyuter — xaritada birinchi 2000 tasi. To‘liq ro‘yxat «Ro‘yxat» ko‘rinishida.
            </Alert>
          )}

          {seatsQuery.isLoading || zonesQuery.isLoading ? (
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, 62px)', gap: 1.25, justifyContent: 'center' }}>
              {Array.from({ length: 20 }).map((_, index) => (
                <Box key={index} sx={{ width: 62, height: 64, borderRadius: '12px', bgcolor: 'action.hover' }} />
              ))}
            </Box>
          ) : seats.length === 0 ? (
            <EmptyState title="Bu binoda joy yo‘q" dense />
          ) : (
            <SeatGrid
              seats={seats}
              selectedId={moveFrom ? moveFrom.id : selectedId}
              onSelect={handleSelect}
              moveMode={Boolean(moveFrom)}
              highlightId={highlightId}
            />
          )}
          {seatsQuery.isFetching && !seatsQuery.isLoading && (
            <LinearProgress sx={{ borderRadius: 999, height: 3 }} />
          )}
        </Stack>
      </Card>

      <SeatPanel
        seat={moveFrom ? null : selected}
        zoneName={zone?.zone_name}
        canManage={canManage}
        busy={busy}
        onClose={() => setSelectedId(null)}
        onAssign={onAssign}
        onRelease={onRelease}
        onStartMove={(seat) => {
          setMoveFrom(seat)
          setSelectedId(null)
        }}
        onToggleActive={onToggleActive}
      />
    </Box>
  )
}

/** Katak ichidagi mazmun — vertikal markazda (`DeviceTokens.CellText` bilan bir xil). */
function Cell({ children }) {
  return (
    <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', minWidth: 0 }}>{children}</Box>
  )
}

/**
 * Stol raqami — jadvalning ENG YIRIK elementi.
 *
 * Operator talabgorni aynan shu raqam bilan yo'naltiradi ("12-kompyuterga
 * o'ting"); buzilgan joy raqami chizilgan va qizil — rang ko'rmaydigan
 * odam ham farqni ko'radi.
 */
function SeatNumber({ value, broken }) {
  return (
    <Cell>
      <Box
        sx={(theme) => ({
          minWidth: 40,
          height: 30,
          px: 1,
          borderRadius: 2,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 800,
          fontSize: 15,
          letterSpacing: 0.2,
          color: broken ? theme.palette.error.main : theme.palette.primary.main,
          bgcolor: alpha(broken ? theme.palette.error.main : theme.palette.primary.main, 0.12),
          textDecoration: broken ? 'line-through' : 'none',
        })}
      >
        {value ?? '—'}
      </Box>
    </Cell>
  )
}

function ScheduleBar({ options, loading, value, onChange }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: '16px' }}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
          <Box
            sx={(theme) => ({
              width: 44, height: 44, borderRadius: 3, flexShrink: 0,
              display: 'grid', placeItems: 'center',
              color: theme.palette.primary.main,
              bgcolor: alpha(theme.palette.primary.main, 0.12),
            })}
          >
            <SeatIcon />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.2 }}>
              Test sessiyasi
            </Typography>
            <Typography variant="subtitle1" fontWeight={700} noWrap>
              {value ? value.exam : 'Tanlanmagan'}
            </Typography>
          </Box>
        </Stack>
        <Autocomplete
          sx={{ flex: 1, minWidth: 280 }}
          size="small"
          loading={loading}
          options={options}
          value={value}
          onChange={(_, option) => option && onChange(option)}
          isOptionEqualToValue={(option, item) => option.value === item.value}
          getOptionLabel={(option) => option?.label || ''}
          disableClearable
          renderOption={(props, option) => (
            <li {...props} key={option.value}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ width: '100%' }}>
                <Typography variant="body2" sx={{ flex: 1 }}>{option.label}</Typography>
                {option.isOpen && <Chip size="small" color="success" label="Ochiq" />}
              </Stack>
            </li>
          )}
          renderInput={(params) => <TextField {...params} label="Seansni tanlang" />}
          noOptionsText="Imtihon jadvalida seans yo‘q"
        />
        {value && (
          <Chip
            color={value.isOpen ? 'success' : 'default'}
            variant={value.isOpen ? 'filled' : 'outlined'}
            label={value.isOpen ? 'Kirish ochiq' : 'Kirish yopiq'}
            sx={{ alignSelf: { xs: 'flex-start', md: 'center' } }}
          />
        )}
      </Stack>
    </Paper>
  )
}

/**
 * Sessiya sonlari — MD3 "stat" plitalari va bandlik chizig'i.
 *
 * Bandlik foizi sessiyaning asosiy savoliga javob beradi: "hamma
 * talabgorga joy yetadimi?". Buzilgan joylar ALOHIDA sanaladi va ular
 * bo'sh joylar sonidan chiqarilgan — bo'sh deb ko'rsatilgan joy
 * haqiqatan talabgor qabul qila oladi.
 */
function StatsStrip({ stats, scope }) {
  const total = stats?.total ?? 0
  const booked = stats?.booked ?? 0
  const usable = total - (stats?.broken ?? 0)
  const percent = usable > 0 ? Math.round((booked / usable) * 100) : 0
  const tiles = [
    { key: 'total', label: 'Jami joy', value: stats?.total, color: 'primary' },
    { key: 'booked', label: 'Band', value: stats?.booked, color: 'info' },
    { key: 'free', label: 'Bo‘sh', value: stats?.free, color: 'success' },
    { key: 'broken', label: 'Buzilgan', value: stats?.broken, color: 'error' },
  ]
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: '16px' }}>
      {/* Telefonda 2x2: bittadan bo'lganda to'rtta plita ~340 px egallardi. */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(4, minmax(0, 1fr))' },
          gap: 1.5,
        }}
      >
        {tiles.map((tile) => (
          <Box
            key={tile.key}
            sx={(theme) => ({
              px: 2,
              py: 1.25,
              borderRadius: '12px',
              bgcolor: alpha(theme.palette[tile.color].main, 0.08),
            })}
          >
            <Typography variant="caption" color="text.secondary" fontWeight={600}>
              {tile.label}
            </Typography>
            <Typography variant="h5" fontWeight={800} color={`${tile.color}.main`}>
              {tile.value ?? '—'}
            </Typography>
          </Box>
        ))}
      </Box>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={{ xs: 1.5, md: 2 }}
        alignItems={{ md: 'center' }}
        sx={{ mt: 1.75 }}
      >
        <Box sx={{ flexShrink: 0 }}>{scope}</Box>
        <LinearProgress
          variant="determinate"
          value={Math.min(100, percent)}
          sx={{ flex: 1, height: 8, borderRadius: 4 }}
        />
        <Box sx={{ minWidth: { md: 170 }, textAlign: { md: 'right' } }}>
          <Typography variant="body2" fontWeight={700} noWrap>
            Bandlik: {percent}% ({booked} / {usable})
          </Typography>
          {/* Yakunlagan talabgorning joyi bo'shaydi va "Band" dan chiqadi —
              usiz bandlik kamayib borishi "talabgorlar kelmadi" bo'lib o'qilardi. */}
          {stats?.finished > 0 && (
            <Typography variant="caption" color="text.secondary" noWrap>
              Yakunlaganlar: {stats.finished}
            </Typography>
          )}
        </Box>
      </Stack>
    </Paper>
  )
}

/**
 * Biriktirish va ko'chirish — bitta dialog, uch rejim:
 *
 *   `seat`  — jadvaldagi aniq bo'sh joyga (faqat JSHSHIR so'raladi);
 *   `move`  — talabgor tayin, yangi joy tanlanadi;
 *   hech biri — JSHSHIR + joy: avtomatik (eng kichik bo'sh raqam) yoki qo'lda.
 *
 * Bo'sh joylar ro'yxati BRON endpointidan olinadi, kompyuterlar
 * ro'yxatidan emas: u faqat SHU sessiyadagi, ishchi va band bo'lmagan
 * joylarni ko'rsatadi va `devices.view` ruxsatini talab qilmaydi.
 */
function AssignDialog({ schedule, seat, move, zoneOptions, loading, onSave, onClose }) {
  const [pinfl, setPinfl] = useState(move?.pinfl || '')
  const [target, setTarget] = useState(null)
  const [auto, setAuto] = useState(!seat && !move)
  const [zone, setZone] = useState(null)

  const { options: freeSeats, isLoading } = useOptions(
    'computer-bookings',
    bookingsApi,
    (item) => ({
      value: item.computer,
      label: `${item.computer_label} — ${item.zone_name}`,
      zone: item.zone,
    }),
    { schedule: schedule.value, is_booked: false, is_active: true },
  )

  const pinflError = pinfl && !PINFL_RE.test(pinfl) ? 'JSHSHIR 14 ta raqamdan iborat' : ''
  const needsSeat = !seat && (move || !auto)
  const valid = PINFL_RE.test(pinfl) && (!needsSeat || target)

  const submit = () => {
    if (!valid || loading) return
    const payload = { pinfl }
    if (seat) payload.computer = seat.computer
    else if (needsSeat) payload.computer = target.value
    else if (zone) payload.zone = zone.value
    onSave(payload)
  }

  const title = move ? 'Boshqa kompyuterga ko‘chirish' : 'Talabgorni biriktirish'
  // Umumiy sessiyada avtomatik rejim uchun binoni tanlash mumkin —
  // aks holda talabgor birinchi viloyatning birinchi binosiga tushardi.
  const zoneChoices = schedule.zone ? [] : zoneOptions

  return (
    <Dialog open onClose={loading ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2.25} sx={{ pt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">{schedule.label}</Typography>

          {seat && (
            <Alert severity="info" icon={<SeatIcon />}>
              Joy: <strong>{seat.computer_label}</strong> · {seat.zone_name}
            </Alert>
          )}
          {move && (
            <Alert severity={move.is_active ? 'info' : 'warning'} icon={<MoveIcon />}>
              Hozirgi joy: <strong>{move.computer_label}</strong> · {move.zone_name}
              {!move.is_active && ' — buzilgan'}
            </Alert>
          )}

          <TextField
            label="JSHSHIR"
            value={pinfl}
            disabled={Boolean(move)}
            autoFocus={!move}
            onChange={(event) => setPinfl(event.target.value.replace(/\D/g, '').slice(0, 14))}
            error={Boolean(pinflError)}
            helperText={pinflError || `${pinfl.length} / 14`}
            inputProps={{ inputMode: 'numeric', style: { fontFamily: 'monospace', letterSpacing: 2 } }}
            onKeyDown={(event) => event.key === 'Enter' && submit()}
          />

          {!seat && !move && (
            <ToggleButtonGroup
              exclusive
              fullWidth
              size="small"
              value={auto ? 'auto' : 'manual'}
              onChange={(_, value) => value && setAuto(value === 'auto')}
            >
              <ToggleButton value="auto">
                <AutoIcon fontSize="small" sx={{ mr: 1 }} /> Avtomatik
              </ToggleButton>
              <ToggleButton value="manual">
                <SeatIcon fontSize="small" sx={{ mr: 1 }} /> Joyni tanlash
              </ToggleButton>
            </ToggleButtonGroup>
          )}

          {!seat && !move && auto && (
            <>
              <Typography variant="body2" color="text.secondary">
                Binodagi eng kichik raqamli bo‘sh ishchi kompyuter tanlanadi. Talabgorning joyi
                allaqachon bo‘lsa, o‘sha qaytariladi.
              </Typography>
              {zoneChoices.length > 0 && (
                <Autocomplete
                  options={zoneChoices}
                  value={zone}
                  onChange={(_, option) => setZone(option)}
                  isOptionEqualToValue={(option, item) => option.value === item.value}
                  getOptionLabel={(option) => option?.label || ''}
                  renderInput={(params) => (
                    <TextField {...params} label="Bino (ixtiyoriy)" helperText="Umumiy sessiya — bino tanlanmasa birinchi bo‘sh joy olinadi" />
                  )}
                />
              )}
            </>
          )}

          {needsSeat && (
            <Autocomplete
              options={freeSeats}
              loading={isLoading}
              value={target}
              onChange={(_, option) => setTarget(option)}
              isOptionEqualToValue={(option, item) => option.value === item.value}
              getOptionLabel={(option) => option?.label || ''}
              renderInput={(params) => (
                <TextField {...params} label="Bo‘sh kompyuter" autoFocus={Boolean(move)} />
              )}
              noOptionsText="Bo‘sh ishchi joy yo‘q — avval «Joylarni yaratish»"
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={loading}>Bekor qilish</Button>
        <Button
          variant="contained"
          startIcon={move ? <MoveIcon /> : <AssignIcon />}
          disabled={!valid || loading}
          onClick={submit}
        >
          {move ? 'Ko‘chirish' : 'Biriktirish'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function Detail({ label, value, mono }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ fontFamily: mono ? 'monospace' : undefined }}>
        {value}
      </Typography>
    </Box>
  )
}
