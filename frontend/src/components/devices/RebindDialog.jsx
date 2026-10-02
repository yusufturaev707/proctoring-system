import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, IconButton, InputAdornment,
  LinearProgress, List, ListItemButton, MenuItem, Stack, TextField, Tooltip, Typography,
  useMediaQuery, useTheme,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import ClearIcon from '@mui/icons-material/ClearOutlined'
import LinkIcon from '@mui/icons-material/LinkOutlined'
import CheckIcon from '@mui/icons-material/CheckCircle'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'

import { computers as computersApi } from '../../api/endpoints'
import { useDebounced } from '../data/useResource'
import { HeaderIcon } from '../data/DetailFields'
import { useAuth } from '../../context/AuthContext'
import { useRegionOptions, useZoneOptions, zonesOfRegion } from '../../pages/crud/shared'
import { computerLabel } from '../../utils/labels'

/** Bir so'rovda ko'rsatiladigan natija. Ko'prog'i - qidiruvni aniqlashtirish kerak. */
const PAGE = 50

/**
 * Qidiruv matni serverga qanday ketadi.
 *
 * MAC bazada kanonik shaklda (`2C:F0:...`, `normalize_mac`), server esa
 * `icontains` bilan qidiradi: `getmac` bergan `2c-f0-5d` hech narsa
 * topmasdi. MAC'ga o'xshagan matn shu shaklga keltiriladi; UUID va boshqa
 * matn o'zgarmaydi (UUID qidiruvi harf katta-kichikligiga qaramaydi).
 */
const toServerSearch = (text) => {
  const value = text.trim()
  return /^[0-9a-f]{2}([-:][0-9a-f]{1,2})+[-:]?$/i.test(value)
    ? value.replace(/-/g, ':').toUpperCase()
    : value
}

/**
 * Qurilmani boshqa kompyuterga biriktirish.
 *
 * Asosiy holat — mashina obrazi ko'chirilgan: `device_id` diskdagi fayl
 * bilan birga ko'chadi va handshake `mismatch` beradi. To'g'ri javob —
 * qurilmani client HAQIQATAN turgan kompyuterga o'tkazish.
 *
 * NIMA UCHUN QIDIRUV SERVERDA. Ilgari barcha kompyuterlar bitta ro'yxatda
 * edi (`useComputerOptions`): minglab yozuv orasidan "№12 · INV-001 —
 * Bino" yorliqlari bo'yicha qidirish kerak edi, MAC/IP/UUID bo'yicha esa
 * umuman topib bo'lmasdi — holbuki administrator aynan shularni biladi
 * (mashina ekranida yoki "Mashina aytgan" qiymatlarda). Endi viloyat ->
 * bino zanjiri va `search` (`number`, `inventory_code`, `machine_uuid`,
 * `ip_address`, `mac_address`) serverda, bitta sahifa bilan.
 *
 * Qidiruv qurilmaning HOZIRGI binosidan boshlanadi: odatda mashina o'sha
 * binoda, faqat boshqa stolda. Mashina o'zi aytgan UUID/MAC/IP chiplar
 * bo'lib turadi — bosilsa shu qiymat bo'yicha qidiriladi. Server viloyat
 * doirasini va hisobdan chiqarilgan mashinani o'zi ham tekshiradi.
 */
export default function RebindDialog({ device, loading, onSave, onClose }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const { user } = useAuth()
  const regionScoped = Boolean(user?.is_region_scoped)
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()

  const [region, setRegion] = useState(device.computer_region ?? '')
  const [zone, setZone] = useState(device.computer_zone ?? '')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const debounced = useDebounced(search)

  const zones = useMemo(
    () => (region ? zonesOfRegion(zoneOptions, region) : zoneOptions),
    [region, zoneOptions],
  )

  const params = useMemo(() => {
    const query = { page_size: PAGE, is_active: true, ordering: 'number' }
    if (zone) query.zone = zone
    else if (region) query.zone__region = region
    const text = toServerSearch(debounced)
    if (text) query.search = text
    return query
  }, [zone, region, debounced])

  const { data, isFetching, isError } = useQuery({
    queryKey: ['computers', 'rebind-search', params],
    queryFn: () => computersApi.list(params),
    // Harf yozilganda ro'yxat "yo'qolib-paydo bo'lmasin".
    placeholderData: keepPreviousData,
    staleTime: 15000,
  })
  const rows = data?.results || []
  const total = data?.count ?? rows.length

  const reported = [
    { key: 'uuid', label: 'UUID', value: device.reported_machine_uuid },
    { key: 'mac', label: 'MAC', value: device.reported_mac },
    { key: 'ip', label: 'IP', value: device.reported_lan_ip },
  ].filter((item) => item.value)

  // Mashina o'zi aytgan qiymat bo'yicha qidirish - bino filtri OLIB
  // tashlanadi: mashina boshqa binoga ko'chgan bo'lishi ham mumkin.
  const searchBy = (value) => {
    setZone('')
    if (!regionScoped) setRegion('')
    setSearch(value)
  }

  const canSave = Boolean(selected) && selected.id !== device.computer && !loading

  return (
    <Dialog
      open
      onClose={loading ? undefined : onClose}
      maxWidth="md"
      fullWidth
      fullScreen={fullScreen}
      slotProps={{ paper: { sx: { bgcolor: 'm3.surfaceContainerLow', borderRadius: fullScreen ? 0 : '28px' } } }}
    >
      {/* Sarlavha */}
      <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ px: 3, pt: 3, pb: 1.5 }}>
        <HeaderIcon><LinkIcon /></HeaderIcon>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h6" sx={{ lineHeight: 1.3 }}>Kompyuterga biriktirish</Typography>
          <Typography variant="body2" color="text.secondary">
            Qurilmani client aslida turgan kompyuterga o‘tkazing
          </Typography>
        </Box>
        <IconButton onClick={onClose} disabled={loading} aria-label="Yopish" sx={{ mt: -0.5, mr: -1 }}>
          <CloseIcon />
        </IconButton>
      </Stack>

      <DialogContent sx={{ pt: 0.5 }}>
        <Stack spacing={2}>
          {/* Qurilma: hozirgi biriktiruv va mashina o'zi aytgan qiymatlar. */}
          <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', p: 2 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 1, sm: 3 }}>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="caption" color="text.secondary">Hozirgi kompyuter</Typography>
                <Typography variant="subtitle2" noWrap>
                  {computerLabel(device.computer_number, device.computer_code) || '—'}
                </Typography>
                <Typography variant="caption" color="text.secondary" noWrap display="block">
                  {[device.region_name, device.zone_name].filter(Boolean).join(' · ') || '—'}
                </Typography>
              </Box>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">Qurilma ID</Typography>
                <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5, wordBreak: 'break-all' }}>
                  {device.device_id}
                </Typography>
              </Box>
            </Stack>
            {reported.length > 0 && (
              <>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5, mb: 0.75 }}>
                  Mashina o‘zi aytgan — bosing, shu bo‘yicha qidiriladi
                </Typography>
                <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                  {reported.map((item) => (
                    <Chip
                      key={item.key}
                      size="small"
                      variant="outlined"
                      icon={<SearchIcon />}
                      label={`${item.label}: ${item.value}`}
                      onClick={() => searchBy(item.value)}
                      sx={{ fontFamily: 'monospace', fontSize: 12, maxWidth: '100%' }}
                    />
                  ))}
                </Stack>
              </>
            )}
          </Box>

          {/* Filtrlar: viloyat -> bino, qidiruv. */}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
            {!regionScoped && (
              <TextField
                select
                size="small"
                label="Viloyat"
                value={region}
                onChange={(event) => {
                  setRegion(event.target.value)
                  setZone('')
                }}
                sx={{ minWidth: { sm: 180 } }}
              >
                <MenuItem value="">Barcha viloyatlar</MenuItem>
                {regionOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              select
              size="small"
              label="Bino"
              value={zone}
              onChange={(event) => setZone(event.target.value)}
              sx={{ minWidth: { sm: 220 } }}
            >
              <MenuItem value="">{region ? 'Viloyatdagi barcha binolar' : 'Barcha binolar'}</MenuItem>
              {zones.map((option) => (
                <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              autoFocus
              fullWidth
              label="Qidirish"
              placeholder="Raqam, inventar kodi, MAC, IP yoki UUID"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>
                  ),
                  endAdornment: search ? (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setSearch('')} aria-label="Tozalash">
                        <ClearIcon fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ) : null,
                },
              }}
            />
          </Stack>

          {/* Natijalar */}
          <Box
            sx={{
              bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden',
              border: 1, borderColor: 'divider',
            }}
          >
            <Box sx={{ height: 4 }}>{isFetching && <LinearProgress />}</Box>
            {isError ? (
              <Alert severity="error" sx={{ m: 2 }}>Kompyuterlarni yuklab bo‘lmadi</Alert>
            ) : rows.length === 0 && !isFetching ? (
              <Stack alignItems="center" spacing={1} sx={{ py: 6, color: 'text.secondary' }}>
                <ComputerIcon />
                <Typography variant="body2">Mos kompyuter topilmadi</Typography>
                <Typography variant="caption">Bino filtrini olib tashlab yoki boshqa qiymat bilan qidiring</Typography>
              </Stack>
            ) : (
              <List dense disablePadding sx={{ maxHeight: { xs: 'none', sm: 340 }, overflowY: 'auto' }}>
                {rows.map((row) => (
                  <ComputerRow
                    key={row.id}
                    row={row}
                    query={toServerSearch(debounced)}
                    current={row.id === device.computer}
                    selected={selected?.id === row.id}
                    onSelect={() => setSelected(row)}
                  />
                ))}
              </List>
            )}
          </Box>
          {total > rows.length && (
            <Typography variant="caption" color="text.secondary">
              {total} ta topildi, dastlabki {rows.length} tasi ko‘rsatilmoqda — qidiruvni aniqlashtiring
            </Typography>
          )}
        </Stack>
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2, gap: 1, bgcolor: 'm3.surfaceContainer', flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 0 }} noWrap>
          {selected
            ? <>Tanlandi: <strong>{selected.label || selected.inventory_code}</strong> · {selected.zone_name}</>
            : 'Ro‘yxatdan kompyuterni tanlang'}
        </Typography>
        <Button onClick={onClose} disabled={loading} sx={{ borderRadius: 999 }}>Bekor qilish</Button>
        <Button
          variant="contained"
          disableElevation
          startIcon={<LinkIcon />}
          disabled={!canSave}
          onClick={() => onSave(selected.id)}
          sx={{ borderRadius: 999 }}
        >
          Biriktirish
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function ComputerRow({ row, query, current, selected, onSelect }) {
  const ids = [
    { label: 'MAC', value: row.mac_address },
    { label: 'IP', value: row.ip_address },
    { label: 'UUID', value: row.machine_uuid },
  ]
  return (
    <ListItemButton
      selected={selected}
      disabled={current}
      onClick={onSelect}
      sx={{
        py: 1.25, px: 2, gap: 1.5, alignItems: 'flex-start',
        '& + &': { borderTop: 1, borderColor: 'divider' },
        '&.Mui-selected': { bgcolor: 'm3.primaryContainer' },
        '&.Mui-selected:hover': { bgcolor: 'm3.primaryContainer' },
      }}
    >
      <Box sx={{ pt: 0.25, color: selected ? 'primary.main' : 'text.secondary', display: 'flex' }}>
        {selected ? <CheckIcon /> : <ComputerIcon />}
      </Box>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle2" noWrap>
            <Highlight text={row.label || row.inventory_code} query={query} />
          </Typography>
          {current && <Chip size="small" label="Hozirgi" />}
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" noWrap>
          {[row.region_name, row.zone_name].filter(Boolean).join(' · ')}
        </Typography>
        <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.25 }}>
          {ids.map((item) => (
            <Tooltip key={item.label} title={item.value || ''} disableInteractive>
              <Typography
                variant="caption"
                sx={{ fontFamily: 'monospace', color: item.value ? 'text.primary' : 'text.disabled' }}
                noWrap
              >
                {item.label}{' '}
                {item.value ? <Highlight text={item.value} query={query} /> : '—'}
              </Typography>
            </Tooltip>
          ))}
        </Stack>
      </Box>
    </ListItemButton>
  )
}

/** Qidiruv matnini qalin + tonal fon bilan ko'rsatadi (katta-kichik harfga qaramaydi). */
function Highlight({ text, query }) {
  const value = String(text || '')
  const index = query ? value.toLowerCase().indexOf(query.toLowerCase()) : -1
  if (index < 0) return value
  return (
    <>
      {value.slice(0, index)}
      <Box
        component="mark"
        sx={{ bgcolor: 'm3.primaryContainer', color: 'inherit', fontWeight: 700, borderRadius: '4px', px: 0.25 }}
      >
        {value.slice(index, index + query.length)}
      </Box>
      {value.slice(index + query.length)}
    </>
  )
}
