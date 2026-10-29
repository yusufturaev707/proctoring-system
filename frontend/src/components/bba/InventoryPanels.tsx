import { useMemo, useState } from 'react'
import {
  Alert, Avatar, Box, Button, Chip, IconButton, InputAdornment, Stack, TextField, ToggleButton,
  ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import CopyIcon from '@mui/icons-material/ContentCopyOutlined'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import AddIcon from '@mui/icons-material/AddOutlined'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'

import { useCopy } from '../data/DetailFields'
import { formatBytes, isPlaceholderId } from './common'
import { adapterIcon, AppIcon, appKind, HARDWARE_ICON, ID_ICON } from './icons'
import type { ComponentType, ReactNode } from 'react'
import type { SvgIconProps } from '@mui/material'
import type { ApiRecord } from '../../types/api'

/**
 * Console inventory snapshot'ining bo'limlari (`GET /devices/{id}/inventory`).
 * Maydon nomlari Console'niki: `Hardware`/`NetworkConfig` ichi snake_case.
 * Eski agentda (< 0.1.96) `Hardware.ids` yo'q, qurilmalar esa son bilan.
 */

type Icon = ComponentType<SvgIconProps>
interface RowOptions {
  mono?: boolean
  copy?: string
  badge?: ReactNode
  icon?: Icon
}
type Row = [ReactNode, ReactNode, RowOptions?]

/** MD3 ro'yxat elementi uchun 40 px tonal ikonka konteyneri. */
function LeadingIcon({ icon: Glyph }: { icon: Icon }) {
  return (
    <Avatar
      variant="rounded"
      sx={{ width: 36, height: 36, borderRadius: '10px', bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer' }}
    >
      <Glyph sx={{ fontSize: 20 }} />
    </Avatar>
  )
}

const surface = { bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden' } as const

export function KeyValueTable({ rows, empty }: { rows: Row[]; empty: ReactNode }) {
  const copy = useCopy()
  if (!rows.length) return <Empty>{empty}</Empty>
  return (
    <Box sx={surface}>
      {rows.map(([label, value, options], index) => (
        <Stack
          key={index}
          direction="row"
          spacing={1.5}
          alignItems="center"
          sx={{ px: 2, py: 1, minHeight: 56, borderTop: index ? 1 : 0, borderColor: 'divider' }}
        >
          {options?.icon && <LeadingIcon icon={options.icon} />}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" display="block">{label}</Typography>
            <Typography
              component="div"
              variant="body2"
              sx={{
                wordBreak: 'break-word',
                fontFamily: options?.mono ? 'monospace' : undefined,
                fontSize: options?.mono ? 12.5 : undefined,
              }}
            >
              {value}
              {options?.badge}
            </Typography>
          </Box>
          {options?.copy && (
            <Tooltip title="Nusxalash">
              <IconButton size="small" onClick={() => copy(options.copy!)} aria-label="Nusxalash">
                <CopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Stack>
      ))}
    </Box>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ p: 3, textAlign: 'center', ...surface }}>
      <Typography variant="body2" color="text.secondary">{children}</Typography>
    </Box>
  )
}

const NO_INVENTORY = 'Inventory hali yig‘ilmagan — «Inventory’ni yangilash» ni bosing'

export function HardwarePanel({ hw }: { hw: ApiRecord | null | undefined }) {
  const rows = useMemo((): Row[] => {
    if (!hw) return []
    const result: Row[] = []
    if (hw.cpu) result.push(['Protsessor', hw.cpu, { icon: HARDWARE_ICON.cpu }])
    if (hw.motherboard) result.push(['Ona plata', hw.motherboard, { icon: HARDWARE_ICON.motherboard }])
    const gpus: ApiRecord[] = hw.gpus || []
    gpus.forEach((gpu, i) => result.push([
      gpus.length > 1 ? `Videokarta ${i + 1}` : 'Videokarta',
      [gpu.name, formatBytes(gpu.vram_bytes)].filter(Boolean).join(', '),
      { icon: HARDWARE_ICON.gpu },
    ]))
    if (hw.ram_total_bytes) {
      const modules: ApiRecord[] = hw.ram_modules || []
      const first = modules[0]
      const detail = first
        ? ` (${modules.length}×${formatBytes(first.capacity_bytes)}${first.speed_mhz ? ` ${first.speed_mhz} MHz` : ''}` +
          `${first.manufacturer ? ` ${String(first.manufacturer).trim()}` : ''})`
        : ''
      result.push(['Operativ xotira', `${formatBytes(hw.ram_total_bytes)}${detail}`, { icon: HARDWARE_ICON.ram }])
    }
    const disks: ApiRecord[] = hw.storage || []
    disks.forEach((disk, i) => {
      const external = String(disk.bus || '').toUpperCase() === 'USB'
      result.push([
        external ? `Tashqi disk ${i + 1}` : `Disk ${i + 1}`,
        [disk.media_type && disk.media_type !== 'Unspecified' ? disk.media_type : null, disk.model, formatBytes(disk.size_bytes)]
          .filter(Boolean).join(', '),
        { icon: external ? HARDWARE_ICON.external : HARDWARE_ICON.disk },
      ])
    })
    const lists: [string, string][] = [
      ['network_disks', 'Tarmoq diski'], ['monitors', 'Monitor'], ['keyboards', 'Klaviatura'],
      ['mice', 'Sichqoncha'], ['cameras', 'Kamera'], ['headsets', 'Naushnik'], ['audio_devices', 'Audio'],
    ]
    for (const [key, label] of lists) {
      const value = hw[key]
      const icon = HARDWARE_ICON[key]
      if (Array.isArray(value)) {
        value.forEach((item, i) => result.push([value.length > 1 ? `${label} ${i + 1}` : label, String(item), { icon }]))
      } else if (typeof value === 'number') {
        // Eski agent: faqat soni (-1 — aniqlanmadi).
        result.push([label, value < 0 ? 'noma’lum' : `${value} ta`, { icon }])
      }
    }
    return result
  }, [hw])
  return <KeyValueTable rows={rows} empty={hw ? 'Hardware ma’lumoti yo‘q (eski agent)' : NO_INVENTORY} />
}

export function HardwareIdsPanel({ hw }: { hw: ApiRecord | null | undefined }) {
  const rows = useMemo((): Row[] => {
    const ids = hw?.ids
    if (!ids) return []
    const result: Row[] = []
    const add = (label: string, value: unknown, icon: Icon, extra?: ReactNode) => {
      if (!value) return
      const text = String(value)
      result.push([label, text, {
        mono: true,
        copy: text,
        icon,
        badge: isPlaceholderId(text)
          ? (
            <Tooltip title="Firmware to‘ldiruvchisi — ko‘p mashinada bir xil, identifikator emas">
              <Chip size="small" color="warning" variant="outlined" label="to‘ldiruvchi" sx={{ ml: 1, height: 20 }} />
            </Tooltip>
          )
          : extra,
      }])
    }
    add('System UUID', ids.system_uuid, ID_ICON.uuid)
    add('Tizim seriyasi', ids.system_serial, ID_ICON.serial)
    add('BIOS seriyasi', ids.bios_serial, ID_ICON.serial)
    add('Ona plata seriyasi', ids.baseboard_serial, ID_ICON.serial)
    add('TPM EK (SHA-256)', ids.tpm_ek_hash, ID_ICON.tpm)
    add('Windows MachineGuid', ids.machine_guid, ID_ICON.windows)
    add('CPU ID', ids.cpu_id, ID_ICON.cpu, (
      <Tooltip title="Bir xil modeldagi barcha protsessorlarda bir xil — identifikatsiya uchun yaroqsiz">
        <Chip size="small" variant="outlined" label="yagona emas" sx={{ ml: 1, height: 20 }} />
      </Tooltip>
    ))
    ;(hw.storage || []).forEach((disk: ApiRecord, i: number) => add(`Disk ${i + 1} seriyasi`, disk.serial, ID_ICON.disk))
    ;(hw.ram_modules || []).forEach((module: ApiRecord, i: number) => add(`RAM ${i + 1} seriyasi`, module.serial_number, ID_ICON.ram))
    ;(ids.network_adapters || []).forEach((nic: ApiRecord, i: number) => add(`Tarmoq ${i + 1} MAC`, nic.mac, ID_ICON.nic))
    ;(ids.monitors || []).forEach((monitor: ApiRecord, i: number) => add(`Monitor ${i + 1} seriyasi`, monitor.serial, ID_ICON.monitor))
    return result
  }, [hw])
  return (
    <KeyValueTable
      rows={rows}
      empty={hw ? 'Hardware ID’lar yo‘q — agent 0.1.96 dan eski (Console uni avtomatik yangilaydi)' : NO_INVENTORY}
    />
  )
}

const normalizeMac = (value: unknown) => String(value || '').replace(/[^0-9a-f]/gi, '').toUpperCase()

export function NetworkPanel({ nics, device }: { nics: ApiRecord[] | undefined; device: ApiRecord }) {
  if (!nics?.length) return <Empty>{device.inventory ? 'Tarmoq adapterlari yo‘q' : NO_INVENTORY}</Empty>
  const ours = normalizeMac(device.computer_detail?.mac_address)
  const physical = new Set((device.macs || []).map(normalizeMac))
  return (
    <Stack spacing={1}>
      {nics.map((nic, index) => {
        const mac = normalizeMac(nic.mac)
        const kind = adapterIcon(nic.name)
        const active = Boolean(mac) && mac === normalizeMac(device.primary_mac)
        return (
          <Stack
            key={`${nic.name}-${index}`}
            direction="row"
            spacing={1.5}
            sx={{
              ...surface, px: 2, py: 1.5,
              outline: active ? 2 : 0, outlineColor: 'success.main', outlineStyle: 'solid',
              opacity: nic.enabled === false ? 0.6 : 1,
            }}
          >
            <Tooltip title={kind.label}><span><LeadingIcon icon={kind.icon} /></span></Tooltip>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography fontWeight={600} sx={{ flex: 1, minWidth: 0 }} noWrap title={nic.name}>{nic.name || '—'}</Typography>
                {nic.enabled === false
                  ? <Chip size="small" label="O‘chirilgan" />
                  : <Chip size="small" variant="outlined" label={nic.dhcp ? 'DHCP' : 'Statik'} />}
                {mac && physical.has(mac) && <Chip size="small" variant="outlined" color="primary" label="Jismoniy" />}
                {active && (
                  <Tooltip title="Shlyuzli faol adapter — client handshake’da shu MAC’ni yuboradi">
                    <Chip size="small" color="success" label="Faol" />
                  </Tooltip>
                )}
                {ours && mac === ours && <Chip size="small" color="info" label="Bizdagi MAC" />}
              </Stack>
              <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5, mt: 0.5 }}>{nic.mac || '—'}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ fontFamily: 'monospace', fontSize: 12.5 }}>
                {(nic.addrs || []).join(', ') || '—'}
              </Typography>
              {(nic.gateway || nic.dns?.length) && (
                <Typography variant="caption" color="text.secondary">
                  {nic.gateway ? `Shlyuz ${nic.gateway}` : ''}
                  {nic.gateway && nic.dns?.length ? ' · ' : ''}
                  {nic.dns?.length ? `DNS ${nic.dns.join(', ')}` : ''}
                </Typography>
              )}
            </Box>
          </Stack>
        )
      })}
    </Stack>
  )
}

export function SoftwarePanel({ software, hasInventory }: { software: ApiRecord[] | undefined; hasInventory: boolean }) {
  const [query, setQuery] = useState('')
  const [onlyRisk, setOnlyRisk] = useState(false)
  const list = useMemo(
    () => [...(software || [])]
      .map((item) => ({ item, kind: appKind(item.name) }))
      .sort((a, b) => Number(Boolean(b.kind?.risk)) - Number(Boolean(a.kind?.risk))
        || String(a.item.name).localeCompare(String(b.item.name))),
    [software],
  )
  const riskCount = list.filter(({ kind }) => kind?.risk).length
  const items = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return list.filter(({ item, kind }) => (
      (!onlyRisk || kind?.risk)
      && (!needle || `${item.name} ${item.publisher || ''} ${kind?.category || ''}`.toLowerCase().includes(needle))
    ))
  }, [list, query, onlyRisk])

  if (!software?.length) return <Empty>{hasInventory ? 'O‘rnatilgan dasturlar ro‘yxati yo‘q' : NO_INVENTORY}</Empty>
  return (
    <Stack spacing={1.5}>
      {riskCount > 0 && (
        <Alert severity="warning" icon={<WarningIcon />}>
          Imtihon kompyuterida bo‘lmasligi kerak bo‘lgan {riskCount} ta dastur bor (masofaviy boshqaruv,
          ekran yozish yoki o‘yin) — ular ro‘yxat boshida.
        </Alert>
      )}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField
          size="small"
          placeholder={`${software.length} ta dastur ichidan qidirish…`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          sx={{ flex: 1, '& .MuiOutlinedInput-root': { borderRadius: 999 } }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
        />
        {riskCount > 0 && (
          <ToggleButtonGroup size="small" exclusive value={onlyRisk ? 'risk' : 'all'} onChange={(_, value) => value && setOnlyRisk(value === 'risk')}>
            <ToggleButton value="all">Hammasi</ToggleButton>
            <ToggleButton value="risk">Xavfli · {riskCount}</ToggleButton>
          </ToggleButtonGroup>
        )}
      </Stack>
      <Box sx={surface}>
        {items.map(({ item, kind }, index) => (
          <Stack
            key={`${item.name}-${index}`}
            direction="row"
            spacing={1.5}
            alignItems="center"
            sx={{
              px: 2, py: 1, borderTop: index ? 1 : 0, borderColor: 'divider',
              bgcolor: kind?.risk ? (theme) => `${theme.palette.error.main}0D` : undefined,
            }}
          >
            <AppIcon name={item.name} />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="body2" fontWeight={500} noWrap title={item.name}>{item.name}</Typography>
              <Typography variant="caption" color="text.secondary" noWrap display="block">
                {[item.version, item.publisher, item.scope && String(item.scope).startsWith('user:')
                  ? `faqat ${String(item.scope).replace(/^user:/, '')} uchun` : '']
                  .filter(Boolean).join(' · ') || '—'}
              </Typography>
            </Box>
            {kind && (
              <Chip
                size="small"
                variant={kind.risk ? 'filled' : 'outlined'}
                color={kind.risk ? 'error' : 'default'}
                label={kind.category}
                sx={{ height: 22 }}
              />
            )}
          </Stack>
        ))}
        {!items.length && <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>Topilmadi</Typography>}
      </Box>
    </Stack>
  )
}

export function StartupPanel({
  apps, hasInventory, canJobs, busy, onToggle, onAdd,
}: {
  apps: ApiRecord[] | undefined
  hasInventory: boolean
  canJobs: boolean
  busy: boolean
  onToggle: (app: ApiRecord) => void
  onAdd: () => void
}) {
  return (
    <Stack spacing={1}>
      {!apps?.length ? (
        <Empty>{hasInventory ? 'Avtostartda dastur yo‘q' : NO_INVENTORY}</Empty>
      ) : (
        <Box sx={surface}>
          {apps.map((app, index) => {
            const kind = appKind(app.name)
            return (
              <Stack
                key={`${app.name}-${index}`}
                direction="row"
                spacing={1.5}
                alignItems="center"
                sx={{ px: 2, py: 1, borderTop: index ? 1 : 0, borderColor: 'divider', opacity: app.enabled ? 1 : 0.7 }}
              >
                <AppIcon name={app.name} />
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2" fontWeight={600} noWrap>{app.name}</Typography>
                    <Chip
                      size="small"
                      color={app.enabled ? 'success' : 'default'}
                      variant={app.enabled ? 'filled' : 'outlined'}
                      label={app.enabled ? 'Yoqilgan' : 'O‘chirilgan'}
                      sx={{ height: 20 }}
                    />
                    {kind?.risk && <Chip size="small" color="error" label={kind.category} sx={{ height: 20 }} />}
                  </Stack>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    noWrap
                    display="block"
                    title={app.command || app.path}
                    sx={{ fontFamily: 'monospace' }}
                  >
                    {[app.scope, app.command || app.path].filter(Boolean).join(' · ')}
                  </Typography>
                </Box>
                {canJobs && (
                  <Button size="small" color="warning" disabled={busy} onClick={() => onToggle(app)} sx={{ borderRadius: 999 }}>
                    {app.enabled ? 'O‘chirish' : 'Yoqish'}
                  </Button>
                )}
              </Stack>
            )
          })}
        </Box>
      )}
      {canJobs && (
        <Box>
          <Button size="small" startIcon={<AddIcon />} onClick={onAdd} disabled={busy} sx={{ borderRadius: 999 }}>
            Avtostartga dastur qo‘shish
          </Button>
        </Box>
      )}
    </Stack>
  )
}
