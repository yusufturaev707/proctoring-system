import { useState } from 'react'
import { Box, Chip, CircularProgress, IconButton, Stack, Tooltip, Typography } from '@mui/material'
import VideocamIcon from '@mui/icons-material/VideocamOutlined'
import NetworkCheckIcon from '@mui/icons-material/NetworkCheckOutlined'
import ResourcePage from '../../components/data/ResourcePage'
import CameraLiveDialog from '../../components/cameras/CameraLiveDialog'
import { LastSeenCell, regionZoneFilters, useRegionOptions, useZoneOptions, zonesOfRegion } from './shared'
import { cameras as camerasApi } from '../../api/endpoints'
import { useUi } from '../../context/UiContext'
import { formatDateTime, fromNow } from '../../utils/labels'

const CAMERA_STATUS = {
  online: { label: 'Online', color: 'success' },
  offline: { label: 'Offline', color: 'default' },
  error: { label: 'Xatolik', color: 'error' },
}

const cameraStatusText = (value) => CAMERA_STATUS[value]?.label || value || ''

/**
 * Kamera holati - RANG + SABAB.
 *
 * "Xatolik" so'zining o'zi administratorga hech narsa aytmaydi: login
 * noto'g'rimi, RTSP yo'limi? Sabab (`status_message`) va holat qachon
 * tekshirilgani tooltip'da - ikkinchisi tekshiruv umuman ishlamay
 * qolganini ko'rsatadi (masalan Celery beat to'xtagan).
 */
function CameraStatusCell({ row }) {
  const meta = CAMERA_STATUS[row.status] || CAMERA_STATUS.offline
  const tooltip = [
    row.status_message,
    row.last_checked_at ? `Tekshirildi: ${fromNow(row.last_checked_at)} (${formatDateTime(row.last_checked_at)})` : 'Hali tekshirilmagan',
  ].filter(Boolean).join(' · ')
  return (
    <Tooltip title={tooltip}>
      {/* `height: 100%` - katak balandligi bo'ylab O'RTAGA: aks holda
          belgi qatorning yuqorisiga yopishib, qo'shni ustunlardagi
          matndan pastda qolardi. */}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0, height: '100%' }}>
        <Chip
          size="small"
          color={meta.color}
          variant={row.status === 'offline' ? 'outlined' : 'filled'}
          label={meta.label}
          sx={{ fontWeight: 600 }}
        />
        {row.status === 'error' && row.status_message && (
          <Typography variant="caption" color="error.main" noWrap>{row.status_message}</Typography>
        )}
      </Stack>
    </Tooltip>
  )
}

/**
 * "Hozir tekshirish" - natijani DARHOL ko'rsatadi.
 *
 * Davriy tekshiruv daqiqada bir marta; administrator kamerani tuzatgach
 * bir daqiqa kutmasligi kerak.
 */
function CheckButton({ row, resource }) {
  const { notify, notifyError } = useUi()
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try {
      const updated = await camerasApi.check(row.id)
      const meta = CAMERA_STATUS[updated.status] || CAMERA_STATUS.offline
      notify(`${row.name}: ${meta.label}${updated.status_message ? ` — ${updated.status_message}` : ''}`)
      resource.refetch()
    } catch (error) {
      notifyError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Tooltip title="Holatni hozir tekshirish">
      <span>
        <IconButton size="small" onClick={run} disabled={busy} aria-label="Holatni hozir tekshirish">
          {busy ? <CircularProgress size={16} /> : <NetworkCheckIcon fontSize="small" />}
        </IconButton>
      </span>
    </Tooltip>
  )
}

export default function CamerasPage() {
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()
  const [live, setLive] = useState(null)   // { camera, resource }

  return (
    <>
    <ResourcePage
      title="IP kameralar"
      subtitle="Zonani kuzatuvchi kameralar — parollar shifrlangan holda saqlanadi"
      queryKey="cameras"
      restorable
      api={camerasApi}
      permission="devices.manage"
      searchPlaceholder="Nomi, IP yoki MAC…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{
        is_active: true,
        rtsp_path: '/Streaming/Channels/101',
        vendor: 'hikvision',
        transport: 'tcp',
        port: 554,
      }}
      getRowLabel={(row) => row?.name}
      // Holat har daqiqada serverda yangilanadi - sahifa ham o'zi
      // yangilanadi, aks holda "online" bo'lgan kamera ekranda "offline"
      // bo'lib turaverardi.
      refetchInterval={30000}
      rowActions={(row, resource) => (
        <>
          <Tooltip title={row.is_active ? 'Jonli ko‘rish' : 'Kamera faol emas'}>
            <span>
              <IconButton
                size="small"
                color="primary"
                disabled={!row.is_active}
                aria-label="Jonli ko‘rish"
                onClick={() => setLive({ camera: row, resource })}
              >
                <VideocamIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <CheckButton row={row} resource={resource} />
        </>
      )}
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1.1, minWidth: 160 },
        { field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 150, sortable: false },
        { field: 'region_name', headerName: 'Viloyat', width: 150, sortable: false },
        { field: 'ip_address', headerName: 'IP', width: 145 },
        { field: 'mac_address', headerName: 'MAC', width: 165 },
        {
          field: 'has_password', headerName: 'Parol', width: 135, sortable: false,
          exportValue: (value) => (value ? 'Shifrlangan' : 'O‘rnatilmagan'),
          renderCell: (params) => (
            <Chip
              size="small"
              variant="outlined"
              color={params.value ? 'success' : 'warning'}
              label={params.value ? 'Shifrlangan' : 'O‘rnatilmagan'}
            />
          ),
        },
        {
          field: 'status', headerName: 'Holat', width: 230,
          renderCell: CameraStatusCell, exportValue: cameraStatusText,
        },
        // "Oxirgi ONLINE" - oxirgi tekshiruv EMAS: offline kamerada u
        // "qachondan beri ishlamayapti" degan savolga javob beradi.
        { field: 'last_seen_at', headerName: 'Oxirgi online', width: 150, renderCell: LastSeenCell },
      ]}
      toggleField="is_active"
      exportName="kameralar"
      filters={[
        ...regionZoneFilters({ regionOptions, zoneOptions }),
        {
          name: 'status', label: 'Holat', type: 'select',
          options: [
            { value: 'online', label: 'Online' },
            { value: 'offline', label: 'Offline' },
            { value: 'error', label: 'Xatolik' },
          ],
        },
      ]}
      fields={[
        // Zanjir: Viloyat -> Bino (Kompyuterlar formasi bilan bir xil).
        // Viloyat modelda yo'q, shuning uchun `transient`.
        {
          name: 'region', label: 'Viloyat', type: 'select', required: true,
          transient: true, options: regionOptions, colSpan: 6, resets: ['zone'],
          helperText: 'Binolar ro‘yxatini toraytirish uchun',
        },
        {
          name: 'zone', label: 'Bino', type: 'select', required: true,
          options: (form) => zonesOfRegion(zoneOptions, form.region),
          colSpan: 6, dependsOn: 'region',
          blockedText: 'Avval viloyatni tanlang',
          emptyOptionsText: 'Bu viloyatda bino yo‘q — avval bino qo‘shing',
        },
        { name: 'name', label: 'Nomi', required: true, maxLength: 120, colSpan: 12 },
        { name: 'ip_address', label: 'IP manzil', required: true, pattern: 'ipv4', colSpan: 6 },
        {
          name: 'mac_address', label: 'MAC manzil', required: true, pattern: 'mac', colSpan: 6,
          transform: (value) => String(value || '').replace(/-/g, ':').toUpperCase(),
        },
        {
          name: 'vendor', label: 'Ishlab chiqaruvchi', type: 'select', colSpan: 6,
          section: 'Ulanish',
          options: [
            { value: 'hikvision', label: 'Hikvision' },
            { value: 'dahua', label: 'Dahua' },
            { value: 'onvif', label: 'ONVIF (umumiy)' },
            { value: 'generic', label: 'Boshqa' },
          ],
          // Ishlab chiqaruvchi RTSP yo'lini TANLAMAYDI - u faqat belgi.
          // Yo'lni har doim `rtsp_path` belgilaydi: "vendor bo'yicha
          // yo'lni taxmin qilish" birinchi nostandart proshivkada
          // buziladi va xato "oqim ochilmadi" bo'lib ko'rinadi.
          helperText: 'Faqat belgi — yo‘lni quyidagi maydon belgilaydi',
        },
        {
          name: 'transport', label: 'Transport', type: 'select', colSpan: 6,
          section: 'Ulanish',
          options: [
            { value: 'tcp', label: 'TCP (tavsiya etiladi)' },
            { value: 'udp', label: 'UDP' },
          ],
          helperText: 'UDP’da paket yo‘qolishi kadrni buzadi',
        },
        {
          name: 'rtsp_path', label: 'RTSP yo‘li', maxLength: 255, colSpan: 8,
          section: 'Ulanish',
          helperText: 'Masalan: /Streaming/Channels/101',
        },
        {
          name: 'port', label: 'RTSP port', type: 'number', colSpan: 4,
          section: 'Ulanish', min: 1, max: 65535,
        },
        { name: 'login', label: 'Login', maxLength: 120, colSpan: 6, section: 'Ulanish' },
        {
          name: 'password', label: 'Parol', type: 'password', colSpan: 6, section: 'Ulanish',
          password: true,
          // Parol serverdan HECH QACHON qaytmaydi — faqat `has_password`
          // bayrog'i keladi. Bo'sh qoldirilsa mavjud parol o'zgarmaydi.
          helperText: (isEdit) =>
            isEdit ? 'Bo‘sh qoldirilsa — parol o‘zgarmaydi' : 'Shifrlangan holda saqlanadi',
          clearable: false,
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Ulanish' },
      ]}
    />
    <CameraLiveDialog
      open={Boolean(live)}
      camera={live?.camera}
      onClose={() => setLive(null)}
      onChecked={() => live?.resource?.refetch()}
    />
    </>
  )
}
