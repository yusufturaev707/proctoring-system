import { Chip, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { useRegionOptions, useZoneOptions, zonesOfRegion } from './shared'
import { allowedIps as allowedIpsApi } from '../../api/endpoints'

/**
 * Ruxsat etilgan tashqi (NAT) IP'lar.
 *
 * Bu ro'yxat ikki vazifani bajaradi va shuning uchun u shunchaki
 * "xavfsizlik sozlamasi" emas:
 *
 *   1. Client imtihon markazidan ulanayotganini tekshiradi — uydan
 *      ulangan client JSHSHIR qidiruviga umuman kira olmaydi.
 *   2. Qurilma ro'yxatdan o'tishda BINONI aniqlaydi. LAN IP faqat bino
 *      ichida unikal, shuning uchun bino noma'lum bo'lsa server IP
 *      bo'yicha kompyuter qidirmaydi.
 *
 * Shu sababli "Bino" ustuni bo'sh (global) yozuv birinchi vazifani
 * bajaradi, lekin ikkinchisini BAJARMAYDI — buni jadvalda ham, formada
 * ham aniq ko'rsatamiz.
 *
 * Ruxsat `controls.ip_manage` — client siyosatidan alohida: bitta
 * noto'g'ri yozuv butun markazni tizimdan uzib qo'yadi.
 */
export default function AllowedIpsPage() {
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()

  return (
    <ResourcePage
      title="Ruxsat etilgan IP'lar"
      subtitle="Imtihon markazlarining tashqi (NAT) manzillari"
      queryKey="allowed-ips"
      api={allowedIpsApi}
      permission="controls.ip_manage"
      searchPlaceholder="IP yoki nom bo‘yicha…"
      defaultSort={{ field: 'ip_address', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.ip_address}
      // Ro'yxat bo'sh bo'lsa tekshiruv O'CHIRILGAN hisoblanadi. Oxirgi
      // qatorni o'chirish — butun tarmoq cheklovini olib tashlash demak.
      deleteConfirmPhrase
      deleteDescription="IP o‘chirilsa, shu manzildan ulanayotgan clientlar ishlamay qoladi. Ro‘yxat butunlay bo‘shab qolsa, tekshiruv o‘chirilgan hisoblanadi."
      formMaxWidth="md"
      columns={[
        { field: 'ip_address', headerName: 'Tashqi IP', width: 165 },
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 170, sortable: false },
        {
          field: 'region_name', headerName: 'Viloyat', width: 165, sortable: false,
          renderCell: (params) => params.value || '—',
        },
        {
          field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 190, sortable: false,
          exportValue: (value) => value || 'Barcha binolar (global)',
          renderCell: (params) =>
            params.value
              ? <Typography variant="body2">{params.value}</Typography>
              : (
                <Chip
                  size="small"
                  color="warning"
                  variant="outlined"
                  label="Global — bino aniqlanmaydi"
                />
              ),
        },
      ]}
      toggleField="is_active"
      exportName="ruxsat-etilgan-ip"
      filters={[
        { name: 'zone__region', label: 'Viloyat', type: 'select', options: regionOptions },
        { name: 'zone', label: 'Bino', type: 'select', options: zoneOptions },
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        {
          name: 'ip_address', label: 'Tashqi IP manzil', required: true,
          pattern: 'ipv4', colSpan: 6,
          helperText: 'Binoning internetga chiqish manzili (LAN IP emas)',
        },
        {
          name: 'name', label: 'Nomi', maxLength: 255, colSpan: 6,
          helperText: 'Masalan: “1-bino, asosiy kanal”',
        },
        // Viloyat `transient`: modelda bunday maydon yo'q va u serverga
        // yuborilmaydi (serializer uni faqat O'QISH uchun beradi, bino
        // orqali). U faqat binolar ro'yxatini toraytiradi — 400 ta bino
        // ichidan qidirish o'rniga admin avval viloyatni tanlaydi.
        {
          name: 'region', label: 'Viloyat', type: 'select', transient: true,
          options: regionOptions, colSpan: 6, resets: ['zone'],
          helperText: 'Binolar ro‘yxatini toraytirish uchun',
        },
        {
          name: 'zone', label: 'Bino', type: 'select', colSpan: 6, dependsOn: 'region',
          options: (form) => zonesOfRegion(zoneOptions, form.region),
          blockedText: 'Avval viloyatni tanlang',
          emptyOptionsText: 'Bu viloyatda bino yo‘q — avval bino qo‘shing',
          helperText:
            'Bino ko‘rsatilsa, qurilma ro‘yxatdan o‘tishda bino shu IP orqali ' +
            'avtomatik aniqlanadi. Bo‘sh qoldirilsa manzil barcha binolar uchun ' +
            'ruxsat etiladi, lekin binoni aniqlash uchun ishlatilmaydi.',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
      formDescription="Bir binoga bir nechta manzil qo‘shish mumkin (rezerv kanal). Har bir IP butun tizimda faqat bir marta uchraydi."
    />
  )
}
