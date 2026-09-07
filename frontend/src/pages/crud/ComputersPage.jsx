import { Chip, Stack, Typography } from '@mui/material'

import ResourcePage from '../../components/data/ResourcePage'
import {
  DeviceStatusCell, LastSeenCell, camerasOfZone, deviceStatusText, useCameraOptions,
  useRegionOptions, useZoneOptions, zonesOfRegion,
} from './shared'
import { computers as computersApi } from '../../api/endpoints'

export default function ComputersPage() {
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()
  const { options: cameraOptions } = useCameraOptions()

  return (
    <ResourcePage
      title="Kompyuterlar"
      subtitle="Imtihon ish stantsiyalari — client faqat ro‘yxatdagi kompyuterdan ulanadi"
      queryKey="computers"
      restorable
      api={computersApi}
      permission="devices.manage"
      searchPlaceholder="Inventar, IP yoki MAC…"
      defaultSort={{ field: 'inventory_code', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.inventory_code}
      deleteConfirmPhrase
      deleteDescription="Kompyuterga bog‘langan sessiyalar tarixi saqlanib qoladi, lekin qurilma tokeni bekor bo‘ladi."
      columns={[
        { field: 'inventory_code', headerName: 'Inventar', width: 150 },
        { field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 150, sortable: false },
        { field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 140, sortable: false },
        { field: 'ip_address', headerName: 'IP', width: 145 },
        { field: 'mac_address', headerName: 'MAC', width: 165 },
        {
          field: 'cameras_detail', headerName: 'Kameralar', width: 150, sortable: false,
          exportValue: (value) => (value || []).map((item) => item.name).join(', '),
          renderCell: (params) => {
            const list = params.value || []
            if (!list.length) {
              return <Typography variant="body2" color="text.disabled">Biriktirilmagan</Typography>
            }
            return (
              <Stack direction="row" spacing={0.5} alignItems="center">
                <Chip size="small" variant="outlined" label={`${list.length} ta`} />
                <Typography variant="caption" color="text.secondary" noWrap>
                  {list.map((item) => item.name).join(', ')}
                </Typography>
              </Stack>
            )
          },
        },
        {
          field: 'status', headerName: 'Holat', width: 140,
          renderCell: DeviceStatusCell, exportValue: deviceStatusText,
        },
        { field: 'last_seen_at', headerName: 'Oxirgi signal', width: 150, renderCell: LastSeenCell },
      ]}
      toggleField="is_active"
      exportName="kompyuterlar"
      formMaxWidth="md"
      filters={[
        { name: 'zone', label: 'Bino', type: 'select', options: zoneOptions },
        {
          name: 'status', label: 'Holat', type: 'select',
          options: [
            { value: 'online', label: 'Online' },
            { value: 'offline', label: 'Offline' },
            { value: 'in_exam', label: 'Imtihonda' },
            { value: 'blocked', label: 'Bloklangan' },
          ],
        },
      ]}
      fields={[
        // Zanjir: Viloyat -> Bino -> Kameralar.
        //
        // Viloyat `transient` — kompyuterda bunday maydon yo'q va u
        // serverga yuborilmaydi. U faqat binolar ro'yxatini toraytiradi:
        // 400 ta bino ichidan qidirish o'rniga admin avval viloyatni
        // tanlaydi va 15 tadan birini tanlaydi.
        {
          name: 'region', label: 'Viloyat', type: 'select', required: true,
          transient: true, options: regionOptions, colSpan: 6,
          resets: ['zone', 'cameras'],
          helperText: 'Binolar ro‘yxatini toraytirish uchun',
        },
        {
          name: 'zone', label: 'Bino', type: 'select', required: true,
          options: (form) => zonesOfRegion(zoneOptions, form.region),
          colSpan: 6, dependsOn: 'region', resets: ['cameras'],
          blockedText: 'Avval viloyatni tanlang',
          emptyOptionsText: 'Bu viloyatda bino yo‘q — avval bino qo‘shing',
        },
        {
          name: 'inventory_code', label: 'Inventar kodi', required: true,
          maxLength: 50, pattern: 'slug', colSpan: 12,
          helperText: 'Faqat harf, raqam, `-` va `_`. Tizim bo‘ylab unikal.',
        },
        {
          name: 'ip_address', label: 'IP manzil', required: true,
          pattern: 'ipv4', colSpan: 6,
          helperText: 'Bino ichida unikal bo‘lishi kerak',
        },
        {
          name: 'mac_address', label: 'MAC manzil', required: true,
          pattern: 'mac', colSpan: 6,
          // MAC serverda ham normalizatsiya qilinadi, lekin bu yerda
          // kiritishni yagona shaklga keltirish dublikat xatolarini kamaytiradi.
          transform: (value) => String(value || '').replace(/-/g, ':').toUpperCase(),
        },
        {
          name: 'cameras', label: 'Biriktirilgan kameralar', type: 'multiselect',
          // FAQAT tanlangan binodagi kameralar. Boshqa binoning kamerasini
          // biriktirish jismonan ma'nosiz — u bu xonani ko'rmaydi.
          options: (form) => camerasOfZone(cameraOptions, form.zone),
          colSpan: 12, section: 'Kuzatuv', dependsOn: 'zone',
          blockedText: 'Avval binoni tanlang',
          emptyOptionsText: 'Bu binoda kamera ro‘yxatga olinmagan',
          helperText:
            'Shu ish stantsiyasini kuzatuvchi IP kameralar. Bo‘sh qoldirilsa, ' +
            'sessiya faqat ekran va veb-kamera bo‘yicha kuzatiladi.',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Kuzatuv' },
      ]}
    />
  )
}
