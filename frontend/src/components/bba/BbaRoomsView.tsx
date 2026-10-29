import { memo, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert, Box, InputAdornment, LinearProgress, Stack, TextField, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import MeetingRoomIcon from '@mui/icons-material/MeetingRoomOutlined'

import { bba } from '../../api/endpoints'
import { BBA_STATUS_LABEL, fromNow } from '../../utils/labels'
import type { Theme } from '@mui/material/styles'
import type { SystemStyleObject } from '@mui/system'
import type { ApiRecord, Id } from '../../types/api'

const STATUSES = ['online', 'offline_unexpected', 'offline_graceful', 'unknown'] as const
const VISIBLE_PARAMS = { is_visible: 'true' }

/** Holat -> palitra rangi (`common.BBA_STATUS_TONE` bilan bir xil ma'no). */
const toneOf = (theme: Theme, status: string) => ({
  online: theme.palette.success.main,
  offline_unexpected: theme.palette.error.main,
  revoked: theme.palette.error.main,
  offline_graceful: theme.palette.text.disabled,
  unknown: theme.palette.text.disabled,
}[status] || theme.palette.text.disabled)

const regionKey = (id: Id | null) => (id == null ? 'none' : String(id))

/**
 * BBA kompyuterlari VILOYAT -> XONA bo'yicha: chapda viloyatlar (holatlar
 * soni bilan), o'ngda tanlangan viloyatning xonalari, har xonada
 * kompyuterlar plitkasi holat rangida.
 *
 * Sonlar — server GROUP BY (`devices/tree/`), plitkalar — bitta viloyat
 * (`devices/by-room/`, sahifasiz). Holat o'zgarishi WebSocket bilan keladi:
 * `useBbaLive` `['bba-devices', ...]` keshidagi qatorlarni o'rnida
 * yangilaydi, sonlarni esa qayta so'raydi.
 *
 * Plitka — oddiy `<button>` + `data-status`, stil bitta blokda, tooltip —
 * brauzerning `title` i: xonada yuzlab kompyuter bo'lganda MUI `Tooltip`/
 * `sx` har plitkada render'ni sekinlashtirardi (`SeatGrid` bilan bir xil sabab).
 */
export default function BbaRoomsView({
  status, region, onRegionChange, onOpen,
}: {
  status: string
  region: string | null
  onRegionChange: (key: string) => void
  onOpen: (id: Id) => void
}) {
  const [search, setSearch] = useState('')
  const { data: tree, isLoading: treeLoading } = useQuery({
    queryKey: ['bba-tree', VISIBLE_PARAMS],
    queryFn: () => bba.devices.tree(VISIBLE_PARAMS),
    refetchInterval: 60000,
  })
  const regions: ApiRecord[] = tree?.regions || []
  const selected = regions.find((item) => regionKey(item.id) === region) || regions[0]
  const selectedKey = selected ? regionKey(selected.id) : null

  const { data: devices, isLoading } = useQuery({
    queryKey: ['bba-devices', 'by-room', selectedKey],
    queryFn: () => bba.devices.byRoom({ ...VISIBLE_PARAMS, bba_region: selectedKey! }),
    enabled: selectedKey != null,
    refetchInterval: 60000,
  })

  const rooms = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const byRoom = new Map<string, ApiRecord[]>()
    for (const device of (devices?.results || []) as ApiRecord[]) {
      if (status !== 'all' && device.status !== status) continue
      if (needle && ![device.name, device.hostname, device.primary_mac, device.computer_label]
        .some((value) => String(value || '').toLowerCase().includes(needle))) continue
      const key = String(device.room ?? 'none')
      if (!byRoom.has(key)) byRoom.set(key, [])
      byRoom.get(key)!.push(device)
    }
    return (selected?.rooms || [])
      .map((room: ApiRecord) => ({ room, devices: byRoom.get(String(room.id ?? 'none')) || [] }))
      .filter((item: { devices: ApiRecord[] }) => item.devices.length > 0)
  }, [devices, selected, status, search])

  if (treeLoading) return <LinearProgress />
  if (!regions.length) {
    return <Alert severity="info">Kompyuterlar hali yo‘q — Console bilan sinxronlanmagan yoki sizga hudud bog‘lanmagan.</Alert>
  }

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '300px minmax(0, 1fr)' }, gap: 2, alignItems: 'start' }}>
      <Box
        component="nav"
        aria-label="Viloyatlar"
        sx={(theme) => ({
          ...regionListStyles(theme),
          position: { md: 'sticky' },
          top: { md: 16 },
          maxHeight: { md: 'calc(100vh - 160px)' },
          overflowY: 'auto',
        })}
      >
        {regions.map((item) => (
          <RegionItem
            key={regionKey(item.id)}
            region={item}
            active={regionKey(item.id) === selectedKey}
            onSelect={onRegionChange}
          />
        ))}
      </Box>

      <Box sx={{ minWidth: 0 }}>
        {selected && (
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }} sx={{ mb: 1.5 }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h6" noWrap>{selected.name}</Typography>
              <Typography variant="body2" color="text.secondary">
                {selected.region_name ? `Viloyat: ${selected.region_name} · ` : ''}
                {selected.rooms.length} ta xona · {selected.total} ta kompyuter · yoniq {selected.by_status.online}
              </Typography>
            </Box>
            <TextField
              size="small"
              placeholder="Kompyuter, MAC…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: '100%', sm: 240 } }}
              slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
            />
          </Stack>
        )}
        <Legend />
        {isLoading && <LinearProgress sx={{ my: 1 }} />}
        {devices?.truncated && (
          <Alert severity="warning" sx={{ mb: 1.5 }}>Hududda kompyuter juda ko‘p — birinchi 3000 tasi ko‘rsatilmoqda.</Alert>
        )}
        {!isLoading && !rooms.length && (
          <Alert severity="info">Bu shartlarga mos kompyuter yo‘q.</Alert>
        )}
        <Box sx={roomStyles}>
          {rooms.map(({ room, devices: list }: { room: ApiRecord; devices: ApiRecord[] }) => (
            <RoomCard key={String(room.id ?? 'none')} room={room} devices={list} onOpen={onOpen} />
          ))}
        </Box>
      </Box>
    </Box>
  )
}

function RegionItem({ region, active, onSelect }: { region: ApiRecord; active: boolean; onSelect: (key: string) => void }) {
  const total = region.total || 1
  return (
    <button
      type="button"
      className="bba-region"
      data-active={active || undefined}
      onClick={() => onSelect(regionKey(region.id))}
    >
      <span className="bba-region-head">
        <span className="bba-region-name">{region.name}</span>
        <span className="bba-region-count">
          <b>{region.by_status.online}</b>/{region.total}
        </span>
      </span>
      <span className="bba-region-sub">
        {[region.region_name, `${region.rooms.length} ta xona`].filter(Boolean).join(' · ')}
      </span>
      <span className="bba-region-bar" aria-hidden>
        {STATUSES.map((status) => (
          region.by_status[status]
            ? <span key={status} data-status={status} style={{ width: `${(region.by_status[status] / total) * 100}%` }} />
            : null
        ))}
      </span>
    </button>
  )
}

function Legend() {
  return (
    <Stack direction="row" spacing={2} sx={{ mb: 1.5, flexWrap: 'wrap' }} useFlexGap>
      {(['online', 'offline_graceful', 'offline_unexpected'] as const).map((status) => (
        <Stack key={status} direction="row" spacing={0.75} alignItems="center">
          <Box
            sx={(theme) => ({ width: 10, height: 10, borderRadius: '50%', bgcolor: toneOf(theme, status) })}
          />
          <Typography variant="caption" color="text.secondary">{BBA_STATUS_LABEL[status]}</Typography>
        </Stack>
      ))}
      <Typography variant="caption" color="text.secondary">· ramka chizig‘i — bizning ro‘yxatda yo‘q</Typography>
    </Stack>
  )
}

const RoomCard = memo(function RoomCard({
  room, devices, onOpen,
}: { room: ApiRecord; devices: ApiRecord[]; onOpen: (id: Id) => void }) {
  const counts = useMemo(() => {
    const result: Record<string, number> = {}
    for (const device of devices) result[device.status] = (result[device.status] || 0) + 1
    return result
  }, [devices])
  return (
    <section className="bba-room">
      <header className="bba-room-head">
        <MeetingRoomIcon fontSize="small" />
        <span className="bba-room-name">{room.name}</span>
        <span className="bba-room-counts">
          {(['online', 'offline_graceful', 'offline_unexpected'] as const).map((status) => (
            counts[status] ? (
              <span key={status} data-status={status}>{BBA_STATUS_LABEL[status]} {counts[status]}</span>
            ) : null
          ))}
          <span>jami {devices.length}</span>
        </span>
      </header>
      <div className="bba-tiles">
        {devices.map((device) => <Tile key={device.id} device={device} onOpen={onOpen} />)}
      </div>
    </section>
  )
})

const Tile = memo(function Tile({ device, onOpen }: { device: ApiRecord; onOpen: (id: Id) => void }) {
  const status = device.revoked_at ? 'revoked' : device.status
  const title = [
    device.name,
    device.hostname && device.hostname !== device.name ? `Windows: ${device.hostname}` : '',
    device.revoked_at ? 'Console’dan chiqarilgan' : BBA_STATUS_LABEL[device.status] || device.status,
    device.last_seen_at ? `oxirgi aloqa ${fromNow(device.last_seen_at)}` : '',
    device.computer_label ? `Bizda: ${device.computer_label}` : 'Bizning ro‘yxatda yo‘q',
    device.primary_mac,
  ].filter(Boolean).join('\n')
  return (
    <button
      type="button"
      className="bba-tile"
      data-status={status}
      data-linked={device.computer_label ? 'yes' : 'no'}
      title={title}
      onClick={() => onOpen(device.id)}
    >
      <span className="bba-tile-name"><i aria-hidden />{device.name}</span>
      <span className="bba-tile-sub">{device.computer_label || 'ro‘yxatda yo‘q'}</span>
    </button>
  )
})

/** `<prefix>[data-status="..."]` selektorlari — har holatga bitta qoida. */
function byStatus(
  statuses: readonly string[], style: (status: string) => SystemStyleObject<Theme>, prefix: string,
): Record<string, SystemStyleObject<Theme>> {
  const result: Record<string, SystemStyleObject<Theme>> = {}
  for (const status of statuses) result[`${prefix}[data-status="${status}"]`] = style(status)
  return result
}

function regionListStyles(theme: Theme): SystemStyleObject<Theme> {
  return {
    bgcolor: 'background.paper',
    borderRadius: '16px',
    p: 0.75,
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
    '& .bba-region': {
      all: 'unset', boxSizing: 'border-box', cursor: 'pointer', display: 'flex', flexDirection: 'column',
      gap: '4px', padding: '10px 12px', borderRadius: '12px',
      '&:hover': { bgcolor: theme.palette.action.hover },
      '&:focus-visible': { outline: `2px solid ${theme.palette.primary.main}` },
      '&[data-active]': { bgcolor: theme.palette.m3.secondaryContainer },
    },
    '& .bba-region-head': { display: 'flex', alignItems: 'baseline', gap: '8px' },
    '& .bba-region-name': {
      flex: 1, minWidth: 0, fontWeight: 600, fontSize: 14,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .bba-region-count': { fontSize: 12, color: theme.palette.text.secondary, '& b': { color: theme.palette.success.main } },
    '& .bba-region-sub': { fontSize: 12, color: theme.palette.text.secondary },
    '& .bba-region-bar': {
      display: 'flex', height: 4, borderRadius: 2, overflow: 'hidden', bgcolor: theme.palette.action.selected,
      '& > span': { height: '100%' },
      ...byStatus(STATUSES, (status) => ({ bgcolor: toneOf(theme, status) }), '& > span'),
    },
  }
}

function roomStyles(theme: Theme): SystemStyleObject<Theme> {
  const tile = (status: string): SystemStyleObject<Theme> => {
    const color = toneOf(theme, status)
    return {
      borderColor: alpha(color, status === 'online' ? 0.6 : 0.35),
      bgcolor: alpha(color, status === 'online' ? 0.08 : 0.04),
      '& i': { bgcolor: color, ...(status === 'online' ? { boxShadow: `0 0 6px ${alpha(color, 0.8)}` } : {}) },
    }
  }
  return {
    display: 'flex', flexDirection: 'column', gap: 1.5,
    '& .bba-room': {
      bgcolor: 'background.paper', borderRadius: '16px', p: 1.5,
      // Ekrandan tashqaridagi xona chizilmaydi (viloyatda yuzlab xona).
      contentVisibility: 'auto', containIntrinsicSize: 'auto 180px',
    },
    '& .bba-room-head': {
      display: 'flex', alignItems: 'center', gap: '8px', mb: 1, flexWrap: 'wrap',
      color: theme.palette.text.secondary,
    },
    '& .bba-room-name': { fontWeight: 650, fontSize: 15, color: theme.palette.text.primary },
    '& .bba-room-counts': {
      display: 'flex', gap: '10px', ml: 'auto', fontSize: 12, flexWrap: 'wrap',
      '& [data-status="online"]': { color: theme.palette.success.main, fontWeight: 600 },
      '& [data-status="offline_unexpected"]': { color: theme.palette.error.main, fontWeight: 600 },
    },
    '& .bba-tiles': {
      display: 'grid', gap: '8px', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    },
    '& .bba-tile': {
      all: 'unset', boxSizing: 'border-box', cursor: 'pointer', display: 'flex', flexDirection: 'column',
      gap: '2px', padding: '8px 10px', borderRadius: '12px', border: '1.5px solid', minWidth: 0,
      transition: 'transform 120ms, box-shadow 120ms',
      '&:hover': { transform: 'translateY(-1px)', boxShadow: theme.shadows[2] },
      '&:focus-visible': { outline: `2px solid ${theme.palette.primary.main}`, outlineOffset: 2 },
      '&[data-linked="no"]': { borderStyle: 'dashed' },
      ...byStatus(['online', 'offline_graceful', 'offline_unexpected', 'unknown', 'revoked'], tile, '&'),
    },
    '& .bba-tile-name': {
      display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, fontSize: 13,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: theme.palette.text.primary,
      '& i': { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
    },
    '& .bba-tile-sub': {
      fontSize: 11.5, color: theme.palette.text.secondary,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
  }
}
