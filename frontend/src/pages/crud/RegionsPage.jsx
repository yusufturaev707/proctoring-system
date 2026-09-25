import ResourcePage from '../../components/data/ResourcePage'
import { regions as regionsApi } from '../../api/endpoints'

export default function RegionsPage() {
  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Viloyatlar"
      subtitle="Hududiy bo‘linish — barcha bino va foydalanuvchilar shunga bog‘lanadi"
      queryKey="regions"
      api={regionsApi}
      permission="regions.manage"
      searchPlaceholder="Viloyat nomi bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.name}
      // Viloyatga binolar, foydalanuvchilar va sessiyalar bog'langan.
      // Tasodifiy o'chirish butun ierarxiyani buzadi — nomni qo'lda yozish talab qilinadi.
      deleteConfirmPhrase
      deleteDescription="Viloyatga bog‘langan binolar va foydalanuvchilar mavjud bo‘lsa, server o‘chirishga ruxsat bermaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1.6, minWidth: 190 },
        { field: 'dtm_id', headerName: 'DTM ID', width: 100, type: 'number' },
        { field: 'vm_number', headerName: 'VM raqami', width: 120, type: 'number' },
        {
          field: 'zones_count', headerName: 'Binolar', width: 110,
          type: 'number', align: 'right', headerAlign: 'right', sortable: false,
        },
      ]}
      // Viloyatni yoqish/o'chirish — bir bosishlik amal; buning uchun
      // formani ochish ortiqcha. Optimistik: kalit darhol o'zgaradi,
      // server rad etsa avvalgi holatga qaytadi.
      toggleField="is_active"
      exportName="viloyatlar"
      filters={[
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12 },
        {
          name: 'dtm_id', label: 'DTM ID', type: 'number', required: true,
          min: 1, integer: true, colSpan: 6,
          helperText: 'Tashqi tizimdagi identifikator — unikal bo‘lishi shart',
        },
        {
          name: 'vm_number', label: 'VM raqami', type: 'number', required: true,
          min: 1, integer: true, colSpan: 6,
        },
        { name: 'is_have_part', label: 'Bo‘linmalari bor', type: 'boolean', colSpan: 6 },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6 },
      ]}
    />
  )
}
