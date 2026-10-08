import { useState } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import MapIcon from '@mui/icons-material/MapOutlined'
import TagIcon from '@mui/icons-material/TagOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import RegionDetailDialog from '../../components/regions/RegionDetailDialog'
import { countCell } from './shared'
import { regions as regionsApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

const FORM_SECTIONS = {
  'Viloyat': { icon: MapIcon, description: 'Xodimlarning ko‘rish doirasi shu hudud bo‘yicha cheklanadi' },
  'Identifikatorlar': {
    icon: TagIcon,
    description: 'Tashqi tizimlar bilan moslik — Excel import va FaceID integratsiyasi DTM ID bo‘yicha qidiradi',
  },
  'Holat': { icon: ToggleIcon },
}

export default function RegionsPage() {
  const { canShared } = useAuth()
  const canManage = canShared('regions.manage')
  const [detail, setDetail] = useState(null)

  return (
    <>
      <ResourcePage
        // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
        shared
        title="Viloyatlar"
        subtitle="Hududiy bo‘linish — bino va xodimlar shunga bog‘lanadi. Qatorni bosing, to‘liq karta ochiladi"
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
        formMaxWidth="sm"
        formIcon={<MapIcon />}
        formTitle={(isEdit, row) => (isEdit ? `${row?.name} — tahrirlash` : 'Yangi viloyat')}
        formSections={FORM_SECTIONS}
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        columns={[
          {
            field: 'name', headerName: 'Viloyat', flex: 1.6, minWidth: 210,
            renderCell: (params) => (
              <Stack direction="row" spacing={1} alignItems="center" sx={{ ...cell, minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap>{params.value}</Typography>
                {params.row.is_have_part && <Chip size="small" variant="outlined" label="Bo‘linmali" />}
              </Stack>
            ),
          },
          {
            field: 'dtm_id', headerName: 'DTM ID', width: 110,
            renderCell: (params) => (
              <Typography variant="body2" sx={{ ...cell, fontFamily: 'monospace' }}>{params.value}</Typography>
            ),
          },
          {
            field: 'vm_number', headerName: 'VM raqami', width: 120,
            renderCell: (params) => (
              <Typography variant="body2" sx={{ ...cell, fontFamily: 'monospace' }}>{params.value}</Typography>
            ),
          },
          {
            field: 'zones_count', headerName: 'Binolar', width: 110,
            align: 'right', headerAlign: 'right', sortable: false,
            renderCell: (params) => <Box sx={{ ...cell, justifyContent: 'flex-end' }}>{countCell(params)}</Box>,
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
          { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12, section: 'Viloyat' },
          {
            name: 'dtm_id', label: 'DTM ID', type: 'number', required: true,
            min: 1, integer: true, colSpan: 6, section: 'Identifikatorlar',
            helperText: 'Tashqi tizimdagi raqam — tizim bo‘ylab unikal',
          },
          {
            name: 'vm_number', label: 'VM raqami', type: 'number', required: true,
            min: 1, integer: true, colSpan: 6, section: 'Identifikatorlar',
            helperText: 'Tizim bo‘ylab unikal',
          },
          { name: 'is_have_part', label: 'Bo‘linmalari bor', type: 'boolean', colSpan: 6, section: 'Holat' },
          { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Holat' },
        ]}
      />

      {detail && (
        <RegionDetailDialog
          row={detail.row}
          onClose={() => setDetail(null)}
          onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
        />
      )}
    </>
  )
}
