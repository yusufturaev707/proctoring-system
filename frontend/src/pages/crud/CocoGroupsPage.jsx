import ResourcePage from '../../components/data/ResourcePage'
import { cocoGroups as cocoGroupsApi } from '../../api/endpoints'

/** COCO obyektlarini mavzu bo'yicha guruhlaydigan ma'lumotnoma. */
export default function CocoGroupsPage() {
  return (
    <ResourcePage
      title="COCO guruhlari"
      subtitle="Aniqlanadigan obyektlarni guruhlash uchun ma’lumotnoma"
      queryKey="coco-groups"
      api={cocoGroupsApi}
      permission="controls.manage"
      searchPlaceholder="Nomi yoki kodi bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Guruhga bog‘langan obyektlar guruhsiz qoladi (o‘chirilmaydi)."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 200 },
        { field: 'code', headerName: 'Kod', flex: 1, minWidth: 170 },
      ]}
      toggleField="is_active"
      exportName="coco-guruhlari"
      filters={[
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
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
