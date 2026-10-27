import { useMemo, useState } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import GavelIcon from '@mui/icons-material/GavelOutlined'
import ArticleIcon from '@mui/icons-material/ArticleOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import type { CustomFieldProps, FieldDef, FormValues, Option, RowDetail } from '../../components/data/types'
import OfferDetailDialog from '../../components/offers/OfferDetailDialog'
import RichTextEditor from '../../components/offers/RichTextEditor'
import { offers as offersApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { formatDateTime } from '../../utils/labels'
import type { ApiRecord } from '../../types/api'
import { useExamOfferOptions, useExamOptions } from './shared'

/**
 * Oferta — talabgor yuz tekshiruvidan OLDIN o'qib, shaxsga doir
 * ma'lumotlari bilan ishlashga rozilik beradigan matn.
 *
 * OFERTA TESTGA TEGISHLI: har testning o'z shartlari bor. Bog'lanish
 * imtihon yozuvida (`Exam.offer`) — testda bitta oferta, bitta matn esa
 * bir nechta testga xizmat qiladi. Shu formadagi «Testlar» va imtihon
 * formasidagi «Oferta» BIR XIL bog'lanishni tahrirlaydi.
 *
 * ROZILIK SAQLANMAYDI: client ofertani har JSHSHIR qidiruvida ko'rsatadi va
 * «Roziman» siz davom ettirmaydi. Bazada faqat shu sahifadagi tahrirlar
 * qoladi — har matn/sarlavha o'zgarishi yangi o'zgarmas versiya.
 *
 * Testga biriktirilmagan yoki nofaol oferta talabgorga ko'rsatilmaydi.
 */

const FORM_SECTIONS = {
  'Hujjat': {
    icon: ArticleIcon,
    description: 'Talabgor ekranida aynan shu ko‘rinishda chiqadi: sarlavha tepada, matn ostida',
  },
  'Testlar': {
    icon: SchoolIcon,
    description: 'Shu testlarda talabgor yuz tekshiruvidan oldin aynan shu matnga rozilik beradi. Har testda bitta oferta',
  },
}

/** Boshqa ofertadagi test tanlansa u shu ofertaga KO'CHADI — yorliq buni oldindan aytadi. */
const examLabel = (option: Option, form: FormValues): Option => {
  const own = form._meta?.row?.id
  const notes: string[] = []
  if (option.offer && option.offer !== own) notes.push(`hozir: «${option.offerTitle}»`)
  if (option.isActive === false) notes.push('nofaol')
  return notes.length ? { ...option, label: `${option.label} — ${notes.join(', ')}` } : option
}

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

const examNames = (row: ApiRecord): string[] => (row.exam_list || []).map((exam: ApiRecord) => exam.name)

const buildFields = (examOptions: Option[]): FieldDef[] => [
  {
    name: 'title', label: 'Sarlavha', required: true, maxLength: 200, colSpan: 12, section: 'Hujjat',
    helperText: 'Masalan: «Shaxsga doir ma’lumotlarni qayta ishlashga rozilik (ommaviy oferta)»',
  },
  {
    name: 'content', label: 'Matn', type: 'custom', required: true, colSpan: 12, section: 'Hujjat',
    emptyValue: '',
    helperText: 'Saqlanganda matn yangi versiya bo‘lib yoziladi — keyingi JSHSHIR tekshiruvidan boshlab talabgorlar shu matnni ko‘radi',
    render: ({ value, onChange, disabled, error }: CustomFieldProps) => (
      <RichTextEditor value={value || ''} onChange={onChange} disabled={disabled} error={Boolean(error)} />
    ),
  },
  {
    name: 'exams', label: 'Testlar', type: 'multiselect', colSpan: 12, section: 'Testlar',
    options: (form) => examOptions.map((option) => examLabel(option, form)),
    emptyOptionsText: 'Imtihon yo‘q — avval «Imtihonlar» sahifasida qo‘shing',
    helperText: (_isEdit, form) => {
      const own = form._meta?.row?.id
      const moving = examOptions.filter(
        (option) => (form.exams || []).includes(option.value) && option.offer && option.offer !== own,
      ).length
      return moving
        ? `${moving} ta test boshqa ofertadan shu ofertaga ko‘chadi — saqlangandan keyin talabgorlar shu matnni ko‘radi`
        : 'Bo‘sh qoldirilsa — oferta hech bir testda so‘ralmaydi. Testni imtihon formasidan ham biriktirish mumkin'
    },
  },
  {
    name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Testlar',
    helperText: 'O‘chirilsa — biriktirilgan testlarda ham so‘ralmaydi (biriktiruv saqlanadi). Qoralama uchun',
  },
]

// Oferta saqlanganda testlarning `offer` i ham o'zgaradi.
const RELATED_KEYS = ['exams']

export default function OffersPage() {
  const { can, canShared } = useAuth()
  const canManage = canShared('offers.manage')
  // Testlar ro'yxati `exams.view` da — usiz so'rov 403 berardi.
  const canSeeExams = can('exams.view')
  const [detail, setDetail] = useState<RowDetail | null>(null)
  const { options: examOfferOptions } = useExamOfferOptions(canSeeExams)
  const { options: examOptions } = useExamOptions(canSeeExams)
  const fields = useMemo(() => buildFields(examOfferOptions), [examOfferOptions])

  return (
    <>
      <ResourcePage
        // Testlar barcha viloyatlar uchun bitta — ularning ofertasi ham.
        shared
        restorable
        title="Oferta"
        subtitle="Har testning shaxsga doir ma’lumotlarni qayta ishlashga rozilik matni — qatorni bosing, matn, testlar va versiyalar tarixi ochiladi"
        queryKey="offers"
        relatedKeys={RELATED_KEYS}
        api={offersApi}
        permission="offers.manage"
        searchPlaceholder="Sarlavha yoki test nomi…"
        defaultSort={{ field: 'updated_at', sort: 'desc' }}
        defaults={{ title: '', content: '', exams: [], is_active: true }}
        getRowLabel={(row) => row?.title}
        deleteDescription="Testga biriktirilgan ofertani o‘chirib bo‘lmaydi — avval testlardan ajrating. Versiyalar tarixi saqlanib qoladi; yozuvni «Savat» dan tiklash mumkin."
        formMaxWidth="lg"
        formIcon={<GavelIcon />}
        formTitle={(isEdit, row) => (isEdit ? `«${row?.title}» — tahrirlash` : 'Yangi oferta')}
        formSections={FORM_SECTIONS}
        formDescription="Matnni muharrirda yozing yoki Word hujjatidan nusxalab qo‘ying. Havola, rasm va jadval qo‘llab-quvvatlanmaydi — talabgor ekrani kiosk rejimida."
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        toggleField="is_active"
        toggleLabel="Faol"
        exportName="oferta"
        columns={[
          {
            field: 'title', headerName: 'Sarlavha', flex: 1, minWidth: 220,
            renderCell: (params) => (
              <Stack direction="row" spacing={1} alignItems="center" sx={{ height: '100%', minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap>{params.value}</Typography>
                {params.row.deleted_at && <Chip size="small" color="error" variant="outlined" label="O‘chirilgan" />}
              </Stack>
            ),
          },
          {
            // Asosiy savol — "bu matn qaysi testlarda so'raladi?". Biriktirilmagan
            // oferta hech kimga ko'rsatilmaydi, shuning uchun ogohlantirish rangida.
            field: 'exam_list', headerName: 'Testlar', flex: 1, minWidth: 200, sortable: false,
            exportValue: (_value, row) => examNames(row).join(', '),
            renderCell: (params) => {
              const names = examNames(params.row)
              if (!names.length) {
                return (
                  <Box sx={cell}>
                    <Chip size="small" variant="outlined" color="warning" label="Biriktirilmagan" />
                  </Box>
                )
              }
              return (
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ ...cell, minWidth: 0 }} title={names.join('\n')}>
                  <Typography variant="body2" noWrap sx={{ minWidth: 0 }}>{names.slice(0, 2).join(', ')}</Typography>
                  {names.length > 2 && <Chip size="small" label={`+${names.length - 2}`} />}
                </Stack>
              )
            },
          },
          {
            field: 'version', headerName: 'Versiya', width: 90, align: 'center', headerAlign: 'center',
            renderCell: (params) => <Box sx={{ ...cell, justifyContent: 'center' }}>v{params.value}</Box>,
          },
          {
            field: 'updated_at', headerName: 'Oxirgi tahrir', width: 200,
            exportValue: (value) => formatDateTime(value),
            renderCell: (params) => (
              <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
                <Typography variant="body2" noWrap>{formatDateTime(params.value)}</Typography>
                {params.row.updated_by_name && (
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ lineHeight: 1.2 }}>
                    {params.row.updated_by_name}
                  </Typography>
                )}
              </Stack>
            ),
          },
        ]}
        filters={[
          ...(canSeeExams ? [{ name: 'exams', label: 'Test', type: 'select' as const, options: examOptions }] : []),
          {
            name: 'is_active', label: 'Holat', type: 'select',
            options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
          },
        ]}
        fields={fields}
      />
      {detail && (
        <OfferDetailDialog
          row={detail.row}
          onClose={() => setDetail(null)}
          onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
        />
      )}
    </>
  )
}
