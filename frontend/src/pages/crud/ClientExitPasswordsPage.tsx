import { Chip } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { useRegionOptions } from './shared'
import { exitPasswords as exitPasswordsApi } from '../../api/endpoints'

/**
 * Desktop client'dan chiqish parollari — har bir viloyat uchun bittadan.
 *
 * NIMA UCHUN KERAK. Client kiosk rejimida ishlaydi va o'zini yopishga
 * ruxsat bermaydi. Xodim tizimga kirgan bo'lsa, u o'z paroli bilan
 * chiqadi va audit iziga ismi yoziladi. Lekin dastur login sahifasida
 * turganda hech qanday xodim yo'q — o'sha paytda mashinani qonuniy
 * yopishning yagona yo'li shu parol.
 *
 * NIMA UCHUN VILOYAT BO'YICHA. Yagona umumiy parol 14 ta hududda
 * ishlatilsa, uning bir markazdan sizib chiqishi butun respublikani
 * ochib qo'yardi. Viloyat paroli sizsa — zarar o'sha viloyat bilan
 * cheklanadi va uni boshqalarga tegmasdan almashtirish mumkin.
 *
 * PAROL KO'RSATILMAYDI. U bazada hash ko'rinishida yotadi va API uni
 * hech qachon qaytarmaydi — jadvalda faqat "o'rnatilgan/yo'q" holati
 * ko'rinadi. Unutilgan parolni tiklab bo'lmaydi, faqat yangisini
 * o'rnatish mumkin. Bu ataylab: baza nusxasi qo'lga tushsa, barcha
 * viloyatlarning kaliti ochiq bo'lmasligi kerak.
 *
 * Ruxsat `controls.exit_password_*` — client siyosatidan ALOHIDA:
 * bu parolni bilgan odam imtihon o'rtasida dasturni yopa oladi.
 */
export default function ClientExitPasswordsPage() {
  const { options: regionOptions } = useRegionOptions()

  return (
    <ResourcePage
      title="Chiqish parollari"
      subtitle="Client'dan chiqish uchun viloyat paroli"
      queryKey="exit-passwords"
      api={exitPasswordsApi}
      permission="controls.exit_password_manage"
      searchPlaceholder="Viloyat yoki izoh bo‘yicha…"
      defaultSort={{ field: 'region__dtm_id', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.region_name}
      deleteConfirmPhrase
      deleteDescription="Parol o‘chirilsa, bu viloyatdagi client'ni login sahifasidan yopib bo‘lmaydi — faqat tizimga kirgan xodim o‘z paroli bilan chiqa oladi."
      formMaxWidth="sm"
      columns={[
        { field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 200, sortable: false },
        {
          field: 'name', headerName: 'Izoh', flex: 1, minWidth: 180, sortable: false,
          renderCell: (params) => params.value || '—',
        },
        {
          field: 'has_password', headerName: 'Parol', width: 150, sortable: false,
          exportValue: (value) => (value ? "o'rnatilgan" : "yo'q"),
          renderCell: (params) =>
            params.value
              ? <Chip size="small" color="success" variant="outlined" label="O‘rnatilgan" />
              : <Chip size="small" color="error" variant="outlined" label="Yo‘q" />,
        },
      ]}
      toggleField="is_active"
      exportName="chiqish-parollari"
      filters={[
        { name: 'region', label: 'Viloyat', type: 'select', options: regionOptions },
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        {
          name: 'region', label: 'Viloyat', type: 'select', required: true,
          options: regionOptions, colSpan: 12,
          helperText: 'Har bir viloyat uchun faqat bitta parol bo‘ladi',
        },
        {
          name: 'name', label: 'Izoh', maxLength: 255, colSpan: 12,
          helperText: 'Masalan: “2026 bahorgi sessiya”. Parolning o‘zi emas!',
        },
        {
          name: 'password', label: 'Yangi parol', type: 'password', colSpan: 12,
          minLength: 4, maxLength: 128,
          helperText:
            'Tahrirlashda bo‘sh qoldirilsa — amaldagi parol o‘zgarmaydi. ' +
            'Kiritilgan parolni keyin ko‘rib bo‘lmaydi, uni saqlab qo‘ying.',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
      formDescription="Parol bazada qaytarib bo‘lmaydigan (hash) ko‘rinishda saqlanadi — uni panelda ham, API orqali ham o‘qib bo‘lmaydi."
    />
  )
}
