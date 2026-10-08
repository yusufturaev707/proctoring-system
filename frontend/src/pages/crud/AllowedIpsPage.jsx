import { useState } from 'react'
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import RouterIcon from '@mui/icons-material/RouterOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import AllowedIpDetailDialog, { cidrInfo } from '../../components/controls/AllowedIpDetailDialog'
import { regionZoneFilters, useRegionOptions, useZoneOptions, zonesOfRegion } from './shared'
import { allowedIps as allowedIpsApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

const FORM_SECTIONS = {
  'Manzil': { icon: RouterIcon, description: 'IP manzil YOKI tarmoqdan aynan bittasi' },
  'Bino': {
    icon: PlaceIcon,
    description: 'Bino ko‘rsatilsa — qurilma ro‘yxatdan o‘tishda bino shu manzil orqali aniqlanadi',
  },
  'Holat': { icon: ToggleIcon },
}

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
 * bajaradi, lekin ikkinchisini BAJARMAYDI — buni jadvalda, formada va
 * kartada aniq ko'rsatamiz.
 *
 * Ruxsat `controls.ip_manage` — client siyosatidan alohida: bitta
 * noto'g'ri yozuv butun markazni tizimdan uzib qo'yadi.
 */
export default function AllowedIpsPage() {
  const { can, user } = useAuth()
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()
  const [detail, setDetail] = useState(null)

  // Binosiz (global) yozuvni viloyat xodimi faqat o'qiydi — server
  // o'zgartirishni rad etadi (`AllowedPublicIpSerializer.validate`).
  const canEditRow = (row) => can('controls.ip_manage') && !(user?.is_region_scoped && !row.zone)

  return (
    <>
      <ResourcePage
        title="Ruxsat etilgan IP'lar"
        subtitle="Imtihon markazlarining tashqi (NAT) manzillari va ichki/VPN tarmoqlari — qatorni bosing, to‘liq karta ochiladi"
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
        formIcon={<RouterIcon />}
        formTitle={(isEdit, row) =>
          (isEdit ? `${row?.ip_address || row?.network} — tahrirlash` : 'Yangi ruxsat etilgan manzil')}
        formSections={FORM_SECTIONS}
        formDescription="Bir binoga bir nechta yozuv qo‘shish mumkin (rezerv kanal, bir nechta subnet). Har bir IP butun tizimda bir marta uchraydi, tarmoqlar o‘zaro kesishmaydi."
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        columns={[
          {
            field: 'ip_address', headerName: 'Manzil', flex: 1, minWidth: 210,
            exportValue: (value, row) => value || row?.network || '',
            renderCell: (params) => {
              const isNetwork = !params.value
              const cidr = isNetwork ? cidrInfo(params.row.network) : null
              const Icon = isNetwork ? LanIcon : PublicIcon
              return (
                <Stack direction="row" spacing={1} alignItems="center" sx={{ ...cell, minWidth: 0 }}>
                  <Tooltip title={isNetwork ? 'Tarmoq (CIDR)' : 'Tashqi (NAT) IP'}>
                    <Icon fontSize="small" sx={{ color: 'text.secondary' }} />
                  </Tooltip>
                  <Typography variant="body2" fontWeight={600} noWrap sx={{ fontFamily: 'monospace' }}>
                    {params.value || params.row.network}
                  </Typography>
                  {cidr && (
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {cidr.size.toLocaleString('ru-RU')} ta
                    </Typography>
                  )}
                </Stack>
              )
            },
          },
          {
            field: 'name', headerName: 'Nomi', flex: 1, minWidth: 160, sortable: false,
            renderCell: (params) => (
              <Typography variant="body2" noWrap color={params.value ? 'text.primary' : 'text.disabled'} sx={cell}>
                {params.value || 'Nomsiz'}
              </Typography>
            ),
          },
          {
            field: 'zone_name', headerName: 'Bino', flex: 1.3, minWidth: 230, sortable: false,
            exportValue: (value, row) => (value ? `${row.region_name} · ${value}` : 'Barcha binolar (global)'),
            renderCell: (params) =>
              params.value
                ? (
                  <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
                    <Typography variant="body2" noWrap>{params.value}</Typography>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ lineHeight: 1.2 }}>
                      {params.row.region_name}
                    </Typography>
                  </Stack>
                )
                : (
                  <Box sx={cell}>
                    <Tooltip title="Barcha binolar uchun ochiq, lekin qurilma ro‘yxatdan o‘tishda bino aniqlanmaydi">
                      <Chip size="small" color="warning" variant="outlined" label="Global — bino aniqlanmaydi" />
                    </Tooltip>
                  </Box>
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
            name: 'ip_address', label: 'Tashqi IP manzil', section: 'Manzil',
            pattern: 'ipv4', colSpan: 6, validate: exactlyOneAddress,
            helperText: 'Bino internet orqali ulansa: uning tashqi (NAT) manzili',
          },
          {
            name: 'network', label: 'yoki tarmoq (CIDR)', section: 'Manzil',
            pattern: 'cidr4', colSpan: 6, validate: exactlyOneAddress,
            helperText: (_isEdit, form) => {
              const cidr = cidrInfo(String(form?.network || '').trim())
              return cidr
                ? `${cidr.first} – ${cidr.last} · ${cidr.size.toLocaleString('ru-RU')} ta manzil`
                : 'Server bino ichida yoki VPN bo‘lsa: bino tarmog‘i, masalan 192.168.0.0/24'
            },
          },
          {
            // Modelda bo'sh satr (`default=""`) — tozalanganda `null` emas.
            name: 'name', label: 'Nomi', maxLength: 255, colSpan: 12, nullable: false, section: 'Manzil',
            helperText: 'Masalan: “1-bino, asosiy kanal”',
          },
          // Viloyat `transient`: modelda bunday maydon yo'q va u serverga
          // yuborilmaydi (serializer uni faqat O'QISH uchun beradi, bino
          // orqali). U faqat binolar ro'yxatini toraytiradi — 400 ta bino
          // ichidan qidirish o'rniga admin avval viloyatni tanlaydi.
          {
            name: 'region', label: 'Viloyat', type: 'select', transient: true, section: 'Bino',
            options: regionOptions, colSpan: 6, resets: ['zone'],
            helperText: 'Binolar ro‘yxatini toraytirish uchun',
          },
          {
            name: 'zone', label: 'Bino', type: 'select', colSpan: 6, dependsOn: 'region', section: 'Bino',
            options: (form) => zonesOfRegion(zoneOptions, form.region),
            blockedText: 'Avval viloyatni tanlang',
            emptyOptionsText: 'Bu viloyatda bino yo‘q — avval bino qo‘shing',
            helperText: (_isEdit, form) =>
              form?.zone
                ? 'Qurilma ro‘yxatdan o‘tishda bino shu manzil orqali avtomatik aniqlanadi'
                : 'Bo‘sh qolsa manzil BARCHA binolar uchun ochiq (global), lekin binoni aniqlash uchun ishlatilmaydi',
          },
          {
            name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Holat',
            helperText: 'O‘chirilsa — bu manzildan kelgan client rad etiladi (boshqa faol yozuv mos kelmasa)',
          },
        ]}
      />

      {detail && (
        <AllowedIpDetailDialog
          row={detail.row}
          onClose={() => setDetail(null)}
          onEdit={canEditRow(detail.row) ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
        />
      )}
    </>
  )
}
