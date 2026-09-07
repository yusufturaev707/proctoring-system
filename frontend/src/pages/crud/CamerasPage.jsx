import { Chip } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import {
  DeviceStatusCell, LastSeenCell, deviceStatusText, useRegionOptions, useZoneOptions,
  zonesOfRegion,
} from './shared'
import { cameras as camerasApi } from '../../api/endpoints'

export default function CamerasPage() {
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()

  return (
    <ResourcePage
      title="IP kameralar"
      subtitle="Zonani kuzatuvchi kameralar — parollar shifrlangan holda saqlanadi"
      queryKey="cameras"
      restorable
      api={camerasApi}
      permission="devices.manage"
      searchPlaceholder="Nomi, IP yoki MAC…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: true, rtsp_path: '/Streaming/Channels/101' }}
      getRowLabel={(row) => row?.name}
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1.1, minWidth: 160 },
        { field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 150, sortable: false },
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
          field: 'status', headerName: 'Holat', width: 130,
          renderCell: DeviceStatusCell, exportValue: deviceStatusText,
        },
        { field: 'last_seen_at', headerName: 'Oxirgi signal', width: 150, renderCell: LastSeenCell },
      ]}
      toggleField="is_active"
      exportName="kameralar"
      filters={[
        { name: 'zone', label: 'Bino', type: 'select', options: zoneOptions },
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
          name: 'rtsp_path', label: 'RTSP yo‘li', maxLength: 255, colSpan: 12,
          section: 'Ulanish',
          helperText: 'Masalan: /Streaming/Channels/101',
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
  )
}
