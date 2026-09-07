import ResourcePage from '../../components/data/ResourcePage'
import { countCell, useRegionOptions } from './shared'
import { zones as zonesApi } from '../../api/endpoints'

export default function ZonesPage() {
  const { options: regionOptions } = useRegionOptions()

  return (
    <ResourcePage
      title="Binolar"
      subtitle="Imtihon markazlari — kompyuter va kameralar shu yerga biriktiriladi"
      queryKey="zones"
      restorable
      api={zonesApi}
      permission="regions.manage"
      searchPlaceholder="Nomi yoki manzili bo‘yicha…"
      defaultSort={{ field: 'number', sort: 'asc' }}
      defaults={{ is_active: true, number: '', capacity: '' }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Binoga bog‘langan kompyuterlar mavjud bo‘lsa, server o‘chirishga ruxsat bermaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1.3, minWidth: 170 },
        { field: 'number', headerName: 'Raqam', width: 95, type: 'number' },
        { field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 150, sortable: false },
        { field: 'address', headerName: 'Manzil', flex: 1.5, minWidth: 190, sortable: false },
        {
          field: 'capacity', headerName: 'Sig‘im', width: 95,
          type: 'number', align: 'right', headerAlign: 'right', renderCell: countCell,
        },
        {
          field: 'computers_count', headerName: 'PC', width: 80, sortable: false,
          align: 'right', headerAlign: 'right', renderCell: countCell,
        },
        {
          field: 'cameras_count', headerName: 'Kamera', width: 95, sortable: false,
          align: 'right', headerAlign: 'right', renderCell: countCell,
        },
      ]}
      toggleField="is_active"
      exportName="binolar"
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
        },
        { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 8 },
        {
          name: 'number', label: 'Raqam', type: 'number', required: true,
          min: 0, integer: true, colSpan: 4,
          helperText: 'Viloyat ichida unikal bo‘lishi shart',
        },
        { name: 'address', label: 'Manzil', maxLength: 500, colSpan: 12 },
        {
          name: 'capacity', label: 'Sig‘im (o‘rin)', type: 'number',
          min: 0, max: 100000, integer: true, colSpan: 6,
        },
        { name: 'is_part', label: 'Bino ankladi', type: 'boolean', colSpan: 6 },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
