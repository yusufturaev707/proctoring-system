import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, Grid, IconButton, Skeleton, Stack,
  Typography, useMediaQuery, useTheme,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'
import FingerprintIcon from '@mui/icons-material/FingerprintOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import MemoryIcon from '@mui/icons-material/MemoryOutlined'
import VideocamIcon from '@mui/icons-material/VideocamOutlined'
import DevicesIcon from '@mui/icons-material/DevicesOtherOutlined'
import PlayIcon from '@mui/icons-material/PlayCircleOutline'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'

import { computers as computersApi, deviceTokens as devicesApi } from '../../api/endpoints'
import { dateText, Field, HeaderIcon, Section, useCopy } from '../data/DetailFields'
import { COMPUTER_STATUS_LABEL, DEVICE_STATUS_LABEL } from '../../utils/labels'

const STATUS_TONE = { online: 'success', in_exam: 'warning', blocked: 'error', offline: 'default' }

/**
 * `info_pc` kalitlari — o'zbekcha yorliq bilan (client `system_info.info_pc`
 * va `hardware/gpu_detector.as_dict`). Ro'yxatda yo'q kalit ham ko'rsatiladi
 * (xom nomi bilan): client yangi maydon qo'shsa, u panelda jimgina yo'qolmasin.
 */
const INFO_LABEL = {
  hostname: 'Kompyuter nomi',
  os: 'Operatsion tizim',
  machine: 'Arxitektura',
  cpu_count: 'CPU (mantiqiy yadro)',
  cpu_cores: 'CPU yadrolari',
  cpu_threads: 'CPU oqimlari',
  memory_total_gb: 'RAM, GB',
  ram_gb: 'RAM, GB',
  gpu_name: 'Videokarta',
  gpu_vram_mb: 'Video xotira, MB',
  driver_version: 'Drayver versiyasi',
  cuda_available: 'CUDA ishlaydimi',
  providers: 'ONNX provayderlari',
  onnxruntime: 'onnxruntime',
  python: 'Python',
  cuda_reason: 'CUDA izohi',
}
// `gpu_warning` alohida ogohlantirish bo'lib chiqadi - ro'yxatga kirmaydi.
const INFO_HIDDEN = new Set(['gpu_warning'])

/** Ichma-ich lug'atni tekis `[kalit, qiymat]` ro'yxatiga yoyadi. */
function flattenInfo(info, prefix = '') {
  if (!info || typeof info !== 'object') return []
  return Object.entries(info).flatMap(([key, value]) => {
    if (INFO_HIDDEN.has(key)) return []
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return flattenInfo(value, `${prefix}${key}.`)
    }
    return [[`${prefix}${key}`, key, value]]
  })
}

const infoText = (value) => {
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'boolean') return value ? 'Ha' : 'Yo‘q'
  return value == null ? '' : String(value)
}

/**
 * Kompyuterning TO'LIQ kartasi — jadval qatori bosilganda (MD3 dialog).
 *
 * Jadvalda faqat qidirish/saralash uchun kerak ustunlar; bu yerda
 * hammasi guruhlab: joylashuv, identifikator (UUID + MAC juftligi),
 * tarmoq, kameralar, shu kompyuterdagi client qurilmalari va client
 * yuborgan apparat ma'lumoti (`info_pc`). Ma'lumot `detail` bilan
 * YANGIDAN olinadi: ro'yxat 30 s da yangilanadi va qatordagi nusxa
 * eskirgan bo'lishi mumkin.
 */
export default function ComputerDetailDialog({ row, canEdit, onEdit, onClose }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const navigate = useNavigate()
  const copy = useCopy()

  const { data: fresh } = useQuery({
    queryKey: ['computers', 'detail', row?.id],
    queryFn: () => computersApi.detail(row.id),
    enabled: Boolean(row?.id),
  })
  const { data: devicesPage, isLoading: devicesLoading } = useQuery({
    queryKey: ['device-tokens', 'by-computer', row?.id],
    queryFn: () => devicesApi.list({ computer: row.id, page_size: 20 }),
    enabled: Boolean(row?.id),
  })

  if (!row) return null
  const pc = { ...row, ...(fresh || {}) }
  const devices = devicesPage?.results || []
  const cameras = pc.cameras_detail || []
  const info = flattenInfo(pc.info_pc)
  const gpuWarning = pc.info_pc?.gpu_warning || pc.info_pc?.hardware?.gpu_warning

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth="md"
      fullWidth
      fullScreen={fullScreen}
      slotProps={{ paper: { sx: { bgcolor: 'm3.surfaceContainerLow', borderRadius: fullScreen ? 0 : '28px' } } }}
    >
      {/* Sarlavha: nom (stoldagi raqam + inventar kodi) va holatlar. */}
      <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ px: 3, pt: 3, pb: 2 }}>
        <HeaderIcon tone={pc.is_active ? 'primary' : 'neutral'}><ComputerIcon /></HeaderIcon>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h6" noWrap sx={{ lineHeight: 1.3 }}>
            {pc.label || pc.inventory_code}
          </Typography>
          <Typography variant="body2" color="text.secondary" noWrap>
            {[pc.region_name, pc.zone_name].filter(Boolean).join(' · ') || '—'}
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            <Chip
              size="small"
              color={STATUS_TONE[pc.status] || 'default'}
              variant={pc.status === 'offline' ? 'outlined' : 'filled'}
              label={COMPUTER_STATUS_LABEL[pc.status] || pc.status}
            />
            <Chip
              size="small"
              variant="outlined"
              color={pc.is_active ? 'success' : 'default'}
              label={pc.is_active ? 'Faol' : 'Hisobdan chiqarilgan'}
            />
            {!pc.mac_address && <Chip size="small" color="warning" label="MAC kiritilmagan" />}
            {!pc.machine_uuid && <Chip size="small" variant="outlined" color="warning" label="UUID yo‘q" />}
          </Stack>
        </Box>
        <IconButton onClick={onClose} aria-label="Yopish" sx={{ mt: -0.5, mr: -1 }}>
          <CloseIcon />
        </IconButton>
      </Stack>

      <DialogContent sx={{ pt: 0, px: { xs: 2, sm: 3 } }}>
        {pc.active_session_id && (
          <Box
            sx={{
              mb: 1.5, p: 2, borderRadius: '16px', bgcolor: 'm3.primaryContainer',
              display: 'flex', alignItems: 'center', gap: 1.5,
            }}
          >
            <PlayIcon color="primary" />
            <Typography variant="body2" sx={{ flex: 1 }}>
              Bu kompyuterda hozir imtihon ketmoqda
            </Typography>
            <Button size="small" onClick={() => navigate(`/sessions/${pc.active_session_id}`)} sx={{ borderRadius: 999 }}>
              Sessiyani ochish
            </Button>
          </Box>
        )}

        <Grid container columnSpacing={2}>
          <Grid item xs={12} md={6}>
            <Section title="Joylashuv">
              <Field icon={<PlaceIcon fontSize="small" />} label="Viloyat" value={pc.region_name} />
              <Field label="Bino" value={pc.zone_name} />
              <Field label="Stoldagi raqam" value={pc.number} hint="Raqamlanmagan" />
              <Field label="Inventar kodi" value={pc.inventory_code} mono onCopy={copy} />
            </Section>

            {/* Mashina - (UUID, MAC) juftligi: ikkalasi birga mashinani belgilaydi. */}
            <Section title="Identifikator (UUID + MAC)">
              <Field
                icon={<FingerprintIcon fontSize="small" />}
                label="Machine UUID"
                value={pc.machine_uuid}
                hint="Yozilmagan — birinchi ulanishda MAC orqali bog‘lanadi"
                mono
                onCopy={copy}
              />
              <Field
                label="MAC manzil"
                value={pc.mac_address}
                hint="Kiritilmagan — mashina faqat UUID bilan tanilmoqda"
                mono
                onCopy={copy}
                warn={!pc.mac_address}
              />
            </Section>

            <Section title="Tarmoq va holat">
              <Field icon={<LanIcon fontSize="small" />} label="IP manzil" value={pc.ip_address} hint="Ko‘rsatilmagan (DHCP)" mono onCopy={copy} />
              <Field label="Oxirgi signal" value={dateText(pc.last_seen_at)} hint="Client hali ulanmagan" />
              <Field label="Qo‘shilgan" value={dateText(pc.created_at)} />
            </Section>
          </Grid>

          <Grid item xs={12} md={6}>
            <Section title={`Kameralar · ${cameras.length}`}>
              {cameras.length ? cameras.map((camera) => (
                <Field
                  key={camera.id}
                  icon={<VideocamIcon fontSize="small" />}
                  label={camera.ip_address || 'IP yo‘q'}
                  value={camera.name}
                />
              )) : (
                <Field icon={<VideocamIcon fontSize="small" />} label="Biriktirilgan kamera" value="" hint="Yo‘q — faqat ekran va veb-kamera" />
              )}
            </Section>

            <Section title={`Client qurilmalari · ${devices.length}`}>
              {devicesLoading ? (
                <Box sx={{ p: 2 }}><Skeleton height={32} /></Box>
              ) : devices.length ? devices.map((device) => (
                <Field
                  key={device.id}
                  icon={<DevicesIcon fontSize="small" />}
                  label={`${DEVICE_STATUS_LABEL[device.status] || device.status}${device.is_online ? ' · online' : ''}${device.app_version ? ` · v${device.app_version}` : ''}`}
                  value={device.device_id}
                  mono
                  onCopy={copy}
                />
              )) : (
                <Field icon={<DevicesIcon fontSize="small" />} label="Qurilma" value="" hint="Client bu kompyuterda hali ro‘yxatdan o‘tmagan" />
              )}
            </Section>

            <Section title="Apparat (client yuborgan)">
              {gpuWarning && (
                <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ px: 2, py: 1.25, bgcolor: 'warning.light', color: 'warning.dark' }}>
                  <WarningIcon fontSize="small" />
                  <Typography variant="body2">{String(gpuWarning)}</Typography>
                </Stack>
              )}
              {info.length ? info.map(([path, key, value]) => (
                <Field
                  key={path}
                  icon={key === 'gpu_name' || key === 'cpu_count' ? <MemoryIcon fontSize="small" /> : undefined}
                  label={INFO_LABEL[key] || path}
                  value={infoText(value)}
                  wrap
                />
              )) : (
                <Field icon={<MemoryIcon fontSize="small" />} label="Ma’lumot" value="" hint="Client hali handshake yubormagan" />
              )}
            </Section>
          </Grid>
        </Grid>
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2, gap: 1, bgcolor: 'm3.surfaceContainer' }}>
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>ID {pc.id}</Typography>
        <Button onClick={onClose} sx={{ borderRadius: 999 }}>Yopish</Button>
        {canEdit && (
          <Button
            variant="contained"
            disableElevation
            startIcon={<EditIcon />}
            onClick={() => onEdit(pc)}
            sx={{ borderRadius: 999 }}
          >
            Tahrirlash
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
