import ResourcePage from '../../components/data/ResourcePage'
import { hotkeys as hotkeysApi } from '../../api/endpoints'

/**
 * Bloklanadigan klaviatura kombinatsiyalari.
 *
 * Client `code` ni past darajali hook'da taqqoslaydi, shuning uchun kod
 * aniq shaklda bo'lishi kerak: `alt+tab`, `ctrl+shift+i`. Nom esa faqat
 * operator uchun.
 */
export default function HotkeysPage() {
  return (
    <ResourcePage
      title="Tezkor tugmalar"
      subtitle="Imtihon paytida bloklanadigan klaviatura kombinatsiyalari"
      queryKey="hotkeys"
      api={hotkeysApi}
      permission="controls.manage"
      searchPlaceholder="Nomi yoki kodi bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Kombinatsiya o‘chirilsa, client uni endi bloklamaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 180 },
        { field: 'code', headerName: 'Kod', flex: 1, minWidth: 180 },
      ]}
      toggleField="is_active"
      exportName="tezkor-tugmalar"
      filters={[
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        {
          name: 'name', label: 'Nomi', required: true, maxLength: 100, colSpan: 6,
          helperText: 'Operator ko‘radigan nom: “Alt+Tab”',
        },
        {
          name: 'code', label: 'Kod', required: true, maxLength: 100, colSpan: 6,
          transform: (value) => String(value || '').trim().toLowerCase().replace(/ /g, ''),
          helperText: 'Client taqqoslaydigan kalit: “alt+tab”, “ctrl+shift+i”',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
