import { Chip, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { regionZoneFilters, useRegionOptions, useZoneOptions, zonesOfRegion } from './shared'
import { allowedIps as allowedIpsApi } from '../../api/endpoints'

/** «IP yoki tarmoq — aynan bittasi» (server: `clean_allowlist_entry`). */
function exactlyOneAddress(_value, form) {
  const hasIp = Boolean(String(form.ip_address || '').trim())
  const hasNetwork = Boolean(String(form.network || '').trim())
  if (hasIp === hasNetwork) return 'IP manzil YOKI tarmoqdan aynan bittasini kiriting'
  return null
}

/**
 * Ruxsat etilgan manzillar: bitta tashqi (NAT) IP YOKI tarmoq (CIDR).
 *
 * Tarmoq — server binoning ICHIDA turganda (u clientlarni LAN manzili
 * bilan ko'radi) yoki binolar bitta VPN tarmog'ida bo'lganda: har bino
 * o'z subnet'i bilan, BINOGA bog'langan holda. Tarmoqlar kesishmaydi.
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
      subtitle="Imtihon markazlarining tashqi (NAT) manzillari va ichki/VPN tarmoqlari"
      queryKey="allowed-ips"
      api={allowedIpsApi}
      permission="controls.ip_manage"
      searchPlaceholder="IP, tarmoq yoki nom bo‘yicha…"
      defaultSort={{ field: 'ip_address', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.ip_address || row?.network}
      // Ro'yxat bo'sh bo'lsa tekshiruv O'CHIRILGAN hisoblanadi. Oxirgi
      // qatorni o'chirish — butun tarmoq cheklovini olib tashlash demak.
      deleteConfirmPhrase
      deleteDescription="IP o‘chirilsa, shu manzildan ulanayotgan clientlar ishlamay qoladi. Ro‘yxat butunlay bo‘shab qolsa, tekshiruv o‘chirilgan hisoblanadi."
      formMaxWidth="md"
      columns={[
        {
          field: 'ip_address', headerName: 'Manzil', width: 180,
          exportValue: (value, row) => value || row?.network || '',
          renderCell: (params) =>
            params.value
              ? params.value
              : <Chip size="small" variant="outlined" label={`Tarmoq ${params.row.network}`} />,
        },
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
        ...regionZoneFilters({ regionOptions, zoneOptions }),
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        {
          name: 'ip_address', label: 'Tashqi IP manzil',
          pattern: 'ipv4', colSpan: 6, validate: exactlyOneAddress,
          helperText: 'Bino internet orqali ulansa: uning tashqi (NAT) manzili',
        },
        {
          name: 'network', label: 'yoki tarmoq (CIDR)',
          pattern: 'cidr4', colSpan: 6, validate: exactlyOneAddress,
          helperText: 'Server bino ichida yoki VPN bo‘lsa: bino tarmog‘i, masalan 192.168.0.0/24',
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
      formDescription="IP yoki tarmoqdan aynan bittasini kiriting. Bir binoga bir nechta yozuv qo‘shish mumkin (rezerv kanal, bir nechta subnet). Har bir IP butun tizimda bir marta uchraydi, tarmoqlar o‘zaro kesishmaydi."
    />
  )
}
