import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, IconButton, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import SyncIcon from '@mui/icons-material/SyncOutlined'
import MapIcon from '@mui/icons-material/MapOutlined'
import TerminalIcon from '@mui/icons-material/TerminalOutlined'
import PowerIcon from '@mui/icons-material/PowerSettingsNewOutlined'
import AddIcon from '@mui/icons-material/AddToQueueOutlined'
import CircleIcon from '@mui/icons-material/Circle'
import RoomsIcon from '@mui/icons-material/GridViewOutlined'
import ListIcon from '@mui/icons-material/ViewListOutlined'

import ResourcePage from '../components/data/ResourcePage'
import PageHeader from '../components/PageHeader'
import BbaRoomsView from '../components/bba/BbaRoomsView'
import type { RoomAction } from '../components/bba/BbaRoomsView'
import ConfirmDialog from '../components/ConfirmDialog'
import BbaDeviceSheet from '../components/bba/BbaDeviceSheet'
import SendJobDialog from '../components/bba/SendJobDialog'
import ImportDialog from '../components/bba/ImportDialog'
import RegionMapDialog from '../components/bba/RegionMapDialog'
import { BbaStatus } from '../components/bba/common'
import { LastSeenCell } from './crud/shared'
import { bba } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'
import { useBbaLive } from '../hooks/useBbaLive'
import { BBA_STATUS_LABEL, fromNow } from '../utils/labels'
import type { ReactNode } from 'react'
import type { JobTarget } from '../components/bba/SendJobDialog'
import type { ImportTarget } from '../components/bba/ImportDialog'
import type { AppColumn, BulkAction, FilterDef } from '../components/data/types'
import type { ApiRecord, Id } from '../types/api'

// Modul doimiylari — `ResourcePage` props barqaror bo'lsin (`CLAUDE.md`).
const devicesApi = { list: bba.devices.list }
const DEFAULT_FILTERS = { is_visible: 'true' }
const STATUSES = ['online', 'offline_graceful', 'offline_unexpected'] as const

function CellText({ value, mono, tooltip }: { value: ReactNode; mono?: boolean; tooltip?: ReactNode }) {
  const node = (
    <Typography
      variant="body2"
      noWrap
      color={value ? undefined : 'text.disabled'}
      sx={mono ? { fontFamily: 'monospace', fontSize: 12.5 } : undefined}
    >
      {value || '—'}
    </Typography>
  )
  return (
    <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', minWidth: 0 }}>
      {tooltip ? <Tooltip title={tooltip}>{node}</Tooltip> : node}
    </Box>
  )
}

interface Pending<T> {
  target: T
  done?: () => void
}

/**
 * BBA Console kompyuterlari — holat REAL VAQTDA (`useBbaLive`).
 *
 * Ro'yxat serverning mahalliy nusxasidan (Console limiti 300 so'rov/daqiqa —
 * har sahifa ochilishi unga bormaydi). «Bizdagi kompyuter» — (UUID, MAC)
 * juftligi bo'yicha topilgan `Computer`; topilmagani «Ro'yxatga qo'shish»
 * bilan bir bosishda qo'shiladi (UUID/MAC inventory'dan, qo'lda yozilmaydi).
 */
export default function BbaDevices() {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { can, user } = useAuth()
  const canJobs = can('bba.jobs')
  const canManage = can('bba.manage')
  const canImport = canManage && can('devices.manage')
  const { connected } = useBbaLive()

  const [scope, setScope] = useState<string>('all')
  // Standart — viloyat -> xona ko'rinishi; jadval `?view=list`, tanlangan
  // viloyat `?region=` (havola bilan ulashiladi, yangilashda saqlanadi).
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get('view') === 'list' ? 'list' : 'rooms'
  const setParam = useCallback((key: string, value: string | null) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev)
      if (value == null) params.delete(key)
      else params.set(key, value)
      return params
    }, { replace: true })
  }, [setSearchParams])
  const selectRegion = useCallback((key: string) => setParam('region', key), [setParam])
  const [detailId, setDetailId] = useState<Id | null>(null)
  const [jobTarget, setJobTarget] = useState<Pending<JobTarget> | null>(null)
  const [importTarget, setImportTarget] = useState<Pending<ImportTarget> | null>(null)
  const [wakeTarget, setWakeTarget] = useState<ApiRecord | null>(null)
  // Xona kartasidagi «yoqish» — xonaning o'chiq kompyuterlari.
  const [roomWake, setRoomWake] = useState<{ devices: ApiRecord[]; roomName: string } | null>(null)
  const [mapping, setMapping] = useState(false)

  const { data: overview } = useQuery({ queryKey: ['bba-overview'], queryFn: bba.overview, refetchInterval: 60000 })
  const { data: regions = [] } = useQuery({ queryKey: ['bba-regions'], queryFn: () => bba.regions.list() })
  const { data: rooms = [] } = useQuery({ queryKey: ['bba-rooms'], queryFn: () => bba.rooms() })

  const sync = useMutation({
    mutationFn: bba.sync,
    retry: false,
    onSuccess: (result) => {
      notify(`Sinxronlandi: ${result.total} ta kompyuter` + (result.created ? ` · ${result.created} ta yangi` : ''))
      ;['bba-devices', 'bba-overview', 'bba-regions', 'bba-rooms'].forEach((key) => (
        queryClient.invalidateQueries({ queryKey: [key] })
      ))
    },
    onError: notifyError,
  })

  const wake = useMutation({
    mutationFn: (id: Id) => bba.devices.wake(id),
    retry: false,
    onSuccess: (data) => {
      const result = data.results?.[0] || {}
      if (result.status === 'already_online') notify('Kompyuter allaqachon yoniq', 'info')
      else if (result.status === 'error') notify(result.message || 'Yoqib bo‘lmadi', 'warning')
      else notify('Yoqish signali yuborildi')
      setWakeTarget(null)
    },
    onError: notifyError,
  })

  const wakeRoom = useMutation({
    mutationFn: (ids: Id[]) => bba.devices.bulkWake({ ids, all: false }),
    retry: false,
    onSuccess: (data) => {
      const rows: ApiRecord[] = data.results || []
      const failed = rows.filter((row) => row.status === 'error').length
      notify(
        `Yoqish signali yuborildi: ${rows.length - failed}` + (failed ? ` · yuborilmadi: ${failed}` : ''),
        failed ? 'warning' : 'success',
      )
      setRoomWake(null)
    },
    onError: notifyError,
  })

  const roomAction = useCallback((action: RoomAction, devices: ApiRecord[], roomName: string) => {
    if (action === 'wake') {
      setRoomWake({ devices, roomName })
      return
    }
    setJobTarget({ target: { selection: { ids: devices.map((device) => device.id), all: false }, count: devices.length } })
  }, [])

  const columns = useMemo(
    (): AppColumn[] => [
      {
        field: 'status', headerName: 'Holat', width: 150,
        exportValue: (value, row) => (row.revoked_at ? 'Chiqarilgan' : BBA_STATUS_LABEL[value] || value),
        renderCell: (params) => <BbaStatus device={params.row} compact />,
      },
      {
        field: 'hostname_code', headerName: 'Nomi', flex: 1, minWidth: 140,
        valueGetter: (value: string, row) => value || row.hostname || '',
        renderCell: (params) => (
          <CellText
            value={params.value}
            tooltip={params.row.hostname && params.row.hostname !== params.value ? `Windows: ${params.row.hostname}` : null}
          />
        ),
      },
      {
        field: 'room_name', headerName: 'Xona', width: 140, sortable: false,
        renderCell: (params) => <CellText value={params.value} />,
      },
      {
        field: 'bba_region_name', headerName: 'Viloyat', width: 170, sortable: false,
        description: 'Console hududi; bizdagi viloyatga bog‘langan bo‘lsa — tooltip’da',
        exportValue: (value, row) => [value, row.region_name].filter(Boolean).join(' / '),
        renderCell: (params) => (
          <CellText value={params.value} tooltip={params.row.region_name ? `Bizda: ${params.row.region_name}` : null} />
        ),
      },
      {
        field: 'computer_label', headerName: 'Bizdagi kompyuter', width: 180, sortable: false,
        exportValue: (value) => value || '',
        description: 'Kompyuterlar ro‘yxatidagi yozuv — (UUID, MAC) juftligi bo‘yicha',
        renderCell: (params) => (
          params.value
            ? <CellText value={params.value} tooltip={params.row.computer_zone_name} />
            : (
              <Box sx={{ height: '100%', display: 'flex', alignItems: 'center' }}>
                <Chip
                  size="small"
                  variant="outlined"
                  color={params.row.system_uuid ? 'warning' : 'default'}
                  label={params.row.system_uuid ? 'Ro‘yxatda yo‘q' : 'UUID yo‘q'}
                />
              </Box>
            )
        ),
      },
      {
        field: 'primary_ip', headerName: 'IP manzil', width: 130, sortable: false,
        renderCell: (params) => <CellText value={params.value} mono />,
      },
      {
        field: 'primary_mac', headerName: 'MAC', width: 160, sortable: false,
        renderCell: (params) => <CellText value={params.value} mono />,
      },
      { field: 'agent_version', headerName: 'Agent', width: 90 },
      { field: 'last_seen_at', headerName: 'Oxirgi aloqa', width: 130, renderCell: LastSeenCell },
    ],
    [],
  )

  const filters = useMemo(
    (): FilterDef[] => [
      {
        name: 'bba_region', label: 'Viloyat', resets: ['room'],
        options: regions.map((item: ApiRecord) => ({ value: item.id, label: item.name })),
      },
      {
        name: 'room', label: 'Xona',
        options: (values) => rooms
          .filter((item: ApiRecord) => !values.bba_region || String(item.bba_region) === String(values.bba_region))
          .map((item: ApiRecord) => ({ value: item.id, label: item.name })),
      },
      {
        name: 'linked', label: 'Bizdagi ro‘yxat',
        options: [{ value: 'true', label: 'Ro‘yxatda bor' }, { value: 'false', label: 'Ro‘yxatda yo‘q' }],
      },
      {
        name: 'revoked', label: 'Console’dan chiqarilgan',
        options: [{ value: 'true', label: 'Chiqarilgan' }, { value: 'false', label: 'Faol' }],
      },
      {
        name: 'is_visible', label: 'Console ro‘yxati',
        options: [{ value: 'true', label: 'Ko‘rinadi' }, { value: 'false', label: 'Ko‘rinmay qolgan' }],
      },
    ],
    [regions, rooms],
  )

  const bulkActions = useMemo((): BulkAction[] => {
    const actions: BulkAction[] = []
    if (canJobs) {
      actions.push({
        key: 'job', label: 'Job yuborish', icon: <TerminalIcon />,
        open: ({ count, ...selection }, done) => setJobTarget({ target: { selection, count }, done }),
      })
      actions.push({
        key: 'wake', label: 'Yoqish', icon: <PowerIcon />, color: 'success',
        confirmTitle: 'Kompyuterlarni yoqish (Wake-on-LAN)',
        description: (count) =>
          `${count} ta kompyuterga yoqish signali yuboriladi — har xonada boshqa yoniq kompyuter orqali. ` +
          'Yoniqlari o‘tkazib yuboriladi.',
        run: (selection) => bba.devices.bulkWake(selection),
        success: (result) => {
          const rows: ApiRecord[] = result.results || []
          const failed = rows.filter((row) => row.status === 'error').length
          return `Signal yuborildi: ${rows.length - failed}` + (failed ? ` · yuborilmadi: ${failed}` : '')
        },
      })
    }
    if (canImport) {
      actions.push({
        key: 'import', label: 'Ro‘yxatga qo‘shish', icon: <AddIcon />,
        open: ({ count, ...selection }, done) => setImportTarget({ target: { selection, count }, done }),
      })
    }
    return actions
  }, [canJobs, canImport])

  const counts = overview?.by_status || {}
  const state = overview?.state || {}
  const countLabel = (value: number | undefined) => (value == null ? '' : ` · ${value}`)

  const banner = !overview ? null : !overview.configured ? (
    <Alert severity="warning">
      BBA Console integratsiyasi sozlanmagan — serverning <code>.env</code> faylida <code>BBA_ENABLED</code>,
      {' '}<code>BBA_USERNAME</code>, <code>BBA_PASSWORD</code> va <code>BBA_CA_FILE</code> ni to‘ldiring.
    </Alert>
  ) : overview.login_blocked ? (
    <Alert severity="error">{overview.login_blocked}</Alert>
  ) : state.ok === false ? (
    <Alert severity="error">
      Console bilan aloqa yo‘q: {state.error}
      {state.last_success_at ? ` · oxirgi muvaffaqiyatli sinxron ${fromNow(state.last_success_at)}` : ''}
      {' '}— ro‘yxatda oxirgi ma’lum holat ko‘rsatilmoqda.
    </Alert>
  ) : canManage && overview.unmapped_regions ? (
    <Alert
      severity="info"
      action={<Button color="inherit" size="small" onClick={() => setMapping(true)}>Bog‘lash</Button>}
    >
      {overview.unmapped_regions} ta Console hududi viloyatga bog‘lanmagan — viloyat xodimlari ularni ko‘rmaydi.
    </Alert>
  ) : null

  const headerActions = (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <Tooltip title={connected ? 'Holat real vaqtda yangilanmoqda' : 'Jonli ulanish yo‘q — ro‘yxat daqiqada yangilanadi'}>
        <Chip
          size="small"
          variant="outlined"
          icon={<CircleIcon sx={{ fontSize: '10px !important' }} color={connected ? 'success' : 'disabled'} />}
          label={connected ? 'Jonli' : 'Ulanmoqda…'}
        />
      </Tooltip>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={view}
        onChange={(_, value) => value && setParam('view', value === 'list' ? 'list' : null)}
      >
        <ToggleButton value="rooms" aria-label="Xonalar bo‘yicha"><RoomsIcon fontSize="small" sx={{ mr: 0.5 }} />Xonalar</ToggleButton>
        <ToggleButton value="list" aria-label="Jadval"><ListIcon fontSize="small" sx={{ mr: 0.5 }} />Jadval</ToggleButton>
      </ToggleButtonGroup>
      {view === 'list' && (
        <ToggleButtonGroup size="small" exclusive value={scope} onChange={(_, value) => value && setScope(value)}>
          <ToggleButton value="all">Barchasi{countLabel(overview?.total)}</ToggleButton>
          {STATUSES.map((status) => (
            <ToggleButton key={status} value={status}>
              {BBA_STATUS_LABEL[status]}{countLabel(counts[status])}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
      )}
      {canManage && !user?.is_region_scoped && (
        <Button size="small" startIcon={<MapIcon />} onClick={() => setMapping(true)}>Hududlar</Button>
      )}
      {canManage && (
        <Button
          size="small" startIcon={<SyncIcon />} disabled={sync.isPending || !overview?.configured}
          onClick={() => sync.mutate()}
        >
          Sinxronlash
        </Button>
      )}
    </Stack>
  )

  const subtitle = overview
    ? `Jami ${overview.total} ta · ro‘yxatda ${overview.linked} tasi` +
      (state.last_success_at ? ` · sinxron ${fromNow(state.last_success_at)}` : '')
    : 'BBA Console’dagi kompyuterlar'

  return (
    <>
      {view === 'rooms' ? (
        <>
          <PageHeader title="Agent PC" subtitle={subtitle} actions={headerActions} />
          {banner && <Box sx={{ mb: 2 }}>{banner}</Box>}
          <BbaRoomsView
            status={scope}
            onStatusChange={setScope}
            region={searchParams.get('region')}
            onRegionChange={selectRegion}
            onOpen={setDetailId}
            canJobs={canJobs}
            onRoomAction={roomAction}
          />
        </>
      ) : (
      <ResourcePage
        title="Agent PC"
        subtitle={subtitle}
        queryKey="bba-devices"
        api={devicesApi}
        permission="bba.view"
        canCreate={false}
        canEdit={false}
        canDelete={false}
        columns={columns}
        fields={[]}
        filters={filters}
        defaultFilters={DEFAULT_FILTERS}
        staticParams={scope === 'all' ? undefined : { status: scope }}
        searchPlaceholder="Nomi, Windows nomi, IP, UUID yoki MAC…"
        exportName="bba-kompyuterlar"
        height={640}
        // WebSocket uzilgan paytda ham ro'yxat eskirib qolmasin.
        refetchInterval={60000}
        onRowClick={(params) => setDetailId(params.row.id)}
        bulkActions={bulkActions}
        emptyDescription={overview?.configured ? 'Bu shartlarga mos kompyuter topilmadi' : 'Integratsiya sozlanmagan'}
        banner={banner}
        actionsWidth={130}
        rowActions={(row) => (
          <Stack direction="row" spacing={0.25} alignItems="center">
            {canJobs && (
              <Tooltip title="Job yuborish">
                <IconButton size="small" aria-label="Job yuborish" onClick={() => setJobTarget({ target: { device: row, count: 1 } })}>
                  <TerminalIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            {canJobs && row.status !== 'online' && (
              <Tooltip title="Yoqish (Wake-on-LAN)">
                <IconButton size="small" color="success" aria-label="Yoqish" onClick={() => setWakeTarget(row)}>
                  <PowerIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            {canImport && !row.computer_label && row.system_uuid && (
              <Tooltip title="Ro‘yxatga qo‘shish">
                <IconButton size="small" color="primary" aria-label="Ro‘yxatga qo‘shish" onClick={() => setDetailId(row.id)}>
                  <AddIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Stack>
        )}
        headerActions={headerActions}
      />
      )}

      <BbaDeviceSheet
        deviceId={detailId}
        canJobs={canJobs}
        canImport={canImport}
        onClose={() => setDetailId(null)}
      />
      {jobTarget && (
        <SendJobDialog
          target={jobTarget.target}
          onClose={() => setJobTarget(null)}
          onSent={jobTarget.done}
        />
      )}
      {importTarget && (
        <ImportDialog
          target={importTarget.target}
          onClose={() => setImportTarget(null)}
          onDone={importTarget.done}
        />
      )}
      {mapping && <RegionMapDialog onClose={() => setMapping(false)} />}
      <ConfirmDialog
        open={Boolean(roomWake)}
        title={`«${roomWake?.roomName || ''}» xonasini yoqish`}
        description={
          `Xonadagi ${roomWake?.devices.length || 0} ta o‘chiq kompyuterga Wake-on-LAN signali yuboriladi — ` +
          'xonadagi boshqa YONIQ kompyuter orqali. Xonada yoniq kompyuter bo‘lmasa yoki BIOS’da WoL o‘chiq bo‘lsa, yoqilmaydi.'
        }
        confirmLabel="Yoqish"
        loading={wakeRoom.isPending}
        onConfirm={() => roomWake && wakeRoom.mutate(roomWake.devices.map((device) => device.id))}
        onClose={() => setRoomWake(null)}
      />
      <ConfirmDialog
        open={Boolean(wakeTarget)}
        title="Kompyuterni yoqish"
        description={
          `«${wakeTarget?.name || ''}» ga Wake-on-LAN signali xonadagi boshqa YONIQ kompyuter orqali yuboriladi. ` +
          'Xonada yoniq kompyuter bo‘lmasa yoki BIOS’da WoL o‘chiq bo‘lsa, yoqilmaydi.'
        }
        confirmLabel="Yoqish"
        loading={wake.isPending}
        onConfirm={() => wakeTarget && wake.mutate(wakeTarget.id)}
        onClose={() => setWakeTarget(null)}
      />
    </>
  )
}
