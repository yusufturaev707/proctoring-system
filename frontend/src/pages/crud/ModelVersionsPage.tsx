import { Chip } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { modelVersions as modelVersionsApi } from '../../api/endpoints'

/**
 * YOLO model versiyalari.
 *
 * `is_active` — client qaysi modelni ishlatishini belgilaydi. Bir vaqtda
 * bir nechta faol versiya qoldirilsa, natija tartibga bog'liq bo'lib
 * qoladi: shuning uchun faol versiyani bittada saqlash tavsiya etiladi.
 */
export default function ModelVersionsPage() {
  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Model versiyalari"
      subtitle="Client ishlatadigan obyekt aniqlash modellari"
      queryKey="model-versions"
      api={modelVersionsApi}
      permission="controls.manage"
      searchPlaceholder="Nomi yoki kodi bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: false }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Faol versiya o‘chirilsa, clientlar model yangilanishini ola olmaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 170 },
        { field: 'code', headerName: 'Kod', width: 160 },
        {
          field: 'file_key', headerName: 'Fayl kaliti', flex: 1.4, minWidth: 220, sortable: false,
          renderCell: (params) =>
            params.value || <Chip size="small" variant="outlined" label="Yuklanmagan" />,
        },
      ]}
      toggleField="is_active"
      exportName="model-versiyalari"
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
        {
          name: 'file_key', label: 'Fayl kaliti (object storage)', maxLength: 500, colSpan: 12,
          helperText:
            'S3/MinIO dagi obyekt kaliti. Bo‘sh bo‘lsa client bundle ichidagi modelni ishlatadi.',
        },
        {
          name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12,
          helperText: 'Faol versiyani clientlar keyingi handshake’da oladi',
        },
      ]}
    />
  )
}
