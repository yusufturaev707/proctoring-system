import { memo, useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert, Avatar, Box, IconButton, InputAdornment, LinearProgress, Stack, TextField, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import MeetingRoomIcon from '@mui/icons-material/MeetingRoomOutlined'
import TerminalIcon from '@mui/icons-material/TerminalOutlined'
import PowerIcon from '@mui/icons-material/PowerSettingsNewOutlined'
import ExpandIcon from '@mui/icons-material/ExpandMoreRounded'
import DevicesIcon from '@mui/icons-material/DevicesOutlined'
import OnlineIcon from '@mui/icons-material/PowerOutlined'
import OffIcon from '@mui/icons-material/PowerOffOutlined'
import LinkOffIcon from '@mui/icons-material/LinkOffOutlined'
import AddLinkIcon from '@mui/icons-material/PlaylistAddOutlined'

import { bba } from '../../api/endpoints'
import { BBA_STATUS_LABEL, fromNow } from '../../utils/labels'
import type { Theme } from '@mui/material/styles'
import type { SystemStyleObject } from '@mui/system'
import type { ComponentType } from 'react'
import type { SvgIconProps } from '@mui/material'
import type { ApiRecord, Id } from '../../types/api'

const STATUSES = ['online', 'offline_unexpected', 'offline_graceful', 'unknown'] as const
const VISIBLE_PARAMS = { is_visible: 'true' }
/** Material `DesktopWindows` yo'li — plitkada SvgIcon komponenti o'rniga (yuzlab plitka). */
const DESKTOP_PATH = 'M21 2H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h7v2H8v2h8v-2h-2v-2h7c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H3V4h18v12z'

export type LinkedFilter = 'all' | 'unlinked'
export type RoomAction = 'job' | 'wake'

const toneOf = (theme: Theme, status: string) => ({
  online: theme.palette.success.main,
  offline_unexpected: theme.palette.error.main,
  revoked: theme.palette.error.main,
  offline_graceful: theme.palette.text.secondary,
  unknown: theme.palette.text.disabled,
}[status] || theme.palette.text.disabled)

const regionKey = (id: Id | null) => (id == null ? 'none' : String(id))
const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase()

/**
 * BBA kompyuterlari VILOYAT -> XONA bo'yicha, Material 3 uslubida.
 *
 * * Chapda — navigatsiya (viloyatlar, yoniq/jami va holatlar chizig'i);
 * * tepada — tanlangan viloyat ko'rsatkichlari, BOSILSA filtr bo'ladi;
 * * xona — karta: onlayn ulushi chizig'i, xonaga job / yoqish, yig'ish;
 * * kompyuter — plitka: holat rangi va belgisi, IP, bizdagi yozuv.
 *
 * Sonlar — server GROUP BY (`devices/tree/`), plitkalar — bitta viloyat
 * (`devices/by-room/`, sahifasiz). Holat WebSocket bilan o'rnida yangilanadi
 * (`useBbaLive` `['bba-devices', ...]` keshini to'g'rilaydi).
 *
 * Plitka — oddiy `<button>` + `data-*`, stil bitta blokda, tooltip —
 * brauzerning `title` i: xonada yuzlab kompyuter bo'lganda MUI komponentlari
 * har plitkada render'ni sekinlashtirardi (`SeatGrid` bilan bir xil sabab).
 */
export default function BbaRoomsView({
  status, onStatusChange, region, onRegionChange, onOpen, canJobs, onRoomAction,
}: {
  status: string
  onStatusChange: (status: string) => void
  region: string | null
  onRegionChange: (key: string) => void
  onOpen: (id: Id) => void
  canJobs: boolean
  onRoomAction: (action: RoomAction, devices: ApiRecord[], roomName: string) => void
}) {
  const [search, setSearch] = useState('')
  const [linked, setLinked] = useState<LinkedFilter>('all')
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())

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
  const all: ApiRecord[] = devices?.results || []

  // Ko'rsatkichlar — tanlangan viloyat, JONLI ro'yxatdan (WebSocket uni yangilaydi).
  const stats = useMemo(() => {
    const result: Record<string, number> = { total: all.length, unlinked: 0 }
    for (const device of all) {
      result[device.status] = (result[device.status] || 0) + 1
      if (!device.computer_label) result.unlinked += 1
    }
    return result
  }, [all])

  const rooms = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const byRoom = new Map<string, ApiRecord[]>()
    for (const device of all) {
      if (status !== 'all' && device.status !== status) continue
      if (linked === 'unlinked' && device.computer_label) continue
      if (needle && ![device.name, device.hostname, device.primary_mac, device.primary_ip, device.computer_label]
        .some((value) => String(value || '').toLowerCase().includes(needle))) continue
      const key = String(device.room ?? 'none')
      if (!byRoom.has(key)) byRoom.set(key, [])
      byRoom.get(key)!.push(device)
    }
    return (selected?.rooms || [])
      .map((room: ApiRecord) => ({ key: String(room.id ?? 'none'), room, devices: byRoom.get(String(room.id ?? 'none')) || [] }))
      .filter((item: { devices: ApiRecord[] }) => item.devices.length > 0)
  }, [all, selected, status, linked, search])

  const toggleRoom = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  if (treeLoading) return <LinearProgress />
  if (!regions.length) {
    return <Alert severity="info">Kompyuterlar hali yo‘q — Console bilan sinxronlanmagan yoki sizga hudud bog‘lanmagan.</Alert>
  }

  const filtered = status !== 'all' || linked !== 'all' || Boolean(search.trim())

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '300px minmax(0, 1fr)' }, gap: 3, alignItems: 'start' }}>
      <Box
        component="nav"
        aria-label="Viloyatlar"
        sx={(theme) => ({
          ...navStyles(theme),
          position: { md: 'sticky' },
          top: { md: 16 },
          maxHeight: { md: 'calc(100vh - 140px)' },
          overflowY: 'auto',
        })}
      >
        <Typography variant="overline" color="text.secondary" sx={{ px: 2, pt: 1, display: 'block', fontWeight: 700 }}>
          Viloyatlar · {regions.length}
        </Typography>
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
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }} sx={{ mb: 2 }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h5" fontWeight={600} noWrap>{selected.name}</Typography>
              <Typography variant="body2" color="text.secondary">
                {selected.region_name ? `${selected.region_name} · ` : ''}
                {selected.rooms.length} ta xona
              </Typography>
            </Box>
            <TextField
              size="small"
              placeholder="Kompyuter, IP, MAC…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: '100%', sm: 280 }, '& .MuiOutlinedInput-root': { borderRadius: 999, bgcolor: 'm3.surfaceContainerHigh' } }}
              slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
            />
          </Stack>
        )}

        <Box sx={statStyles}>
          <StatCard
            icon={DevicesIcon} tone="primary" value={stats.total} label="Jami"
            active={status === 'all' && linked === 'all'}
            onClick={() => { onStatusChange('all'); setLinked('all') }}
          />
          <StatCard
            icon={OnlineIcon} tone="success" value={stats.online || 0} label={BBA_STATUS_LABEL.online}
            active={status === 'online'} onClick={() => onStatusChange(status === 'online' ? 'all' : 'online')}
          />
          <StatCard
            icon={OffIcon} tone="neutral" value={stats.offline_graceful || 0} label={BBA_STATUS_LABEL.offline_graceful}
            active={status === 'offline_graceful'}
            onClick={() => onStatusChange(status === 'offline_graceful' ? 'all' : 'offline_graceful')}
          />
          <StatCard
            icon={LinkOffIcon} tone="error" value={stats.offline_unexpected || 0} label={BBA_STATUS_LABEL.offline_unexpected}
            active={status === 'offline_unexpected'}
            onClick={() => onStatusChange(status === 'offline_unexpected' ? 'all' : 'offline_unexpected')}
          />
          <StatCard
            icon={AddLinkIcon} tone="warning" value={stats.unlinked} label="Ro‘yxatda yo‘q"
            active={linked === 'unlinked'} onClick={() => setLinked(linked === 'unlinked' ? 'all' : 'unlinked')}
          />
        </Box>

        {isLoading && <LinearProgress sx={{ my: 1, borderRadius: 1 }} />}
        {devices?.truncated && (
          <Alert severity="warning" sx={{ mb: 1.5 }}>Hududda kompyuter juda ko‘p — birinchi 3000 tasi ko‘rsatilmoqda.</Alert>
        )}
        {!isLoading && !rooms.length && (
          <Alert severity="info" sx={{ borderRadius: '16px' }}>
            {filtered ? 'Tanlangan filtrga mos kompyuter yo‘q.' : 'Bu viloyatda kompyuter yo‘q.'}
          </Alert>
        )}
        <Box sx={roomStyles}>
          {rooms.map(({ key, room, devices: list }: { key: string; room: ApiRecord; devices: ApiRecord[] }) => (
            <RoomCard
              key={key}
              roomKey={key}
              room={room}
              devices={list}
              collapsed={collapsed.has(key)}
              canJobs={canJobs}
              onToggle={toggleRoom}
              onOpen={onOpen}
              onAction={onRoomAction}
            />
          ))}
        </Box>
      </Box>
    </Box>
  )
}

type Tone = 'primary' | 'success' | 'error' | 'warning' | 'neutral'

function StatCard({
  icon: Glyph, tone, value, label, active, onClick,
}: { icon: ComponentType<SvgIconProps>; tone: Tone; value: number; label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className="stat" data-tone={tone} data-active={active || undefined} onClick={onClick} aria-pressed={active}>
      <span className="stat-icon"><Glyph fontSize="small" /></span>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </button>
  )
}

function RegionItem({ region, active, onSelect }: { region: ApiRecord; active: boolean; onSelect: (key: string) => void }) {
  const total = region.total || 1
  return (
    <button
      type="button"
      className="nav-item"
      data-active={active || undefined}
      aria-current={active ? 'true' : undefined}
      onClick={() => onSelect(regionKey(region.id))}
    >
      <span className="nav-avatar">{initials(region.name) || '?'}</span>
      <span className="nav-text">
        <span className="nav-head">
          <span className="nav-name">{region.name}</span>
          <span className="nav-badge" title="Yoniq / jami">{region.by_status.online}/{region.total}</span>
        </span>
        <span className="nav-sub">
          {[region.region_name, `${region.rooms.length} xona`].filter(Boolean).join(' · ')}
        </span>
        <span className="nav-bar" aria-hidden>
          {STATUSES.map((status) => (
            region.by_status[status]
              ? <span key={status} data-status={status} style={{ width: `${(region.by_status[status] / total) * 100}%` }} />
              : null
          ))}
        </span>
      </span>
    </button>
  )
}

const RoomCard = memo(function RoomCard({
  roomKey, room, devices, collapsed, canJobs, onToggle, onOpen, onAction,
}: {
  roomKey: string
  room: ApiRecord
  devices: ApiRecord[]
  collapsed: boolean
  canJobs: boolean
  onToggle: (key: string) => void
  onOpen: (id: Id) => void
  onAction: (action: RoomAction, devices: ApiRecord[], roomName: string) => void
}) {
  const counts = useMemo(() => {
    const result: Record<string, number> = {}
    for (const device of devices) result[device.status] = (result[device.status] || 0) + 1
    return result
  }, [devices])
  const offline = devices.filter((device) => device.status !== 'online' && !device.revoked_at)
  const online = counts.online || 0
  return (
    <Box component="section" className="room" data-collapsed={collapsed || undefined}>
      <Stack direction="row" spacing={1.5} alignItems="center" className="room-head">
        <Avatar variant="rounded" sx={{ width: 40, height: 40, borderRadius: '12px', bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer' }}>
          <MeetingRoomIcon />
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={650} noWrap>{room.name}</Typography>
          <Typography variant="caption" color="text.secondary" component="div" className="room-counts">
            <span>{devices.length} ta kompyuter</span>
            {online > 0 && <span data-status="online">{online} yoniq</span>}
            {counts.offline_unexpected ? <span data-status="offline_unexpected">{counts.offline_unexpected} aloqa uzilgan</span> : null}
            {counts.offline_graceful ? <span>{counts.offline_graceful} o‘chirilgan</span> : null}
          </Typography>
        </Box>
        {canJobs && (
          <>
            <Tooltip title="Xonadagi kompyuterlarga job yuborish">
              <IconButton size="small" aria-label="Xonaga job yuborish" onClick={() => onAction('job', devices, room.name)}>
                <TerminalIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title={offline.length ? `O‘chiq ${offline.length} ta kompyuterni yoqish` : 'Hammasi yoniq'}>
              <span>
                <IconButton
                  size="small" color="success" aria-label="Xonani yoqish" disabled={!offline.length}
                  onClick={() => onAction('wake', offline, room.name)}
                >
                  <PowerIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </>
        )}
        <Tooltip title={collapsed ? 'Ochish' : 'Yig‘ish'}>
          <IconButton
            size="small" aria-label={collapsed ? 'Xonani ochish' : 'Xonani yig‘ish'} aria-expanded={!collapsed}
            onClick={() => onToggle(roomKey)}
            sx={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform 150ms' }}
          >
            <ExpandIcon />
          </IconButton>
        </Tooltip>
      </Stack>
      <div className="room-bar" role="img" aria-label={`${online} / ${devices.length} yoniq`}>
        {STATUSES.map((status) => (
          counts[status]
            ? <span key={status} data-status={status} style={{ width: `${(counts[status] / devices.length) * 100}%` }} />
            : null
        ))}
      </div>
      {!collapsed && (
        <div className="tiles">
          {devices.map((device) => <Tile key={device.id} device={device} onOpen={onOpen} />)}
        </div>
      )}
    </Box>
  )
})

const Tile = memo(function Tile({ device, onOpen }: { device: ApiRecord; onOpen: (id: Id) => void }) {
  const status = device.revoked_at ? 'revoked' : device.status
  const label = device.revoked_at ? 'Chiqarilgan' : BBA_STATUS_LABEL[device.status] || device.status
  const title = [
    device.name,
    device.hostname && device.hostname !== device.name ? `Windows: ${device.hostname}` : '',
    `${label}${device.status_changed_at ? ` · ${fromNow(device.status_changed_at)}` : ''}`,
    device.last_seen_at ? `Oxirgi aloqa: ${fromNow(device.last_seen_at)}` : '',
    device.primary_ip ? `IP: ${device.primary_ip}` : '',
    device.primary_mac ? `MAC: ${device.primary_mac}` : '',
    device.computer_label ? `Bizda: ${device.computer_label}` : 'Bizning ro‘yxatda yo‘q',
  ].filter(Boolean).join('\n')
  return (
    <button
      type="button"
      className="tile"
      data-status={status}
      data-linked={device.computer_label ? 'yes' : 'no'}
      title={title}
      onClick={() => onOpen(device.id)}
    >
      <span className="tile-top">
        <span className="tile-icon">
          <svg viewBox="0 0 24 24" aria-hidden><path d={DESKTOP_PATH} /></svg>
        </span>
        <span className="tile-pill"><i aria-hidden />{label}</span>
      </span>
      <span className="tile-name">{device.name}</span>
      <span className="tile-ip">{device.primary_ip || '—'}</span>
      <span className="tile-foot">{device.computer_label || 'Ro‘yxatda yo‘q'}</span>
    </button>
  )
})

// --------------------------------------------------------------------------
// Stillar — har blok BITTA `sx` da, holatlar `data-*` selektorlari bilan.
// --------------------------------------------------------------------------
function byStatus(
  statuses: readonly string[], style: (status: string) => SystemStyleObject<Theme>, prefix: string,
): Record<string, SystemStyleObject<Theme>> {
  const result: Record<string, SystemStyleObject<Theme>> = {}
  for (const status of statuses) result[`${prefix}[data-status="${status}"]`] = style(status)
  return result
}

/** MD3 holat qatlami (state layer): hover 8%, bosish 12%. */
function stateLayer(color: string): SystemStyleObject<Theme> {
  return {
    position: 'relative',
    '&::after': {
      content: '""', position: 'absolute', inset: 0, borderRadius: 'inherit', pointerEvents: 'none',
      bgcolor: color, opacity: 0, transition: 'opacity 120ms',
    },
    '&:hover::after': { opacity: 0.08 },
    '&:active::after': { opacity: 0.12 },
  }
}

function navStyles(theme: Theme): SystemStyleObject<Theme> {
  const { m3 } = theme.palette
  return {
    bgcolor: m3.surfaceContainerLow,
    borderRadius: '28px',
    p: 1.5,
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
    '& .nav-item': {
      all: 'unset', boxSizing: 'border-box', cursor: 'pointer', display: 'flex', alignItems: 'center',
      gap: '12px', padding: '10px 14px', borderRadius: '28px', minHeight: 64,
      ...stateLayer(theme.palette.text.primary),
      '&:focus-visible': { outline: `2px solid ${theme.palette.primary.main}`, outlineOffset: 2 },
      '&[data-active]': { bgcolor: m3.secondaryContainer, color: m3.onSecondaryContainer },
      '&[data-active] .nav-avatar': { bgcolor: theme.palette.primary.main, color: theme.palette.primary.contrastText },
    },
    '& .nav-avatar': {
      width: 36, height: 36, borderRadius: '50%', flexShrink: 0, display: 'grid', placeItems: 'center',
      fontSize: 13, fontWeight: 700, bgcolor: m3.surfaceContainerHigh, color: theme.palette.text.secondary,
      transition: 'background-color 150ms',
    },
    '& .nav-text': { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '3px' },
    '& .nav-head': { display: 'flex', alignItems: 'center', gap: '8px' },
    '& .nav-name': {
      flex: 1, minWidth: 0, fontWeight: 600, fontSize: 14,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .nav-badge': {
      fontSize: 12, fontWeight: 700, padding: '1px 8px', borderRadius: 999,
      bgcolor: alpha(theme.palette.success.main, 0.14), color: theme.palette.success.dark,
    },
    '& .nav-sub': {
      fontSize: 12, color: theme.palette.text.secondary,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .nav-bar': {
      display: 'flex', height: 4, borderRadius: 2, overflow: 'hidden', bgcolor: theme.palette.action.selected,
      '& > span': { height: '100%' },
      ...byStatus(STATUSES, (status) => ({ bgcolor: toneOf(theme, status) }), '& > span'),
    },
  }
}

function statStyles(theme: Theme): SystemStyleObject<Theme> {
  const tones: Record<Tone, string> = {
    primary: theme.palette.primary.main,
    success: theme.palette.success.main,
    error: theme.palette.error.main,
    warning: theme.palette.warning.main,
    neutral: theme.palette.text.secondary,
  }
  const toneRules: Record<string, SystemStyleObject<Theme>> = {}
  for (const [tone, color] of Object.entries(tones)) {
    toneRules[`& .stat[data-tone="${tone}"] .stat-icon`] = { bgcolor: alpha(color, 0.14), color }
    toneRules[`& .stat[data-tone="${tone}"][data-active]`] = { borderColor: color, bgcolor: alpha(color, 0.08) }
    toneRules[`& .stat[data-tone="${tone}"][data-active] .stat-value`] = { color }
  }
  return {
    display: 'grid', gap: 1.5, mb: 2.5,
    gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(3, minmax(0, 1fr))', lg: 'repeat(5, minmax(0, 1fr))' },
    '& .stat': {
      all: 'unset', boxSizing: 'border-box', cursor: 'pointer', display: 'grid',
      gridTemplateColumns: 'auto 1fr', gridTemplateRows: 'auto auto', columnGap: '12px', alignItems: 'center',
      padding: '14px 16px', borderRadius: '20px', border: '1.5px solid transparent',
      bgcolor: theme.palette.m3.surfaceContainerLow,
      transition: 'border-color 150ms, background-color 150ms',
      ...stateLayer(theme.palette.text.primary),
      '&:focus-visible': { outline: `2px solid ${theme.palette.primary.main}`, outlineOffset: 2 },
    },
    '& .stat-icon': {
      gridRow: 'span 2', width: 40, height: 40, borderRadius: '12px', display: 'grid', placeItems: 'center',
    },
    '& .stat-value': { fontSize: 24, fontWeight: 700, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' },
    '& .stat-label': { fontSize: 12.5, color: theme.palette.text.secondary },
    ...toneRules,
  }
}

function roomStyles(theme: Theme): SystemStyleObject<Theme> {
  const { m3 } = theme.palette
  const tile = (status: string): SystemStyleObject<Theme> => {
    const color = toneOf(theme, status)
    const live = status === 'online'
    return {
      borderColor: alpha(color, live ? 0.45 : 0.22),
      '& .tile-icon': { bgcolor: alpha(color, live ? 0.16 : 0.08), color },
      '& .tile-pill': { color, bgcolor: alpha(color, 0.1) },
      '& .tile-pill i': {
        bgcolor: color,
        ...(live ? { animation: 'bbaPulse 2s ease-out infinite' } : {}),
      },
    }
  }
  return {
    display: 'flex', flexDirection: 'column', gap: 2,
    '@keyframes bbaPulse': {
      '0%': { boxShadow: `0 0 0 0 ${alpha(theme.palette.success.main, 0.55)}` },
      '70%': { boxShadow: `0 0 0 6px ${alpha(theme.palette.success.main, 0)}` },
      '100%': { boxShadow: `0 0 0 0 ${alpha(theme.palette.success.main, 0)}` },
    },
    '& .room': {
      bgcolor: m3.surfaceContainerLow, borderRadius: '24px', p: 2,
      // Ekrandan tashqaridagi xona chizilmaydi (viloyatda yuzlab xona).
      contentVisibility: 'auto', containIntrinsicSize: 'auto 220px',
    },
    '& .room-counts': {
      display: 'flex', gap: '10px', flexWrap: 'wrap',
      '& [data-status="online"]': { color: theme.palette.success.main, fontWeight: 600 },
      '& [data-status="offline_unexpected"]': { color: theme.palette.error.main, fontWeight: 600 },
    },
    '& .room-bar': {
      display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', my: 1.5,
      bgcolor: theme.palette.action.selected,
      '& > span': { height: '100%', transition: 'width 300ms' },
      ...byStatus(STATUSES, (status) => ({ bgcolor: toneOf(theme, status) }), '& > span'),
    },
    '& .room[data-collapsed] .room-bar': { mb: 0 },
    '& .tiles': {
      display: 'grid', gap: '10px', gridTemplateColumns: 'repeat(auto-fill, minmax(168px, 1fr))',
    },
    '& .tile': {
      all: 'unset', boxSizing: 'border-box', cursor: 'pointer', display: 'flex', flexDirection: 'column',
      gap: '4px', padding: '12px', borderRadius: '16px', border: '1px solid', minWidth: 0,
      bgcolor: theme.palette.background.paper,
      transition: 'box-shadow 150ms, transform 150ms, border-color 150ms',
      ...stateLayer(theme.palette.primary.main),
      '&:hover': { boxShadow: theme.shadows[3], transform: 'translateY(-2px)' },
      '&:active': { transform: 'none', boxShadow: theme.shadows[1] },
      '&:focus-visible': { outline: `2px solid ${theme.palette.primary.main}`, outlineOffset: 2 },
      ...byStatus(['online', 'offline_graceful', 'offline_unexpected', 'unknown', 'revoked'], tile, '&'),
    },
    '& .tile-top': { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', mb: '4px' },
    '& .tile-icon': {
      width: 36, height: 36, borderRadius: '12px', display: 'grid', placeItems: 'center',
      '& svg': { width: 20, height: 20, fill: 'currentColor' },
    },
    '& .tile-pill': {
      display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: 11, fontWeight: 700,
      padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap',
      '& i': { width: 7, height: 7, borderRadius: '50%', flexShrink: 0 },
    },
    '& .tile-name': {
      fontWeight: 650, fontSize: 14, color: theme.palette.text.primary,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .tile-ip': {
      fontFamily: 'monospace', fontSize: 12, color: theme.palette.text.secondary,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .tile-foot': {
      mt: '4px', pt: '6px', borderTop: `1px dashed ${theme.palette.divider}`, fontSize: 11.5,
      color: theme.palette.info.main, fontWeight: 600,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    },
    '& .tile[data-linked="no"] .tile-foot': { color: theme.palette.warning.dark, fontWeight: 500 },
  }
}
