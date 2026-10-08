import { useState } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import ApartmentIcon from '@mui/icons-material/ApartmentOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'
import EventSeatIcon from '@mui/icons-material/EventSeatOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import ZoneDetailDialog from '../../components/regions/ZoneDetailDialog'
import { countCell, useRegionOptions } from './shared'
import { zones as zonesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

const cell = { height: '100%', display: 'flex', alignItems: 'center' }
const rightCell = (params) => <Box sx={{ ...cell, justifyContent: 'flex-end' }}>{countCell(params)}</Box>

const FORM_SECTIONS = {
  'Joylashuv': { icon: PlaceIcon, description: 'Viloyat va raqam — Excel import va FaceID integratsiyasi binoni shu juftlik bo‘yicha topadi' },
  'Sig‘im': { icon: EventSeatIcon, description: 'Imtihon o‘rinlari soni — rejalashtirish uchun' },
  'Holat': { icon: ToggleIcon },
}

export default function ZonesPage() {
  const { can, user } = useAuth()
  const canManage = can('regions.manage')
  const { options: regionOptions } = useRegionOptions()
  const [detail, setDetail] = useState(null)

  return (
    <>
      <ResourcePage
        title="Binolar"
        subtitle="Imtihon markazlari — kompyuter va kameralar shu yerga biriktiriladi. Qatorni bosing, to‘liq karta ochiladi"
        queryKey="zones"
        restorable
        api={zonesApi}
        permission="regions.manage"
        searchPlaceholder="Nomi yoki manzili bo‘yicha…"
        defaultSort={{ field: 'number', sort: 'asc' }}
        defaults={{
          is_active: true,
          number: '',
          capacity: '',
          // Viloyat admini faqat o'z viloyatiga bino qo'sha oladi.
          region: user?.is_region_scoped ? user.region : '',
        }}
        getRowLabel={(row) => row?.name}
        deleteDescription="Binoga bog‘langan kompyuterlar mavjud bo‘lsa, server o‘chirishga ruxsat bermaydi. O‘chirilgan bino «Savat» filtrida qoladi va tiklanadi."
        formMaxWidth="md"
        formIcon={<ApartmentIcon />}
        formTitle={(isEdit, row) => (isEdit ? `${row?.name} — tahrirlash` : 'Yangi bino')}
        formSections={FORM_SECTIONS}
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        columns={[
          {
            field: 'number', headerName: 'Raqam', width: 84,
            renderCell: (params) => (
              <Box sx={cell}>
                <Box
                  sx={{
                    minWidth: 32, height: 26, px: 0.75, borderRadius: '8px',
                    display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 700,
                    bgcolor: params.row.is_active ? 'm3.secondaryContainer' : 'm3.surfaceContainerHighest',
                    color: params.row.is_active ? 'm3.onSecondaryContainer' : 'text.disabled',
                  }}
                >
                  {params.value}
                </Box>
              </Box>
            ),
          },
          {
            field: 'name', headerName: 'Bino', flex: 1.4, minWidth: 210,
            exportValue: (value, row) => (row.address ? `${value} (${row.address})` : value),
            renderCell: (params) => (
              <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ minWidth: 0 }}>
                  <Typography variant="body2" fontWeight={600} noWrap>{params.value}</Typography>
                  {params.row.is_part && <Chip size="small" variant="outlined" label="Anklav" />}
                  {params.row.deleted_at && <Chip size="small" color="error" variant="outlined" label="O‘chirilgan" />}
                </Stack>
                {params.row.address && (
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ lineHeight: 1.2 }}>
                    {params.row.address}
                  </Typography>
                )}
              </Stack>
            ),
          },
          {
            field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 150, sortable: false,
            renderCell: (params) => <Typography variant="body2" noWrap sx={cell}>{params.value}</Typography>,
          },
          {
            field: 'capacity', headerName: 'Sig‘im', width: 95,
            align: 'right', headerAlign: 'right', sortable: false, renderCell: rightCell,
          },
          {
            field: 'computers_count', headerName: 'PC', width: 80, sortable: false,
            align: 'right', headerAlign: 'right', renderCell: rightCell,
          },
          {
            field: 'cameras_count', headerName: 'Kamera', width: 95, sortable: false,
            align: 'right', headerAlign: 'right', renderCell: rightCell,
          },
        ]}
        toggleField="is_active"
        exportName="binolar"
        filters={[
          // Viloyat xodimi faqat o'z viloyatini ko'radi — tanlov ma'nosiz.
          { name: 'region', label: 'Viloyat', type: 'select', options: regionOptions, regionScope: true },
          {
            name: 'is_active', label: 'Holat', type: 'select',
            options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
          },
        ]}
        fields={[
          {
            name: 'region', label: 'Viloyat', type: 'select', required: true,
            options: regionOptions, colSpan: 8, section: 'Joylashuv',
          },
          {
            name: 'number', label: 'Raqam', type: 'number', required: true,
            min: 0, integer: true, colSpan: 4, section: 'Joylashuv',
            helperText: 'Viloyat ichida unikal',
          },
          { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12, section: 'Joylashuv' },
          {
            // Modelda bo'sh satr (`default=""`) — tozalanganda `null` emas.
            name: 'address', label: 'Manzil', maxLength: 500, colSpan: 12, nullable: false, section: 'Joylashuv',
            helperText: 'Ko‘cha, uy — operator va texnik xodim uchun',
          },
          {
            name: 'capacity', label: 'Sig‘im (o‘rin)', type: 'number',
            min: 0, max: 100000, integer: true, colSpan: 6, section: 'Sig‘im',
            // Ustun NOT NULL (`default=0`): tozalangan maydon `null` emas, 0.
            transform: (value) => value ?? 0,
            helperText: 'Bo‘sh qolsa — 0 (kiritilmagan)',
          },
          { name: 'is_part', label: 'Bino anklavmi', type: 'boolean', colSpan: 6, section: 'Holat' },
          {
            name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Holat',
            helperText: 'Nofaol bino qurilma ro‘yxatdan o‘tishda IP orqali aniqlanmaydi',
          },
        ]}
      />

      {detail && (
        <ZoneDetailDialog
          row={detail.row}
          onClose={() => setDetail(null)}
          onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
        />
      )}
    </>
  )
}
