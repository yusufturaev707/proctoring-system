import { useState } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import CategoryIcon from '@mui/icons-material/CategoryOutlined'
import LabelIcon from '@mui/icons-material/LabelOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import type { CellParams, RowDetail } from '../../components/data/types'
import ExamTypeDetailDialog from '../../components/exams/ExamTypeDetailDialog'
import { countCell } from './shared'
import { examTypes as examTypesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

const cell = { height: '100%', display: 'flex', alignItems: 'center', minWidth: 0 }
// `countCell` o'zi tekislanmaydi — o'ngga va vertikal markazga (`ZonesPage` bilan bir xil).
const rightCount = (params: CellParams<number | null>) => (
  <Box sx={{ ...cell, justifyContent: 'flex-end' }}>{countCell(params)}</Box>
)

const FORM_SECTIONS = {
  'Asosiy': { icon: LabelIcon, description: 'Nom ro‘yxatlarda ko‘rinadi, kalit — hisobot va integratsiyadagi kod' },
  'Holat': { icon: ToggleIcon, description: 'Nofaol tur yangi imtihonga tanlanmaydi, mavjudlari ishlayveradi' },
}

export default function ExamTypesPage() {
  const { canShared } = useAuth()
  const canManage = canShared('exams.manage')
  const [detail, setDetail] = useState<RowDetail | null>(null)

  return (
    <>
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Imtihon turlari"
      subtitle="Imtihonlarni guruhlaydigan ma’lumotnoma. Qatorni bosing, to‘liq karta ochiladi"
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
      formIcon={<CategoryIcon />}
      formTitle={(isEdit, row) => (isEdit ? `${row?.name} — tahrirlash` : 'Yangi imtihon turi')}
      formSections={FORM_SECTIONS}
      onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
      columns={[
        {
          field: 'name', headerName: 'Nomi', flex: 1.6, minWidth: 190,
          renderCell: (params) => (
            <Stack direction="row" spacing={1} alignItems="center" sx={cell}>
              <Typography variant="body2" fontWeight={600} noWrap>{params.value}</Typography>
              {params.row.deleted_at && <Chip size="small" color="error" variant="outlined" label="O‘chirilgan" />}
            </Stack>
          ),
        },
        {
          field: 'key', headerName: 'Kalit', width: 180,
          renderCell: (params) => (
            <Typography variant="body2" color="text.secondary" sx={{ ...cell, fontFamily: 'monospace', fontSize: 12.5 }} noWrap>
              {params.value}
            </Typography>
          ),
        },
        {
          field: 'exams_count', headerName: 'Imtihonlar', width: 120, sortable: false,
          align: 'right', headerAlign: 'right', renderCell: rightCount,
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
        { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12, section: 'Asosiy' },
        {
          name: 'key', label: 'Kalit', required: true, maxLength: 100, colSpan: 12, section: 'Asosiy',
          // Server ham kichik harfga keltiradi (`validate_key`), bu yerda
          // esa foydalanuvchi kiritayotgan payt ko'rib turadi.
          transform: (value) => String(value || '').trim().toLowerCase(),
          helperText: 'Kod sifatida ishlatiladi va keyin o‘zgartirilmasligi kerak',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Holat' },
      ]}
    />
    {detail && (
      <ExamTypeDetailDialog
        row={detail.row}
        onClose={() => setDetail(null)}
        onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
      />
    )}
    </>
  )
}
