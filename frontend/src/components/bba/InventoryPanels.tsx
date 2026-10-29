import { useMemo, useState } from 'react'
import {
  Box, Button, Chip, IconButton, InputAdornment, Stack, TextField, Tooltip, Typography,
} from '@mui/material'
import CopyIcon from '@mui/icons-material/ContentCopyOutlined'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import AddIcon from '@mui/icons-material/AddOutlined'

import { useCopy } from '../data/DetailFields'
import { formatBytes, isPlaceholderId } from './common'
import type { ReactNode } from 'react'
import type { ApiRecord } from '../../types/api'

/**
 * Console inventory snapshot'ining bo'limlari (`GET /devices/{id}/inventory`).
 * Maydon nomlari Console'niki: `Hardware`/`NetworkConfig` ichi snake_case.
 * Eski agentda (< 0.1.96) `Hardware.ids` yo'q, qurilmalar esa son bilan.
 */

type Row = [ReactNode, ReactNode, { mono?: boolean; copy?: string; badge?: ReactNode }?]

export function KeyValueTable({ rows, empty }: { rows: Row[]; empty: ReactNode }) {
  const copy = useCopy()
  if (!rows.length) return <Empty>{empty}</Empty>
  return (
    <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden' }}>
      {rows.map(([label, value, options], index) => (
        <Stack
          key={index}
          direction="row"
          spacing={1.5}
          alignItems="center"
          sx={{ px: 2, py: 1, minHeight: 44, borderTop: index ? 1 : 0, borderColor: 'divider' }}
        >
          <Typography variant="caption" color="text.secondary" sx={{ width: 150, flexShrink: 0 }}>
            {label}
          </Typography>
          <Typography
            component="div"
            variant="body2"
            sx={{
              flex: 1, minWidth: 0, wordBreak: 'break-word',
              fontFamily: options?.mono ? 'monospace' : undefined,
              fontSize: options?.mono ? 12.5 : undefined,
            }}
          >
            {value}
            {options?.badge}
          </Typography>
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
    <Box sx={{ p: 3, textAlign: 'center', bgcolor: 'background.paper', borderRadius: '16px' }}>
      <Typography variant="body2" color="text.secondary">{children}</Typography>
    </Box>
  )
}

const NO_INVENTORY = 'Inventory hali yig‘ilmagan — «Yangilash» ni bosing'

export function HardwarePanel({ hw }: { hw: ApiRecord | null | undefined }) {
  const rows = useMemo((): Row[] => {
    if (!hw) return []
    const result: Row[] = []
    if (hw.cpu) result.push(['Protsessor', hw.cpu])
    if (hw.motherboard) result.push(['Ona plata', hw.motherboard])
    const gpus: ApiRecord[] = hw.gpus || []
    gpus.forEach((gpu, i) => result.push([
      gpus.length > 1 ? `Videokarta ${i + 1}` : 'Videokarta',
      [gpu.name, formatBytes(gpu.vram_bytes)].filter(Boolean).join(', '),
    ]))
    if (hw.ram_total_bytes) {
      const modules: ApiRecord[] = hw.ram_modules || []
      const first = modules[0]
      const detail = first
        ? ` (${modules.length}×${formatBytes(first.capacity_bytes)}${first.speed_mhz ? ` ${first.speed_mhz} MHz` : ''}` +
          `${first.manufacturer ? ` ${String(first.manufacturer).trim()}` : ''})`
        : ''
      result.push(['Operativ xotira', `${formatBytes(hw.ram_total_bytes)}${detail}`])
    }
    const disks: ApiRecord[] = hw.storage || []
    disks.forEach((disk, i) => {
      const external = String(disk.bus || '').toUpperCase() === 'USB'
      result.push([
        external ? `Tashqi disk ${i + 1}` : `Disk ${i + 1}`,
        [disk.media_type && disk.media_type !== 'Unspecified' ? disk.media_type : null, disk.model, formatBytes(disk.size_bytes)]
          .filter(Boolean).join(', '),
      ])
    })
    const lists: [string, string][] = [
      ['network_disks', 'Tarmoq diski'], ['monitors', 'Monitor'], ['keyboards', 'Klaviatura'],
      ['mice', 'Sichqoncha'], ['cameras', 'Kamera'], ['headsets', 'Naushnik'], ['audio_devices', 'Audio'],
    ]
    for (const [key, label] of lists) {
      const value = hw[key]
      if (Array.isArray(value)) {
        value.forEach((item, i) => result.push([value.length > 1 ? `${label} ${i + 1}` : label, String(item)]))
      } else if (typeof value === 'number') {
        // Eski agent: faqat soni (-1 — aniqlanmadi).
        result.push([label, value < 0 ? 'noma’lum' : `${value} ta`])
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
    const add = (label: string, value: unknown, extra?: ReactNode) => {
      if (!value) return
      const text = String(value)
      result.push([label, text, {
        mono: true,
        copy: text,
        badge: isPlaceholderId(text)
          ? (
            <Tooltip title="Firmware to‘ldiruvchisi — ko‘p mashinada bir xil, identifikator emas">
              <Chip size="small" color="warning" variant="outlined" label="to‘ldiruvchi" sx={{ ml: 1, height: 20 }} />
            </Tooltip>
          )
          : extra,
      }])
    }
    add('System UUID', ids.system_uuid)
    add('Tizim seriyasi', ids.system_serial)
    add('BIOS seriyasi', ids.bios_serial)
    add('Ona plata seriyasi', ids.baseboard_serial)
    add('TPM EK (SHA-256)', ids.tpm_ek_hash)
    add('Windows MachineGuid', ids.machine_guid)
    add('CPU ID', ids.cpu_id, (
      <Tooltip title="Bir xil modeldagi barcha protsessorlarda bir xil — identifikatsiya uchun yaroqsiz">
        <Chip size="small" variant="outlined" label="yagona emas" sx={{ ml: 1, height: 20 }} />
      </Tooltip>
    ))
    ;(hw.storage || []).forEach((disk: ApiRecord, i: number) => add(`Disk ${i + 1} seriyasi`, disk.serial))
    ;(hw.ram_modules || []).forEach((module: ApiRecord, i: number) => add(`RAM ${i + 1} seriyasi`, module.serial_number))
    ;(ids.network_adapters || []).forEach((nic: ApiRecord, i: number) => add(`Tarmoq ${i + 1} MAC`, nic.mac))
    ;(ids.monitors || []).forEach((monitor: ApiRecord, i: number) => add(`Monitor ${i + 1} seriyasi`, monitor.serial))
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
        return (
          <Box key={`${nic.name}-${index}`} sx={{ bgcolor: 'background.paper', borderRadius: '16px', px: 2, py: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography fontWeight={600} sx={{ flex: 1, minWidth: 0 }} noWrap>{nic.name || '—'}</Typography>
              {nic.enabled === false
                ? <Chip size="small" label="O‘chirilgan" />
                : <Chip size="small" variant="outlined" label={nic.dhcp ? 'DHCP' : 'Statik'} />}
              {mac && physical.has(mac) && <Chip size="small" variant="outlined" color="primary" label="Jismoniy" />}
              {mac && mac === normalizeMac(device.primary_mac) && (
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
        )
      })}
    </Stack>
  )
}

export function SoftwarePanel({ software, hasInventory }: { software: ApiRecord[] | undefined; hasInventory: boolean }) {
  const [query, setQuery] = useState('')
  const items = useMemo(() => {
    const list = [...(software || [])].sort((a, b) => String(a.name).localeCompare(String(b.name)))
    const needle = query.trim().toLowerCase()
    return needle
      ? list.filter((item) => `${item.name} ${item.publisher || ''}`.toLowerCase().includes(needle))
      : list
  }, [software, query])
  if (!software?.length) return <Empty>{hasInventory ? 'O‘rnatilgan dasturlar ro‘yxati yo‘q' : NO_INVENTORY}</Empty>
  return (
    <Stack spacing={1}>
      <TextField
        size="small"
        placeholder={`${software.length} ta dastur ichidan qidirish…`}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
      />
      <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden' }}>
        {items.map((item, index) => (
          <Stack
            key={`${item.name}-${index}`}
            direction="row"
            spacing={1}
            alignItems="baseline"
            sx={{ px: 2, py: 0.75, borderTop: index ? 1 : 0, borderColor: 'divider' }}
          >
            <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }} noWrap title={item.name}>{item.name}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: 160 }} title={item.version}>
              {item.version}
            </Typography>
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
        <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden' }}>
          {apps.map((app, index) => (
            <Stack
              key={`${app.name}-${index}`}
              direction="row"
              spacing={1}
              alignItems="center"
              sx={{ px: 2, py: 1, borderTop: index ? 1 : 0, borderColor: 'divider' }}
            >
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
                <Button size="small" color="warning" disabled={busy} onClick={() => onToggle(app)}>
                  {app.enabled ? 'O‘chirish' : 'Yoqish'}
                </Button>
              )}
            </Stack>
          ))}
        </Box>
      )}
      {canJobs && (
        <Box>
          <Button size="small" startIcon={<AddIcon />} onClick={onAdd} disabled={busy}>
            Avtostartga dastur qo‘shish
          </Button>
        </Box>
      )}
    </Stack>
  )
}
