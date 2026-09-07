import ResourcePage from '../../components/data/ResourcePage'
import { countCell } from './shared'
import { examTypes as examTypesApi } from '../../api/endpoints'

export default function ExamTypesPage() {
  return (
    <ResourcePage
      title="Imtihon turlari"
      subtitle="Imtihonlarni guruhlaydigan ma’lumotnoma"
      queryKey="exam-types"
      restorable
      api={examTypesApi}
      permission="exams.manage"
      searchPlaceholder="Nomi yoki kaliti bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.name}
      // Turga bog'langan imtihonlar bo'lsa, FK `PROTECT` — server rad etadi.
      deleteDescription="Turga bog‘langan imtihonlar mavjud bo‘lsa, server o‘chirishga ruxsat bermaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1.6, minWidth: 190 },
        { field: 'key', headerName: 'Kalit', width: 180 },
        {
          field: 'exams_count', headerName: 'Imtihonlar', width: 120, sortable: false,
          align: 'right', headerAlign: 'right', renderCell: countCell,
        },
      ]}
      toggleField="is_active"
      exportName="imtihon-turlari"
      filters={[
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12 },
        {
          name: 'key', label: 'Kalit', required: true, maxLength: 100, colSpan: 6,
          // Server ham kichik harfga keltiradi (`validate_key`), bu yerda
          // esa foydalanuvchi kiritayotgan payt ko'rib turadi.
          transform: (value) => String(value || '').trim().toLowerCase(),
          helperText: 'Kod sifatida ishlatiladi va keyin o‘zgartirilmasligi kerak',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6 },
      ]}
    />
  )
}
