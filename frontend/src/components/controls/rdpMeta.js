import ScreenShareIcon from '@mui/icons-material/ScreenShareOutlined'
import VmIcon from '@mui/icons-material/DnsOutlined'
import BuildIcon from '@mui/icons-material/BuildOutlined'

/**
 * Taqiqlangan dastur toifalari. Toifa hodisa TURINI belgilaydi
 * (`RdpObject.category` izohi) — proktor ekranida u shu nom bilan chiqadi.
 */
export const CATEGORY_META = {
  remote: { label: 'Masofaviy boshqaruv', icon: ScreenShareIcon, event: 'rdp_detected' },
  vm: { label: 'Virtual mashina', icon: VmIcon, event: 'vm_detected' },
  tool: { label: 'Yordamchi vosita', icon: BuildIcon, event: 'process_blacklisted' },
}

export const CATEGORY_OPTIONS = Object.entries(CATEGORY_META).map(([value, meta]) => ({ value, label: meta.label }))

/**
 * Aniqlash belgilari — client'ning ISHONCHLILIK tartibida
 * (`client/services/process_identity.py`: imzo → OriginalFilename →
 * ProductName → xizmat → port → fayl nomi). Tartib formada ham, kartada
 * ham shu: administrator avval kuchli belgini to'ldirsin.
 *
 * `strong` — faylni qayta nomlash O'ZGARTIRMAYDIGAN belgi.
 */
export const SIGNS = [
  {
    name: 'publishers', label: 'Imzo egasi', short: 'Imzo', strength: 'Eng ishonchli', strong: true,
    placeholder: 'AnyDesk Software GmbH',
    help: 'Authenticode sertifikatidagi tashkilot. Keng vendor nomini yozmang — “Google LLC” Chrome’ni ham tutadi.',
  },
  {
    name: 'original_filenames', label: 'Asl fayl nomi (OriginalFilename)', short: 'Asl nom', strength: 'Ishonchli', strong: true,
    placeholder: 'AnyDesk.exe',
    help: 'PE resursidagi asl nom — faylni qayta nomlash unga ta’sir qilmaydi.',
  },
  {
    name: 'products', label: 'Mahsulot nomi (ProductName)', short: 'Mahsulot', strength: 'O‘rtacha', strong: true,
    placeholder: 'AnyDesk',
    help: 'ProductName / FileDescription ichidan QISM SATR bo‘yicha qidiriladi. Juda qisqa qiymat (“vnc”) begona dasturni ham tutadi.',
  },
  {
    name: 'service_names', label: 'Windows xizmati', short: 'Xizmat', strength: 'Ishonchli', strong: true,
    placeholder: 'AnyDesk',
    help: 'Oynasiz qism. Client avval xizmatni to‘xtatadi — aks holda Windows jarayonni qayta ko‘taradi.',
  },
  {
    name: 'ports', label: 'Tinglanadigan TCP port', short: 'Port', strength: 'Zaxira', strong: true, numeric: true,
    placeholder: '7070',
    help: 'Resursi va imzosi tozalangan binar faqat shu bilan tutiladi.',
  },
  {
    name: 'process_names', label: 'Jarayon (fayl) nomi', short: 'Fayl nomi', strength: 'Eng zaif', strong: false,
    placeholder: 'AnyDesk.exe',
    help: 'Faylni qayta nomlash bilan chetlab o‘tiladi. “.exe” yozilmasa client o‘zi qo‘shadi.',
  },
]

/** Yozuvdagi to'ldirilgan belgilar va ularning holati. */
export function signsOf(row) {
  const present = SIGNS.filter((sign) => (row?.[sign.name] || []).length > 0)
  return {
    present,
    none: present.length === 0,
    // Faqat fayl nomi — "taqiqlangan" ko'rinadi, lekin qayta nomlangan
    // nusxa o'tib ketadi.
    weakOnly: present.length > 0 && present.every((sign) => !sign.strong),
  }
}
