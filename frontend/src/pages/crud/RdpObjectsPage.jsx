import { Chip, Stack, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { rdpObjects as rdpObjectsApi } from '../../api/endpoints'

/**
 * Aniqlanishi kerak bo'lgan dasturlar (AnyDesk, TeamViewer, VirtualBox...).
 *
 * BU RO'YXAT CLIENT KATALOGINI ALMASHTIRMAYDI, QO'SHADI. Client'da
 * ichki katalog bor (`client/services/threat_rules.py`) va u serverdan
 * mustaqil ishlaydi — ya'ni bu jadval bo'sh bo'lsa ham himoya bor.
 * Bu yerga faqat katalogda YO'Q dastur yoziladi: yangi dasturni 500
 * mashinaga tarqatish uchun client'ni qayta yig'ish shart emas.
 *
 * FAQAT JARAYON NOMI YETARLI EMAS. `AnyDesk.exe` ni `notepad.exe` deb
 * qayta nomlash bir soniyalik ish, ya'ni nom bo'yicha qidiruv eng
 * sodda chetlab o'tishga ham dosh bermaydi. Qolgan maydonlar aynan
 * shuning uchun: imzo, `OriginalFilename`, xizmat nomi va port
 * faylni qayta nomlaganda O'ZGARMAYDI.
 */

/** Bo'sh bo'lmagan matnlar massivi — barcha JSON maydonlari uchun bir xil. */
function stringArray(value) {
  if (!value?.trim()) return null
  try {
    const parsed = JSON.parse(value)
    if (!Array.isArray(parsed)) return 'Massiv bo‘lishi kerak: ["App.exe"]'
    if (parsed.some((item) => typeof item !== 'string' || !item.trim())) {
      return 'Har bir element bo‘sh bo‘lmagan matn bo‘lishi kerak'
    }
    return null
  } catch {
    return 'JSON formati noto‘g‘ri'
  }
}

/** Portlar — 1..65535 oralig'idagi butun sonlar. */
function portArray(value) {
  if (!value?.trim()) return null
  try {
    const parsed = JSON.parse(value)
    if (!Array.isArray(parsed)) return 'Massiv bo‘lishi kerak: [7070]'
    if (parsed.some((item) => !Number.isInteger(item) || item < 1 || item > 65535)) {
      return 'Har bir element 1–65535 oralig‘idagi butun son bo‘lishi kerak'
    }
    return null
  } catch {
    return 'JSON formati noto‘g‘ri'
  }
}

const CATEGORY_LABEL = {
  remote: 'Masofaviy boshqaruv',
  vm: 'Virtual mashina',
  tool: 'Yordamchi vosita',
}

function chipList(params) {
  const items = params.value || []
  if (!items.length) {
    return <Typography variant="body2" color="text.disabled">—</Typography>
  }
  return (
    <Stack direction="row" spacing={0.5} sx={{ overflow: 'hidden' }}>
      {/* Kalit indeks bo'yicha: ro'yxat erkin kiritiladi va takroriy
          nom bo'lishi mumkin. */}
      {items.slice(0, 3).map((item, index) => (
        <Chip key={index} size="small" variant="outlined" label={item} />
      ))}
      {items.length > 3 && <Chip size="small" label={`+${items.length - 3}`} />}
    </Stack>
  )
}

export default function RdpObjectsPage() {
  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Taqiqlangan dasturlar"
      subtitle="Masofaviy boshqaruv, virtualizatsiya va yordamchi vositalarni aniqlash"
      queryKey="rdp-objects"
      api={rdpObjectsApi}
      permission="controls.manage"
      searchPlaceholder="Nomi yoki kodi bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{
        is_active: true,
        is_blocking: false,
        category: 'remote',
        process_names: [],
        publishers: [],
        original_filenames: [],
        products: [],
        service_names: [],
        ports: [],
      }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Dastur o‘chirilsa, client uni endi aniqlamaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 160 },
        { field: 'code', headerName: 'Kod', width: 140 },
        {
          field: 'category', headerName: 'Toifa', width: 170,
          valueFormatter: (value) => CATEGORY_LABEL[value] || value,
        },
        {
          field: 'process_names', headerName: 'Jarayonlar', flex: 1.2, minWidth: 190,
          sortable: false,
          exportValue: (value) => (value || []).join(', '),
          renderCell: chipList,
        },
        {
          field: 'original_filenames', headerName: 'OriginalFilename', flex: 1.2, minWidth: 190,
          sortable: false,
          exportValue: (value) => (value || []).join(', '),
          renderCell: chipList,
        },
        {
          field: 'is_blocking', headerName: 'To‘sadi', width: 110, type: 'boolean',
        },
      ]}
      toggleField="is_active"
      exportName="taqiqlangan-dasturlar"
      filters={[
        {
          name: 'category', label: 'Toifa', type: 'select',
          options: [
            { value: 'remote', label: 'Masofaviy boshqaruv' },
            { value: 'vm', label: 'Virtual mashina' },
            { value: 'tool', label: 'Yordamchi vosita' },
          ],
        },
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Nomi', required: true, maxLength: 100, colSpan: 6 },
        {
          name: 'code', label: 'Kod', required: true, maxLength: 100, colSpan: 6,
          transform: (value) => String(value || '').trim().toLowerCase(),
          helperText: 'Barqaror kalit — keyin o‘zgartirilmasligi kerak',
        },
        {
          name: 'category', label: 'Toifa', type: 'select', required: true, colSpan: 6,
          options: [
            { value: 'remote', label: 'Masofaviy boshqaruv' },
            { value: 'vm', label: 'Virtual mashina' },
            { value: 'tool', label: 'Yordamchi vosita' },
          ],
          helperText: 'Hodisa turini belgilaydi: rdp_detected / vm_detected / process_blacklisted',
        },
        {
          name: 'is_blocking', label: 'Yopib bo‘lmasa imtihonni to‘sadi',
          type: 'boolean', colSpan: 6,
          helperText: 'Ehtiyot bo‘ling: noto‘g‘ri yozuv butun imtihonni bloklaydi',
        },
        {
          name: 'publishers', label: 'Imzo egalari (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [], validate: stringArray,
          helperText:
            'Masalan: ["AnyDesk Software GmbH"]. Faylni qayta nomlash imzoni o‘zgartirmaydi — ' +
            'eng ishonchli belgi. Keng vendor nomini yozmang ("Google LLC" Chrome‘ni ham tutadi).',
        },
        {
          name: 'original_filenames', label: 'OriginalFilename (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [], validate: stringArray,
          helperText:
            'Masalan: ["AnyDesk.exe"]. PE resursidagi asl nom — qayta nomlash unga ta‘sir qilmaydi.',
        },
        {
          name: 'products', label: 'Mahsulot nomlari (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [], validate: stringArray,
          helperText:
            'ProductName / FileDescription ichidan QISM SATR bo‘yicha qidiriladi. ' +
            'Juda qisqa qiymat yozmang — "vnc" begona dasturlarni ham tutishi mumkin.',
        },
        {
          name: 'process_names', label: 'Jarayon nomlari (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [], validate: stringArray,
          helperText:
            'Masalan: ["AnyDesk.exe"]. ENG ZAIF belgi — faqat yuqoridagilar javob bermaganda ishlaydi.',
        },
        {
          name: 'service_names', label: 'Windows xizmatlari (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [], validate: stringArray,
          helperText:
            'Masalan: ["AnyDesk"]. Xizmatni to‘xtatmasdan jarayonni o‘ldirish foydasiz — ' +
            'Windows uni bir necha soniyada qayta ko‘taradi.',
        },
        {
          name: 'ports', label: 'Portlar (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [], validate: portArray,
          helperText:
            'Masalan: [7070]. Resursi va imzosi butunlay tozalangan binar faqat shu yerda tutiladi.',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
