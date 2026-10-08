import { useState } from 'react'
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import AppsIcon from '@mui/icons-material/AppsOutlined'
import FingerprintIcon from '@mui/icons-material/FingerprintOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import ShieldIcon from '@mui/icons-material/GppMaybeOutlined'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import ChipListInput from '../../components/controls/ChipListInput'
import RdpObjectDetailDialog from '../../components/controls/RdpObjectDetailDialog'
import { ProfilesCell } from '../../components/controls/ControlBits'
import { CATEGORY_META, CATEGORY_OPTIONS, SIGNS, signsOf } from '../../components/controls/rdpMeta'
import { rdpObjects as rdpObjectsApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { EVENT_LABEL } from '../../utils/labels'

/**
 * Aniqlanishi kerak bo'lgan dasturlar (AnyDesk, TeamViewer, VirtualBox...).
 *
 * BU RO'YXAT CLIENT KATALOGINI ALMASHTIRMAYDI, QO'SHADI. Client'da
 * ichki katalog bor (`client/services/threat_rules.py`) va u serverdan
 * mustaqil ishlaydi — ya'ni bu jadval bo'sh bo'lsa ham himoya bor.
 * Bu yerga faqat katalogda YO'Q dastur yoziladi: yangi dasturni 500
 * mashinaga tarqatish uchun client'ni qayta yig'ish shart emas.
 *
 * FAQAT JARAYON NOMI YETARLI EMAS. `AnyDesk.exe` ni `notepad.exe` deb
 * qayta nomlash bir soniyalik ish, ya'ni nom bo'yicha qidiruv eng
 * sodda chetlab o'tishga ham dosh bermaydi. Qolgan maydonlar aynan
 * shuning uchun: imzo, `OriginalFilename`, xizmat nomi va port
 * faylni qayta nomlaganda O'ZGARMAYDI. Forma va karta ularni client'ning
 * ishonchlilik tartibida ko'rsatadi (`rdpMeta.SIGNS`).
 */

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

const FORM_SECTIONS = {
  'Dastur': { icon: AppsIcon, description: 'Nomi panelda va proktor ekranidagi hodisada ko‘rinadi' },
  'Aniqlash belgilari': {
    icon: FingerprintIcon,
    description: 'Ishonchlilik tartibida. Kamida bittasi shart — imzo yoki asl fayl nomi faylni qayta nomlaganda ham ishlaydi',
  },
  'Xulq': { icon: TuneIcon, description: 'Topilgan dasturni yopib bo‘lmasa nima bo‘ladi' },
}

/** Belgi maydoni: Enter yoki vergul bilan qo'shiladigan chip'lar. */
const signField = (sign) => ({
  name: sign.name,
  type: 'custom',
  colSpan: 12,
  section: 'Aniqlash belgilari',
  render: ({ value, onChange, disabled, error }) => (
    <ChipListInput
      value={value}
      onChange={onChange}
      disabled={disabled}
      error={error}
      numeric={sign.numeric}
      label={`${sign.label} · ${sign.strength}`}
      placeholder={`Masalan: ${sign.placeholder} — Enter bilan qo‘shing`}
      helperText={sign.help}
    />
  ),
})

/** Server qoidasining nusxasi (`RdpObjectSerializer.validate`) — xato shu maydonga. */
const atLeastOneSign = (_value, form) =>
  SIGNS.some((sign) => (form[sign.name] || []).length > 0)
    ? null
    : 'Kamida bitta aniqlash belgisi kiriting — belgisiz yozuvni client topa olmaydi'

export default function RdpObjectsPage() {
  const { canShared } = useAuth()
  const canManage = canShared('controls.manage')
  const [detail, setDetail] = useState(null)

  return (
    <>
      <ResourcePage
        // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
        shared
        title="Taqiqlangan dasturlar"
        subtitle="Masofaviy boshqaruv, virtualizatsiya va yordamchi vositalar — qatorni bosing, to‘liq karta ochiladi"
        queryKey="rdp-objects"
        api={rdpObjectsApi}
        permission="controls.manage"
        searchPlaceholder="Nomi yoki kodi bo‘yicha…"
        defaultSort={{ field: 'name', sort: 'asc' }}
        defaults={{
          is_active: true,
          is_blocking: false,
          category: 'remote',
          process_names: [],
          publishers: [],
          original_filenames: [],
          products: [],
          service_names: [],
          ports: [],
        }}
        getRowLabel={(row) => row?.name}
        deleteDescription="Dastur o‘chirilsa, u barcha profillardan chiqadi va client uni endi aniqlamaydi (ichki katalogdagi dasturlar bundan mustasno)."
        formMaxWidth="md"
        formIcon={<ShieldIcon />}
        formTitle={(isEdit, row) => (isEdit ? `«${row?.name}» — tahrirlash` : 'Yangi taqiqlangan dastur')}
        formSections={FORM_SECTIONS}
        formDescription="Yangi yozuvni «Client sozlamalari» dagi profilga qo‘shmaguncha client uni qidirmaydi."
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        columns={[
          {
            field: 'name', headerName: 'Dastur', flex: 1, minWidth: 180,
            renderCell: (params) => (
              <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap>{params.value}</Typography>
                <Typography variant="caption" color="text.secondary" noWrap sx={{ fontFamily: 'monospace', lineHeight: 1.2 }}>
                  {params.row.code}
                </Typography>
              </Stack>
            ),
          },
          {
            field: 'category', headerName: 'Toifa', width: 188,
            exportValue: (value) => CATEGORY_META[value]?.label || value,
            renderCell: (params) => {
              const meta = CATEGORY_META[params.value] || CATEGORY_META.remote
              const Icon = meta.icon
              return (
                <Box sx={cell}>
                  <Tooltip title={`Hodisa: ${EVENT_LABEL[meta.event] || meta.event}`}>
                    <Chip size="small" variant="outlined" icon={<Icon />} label={meta.label} />
                  </Tooltip>
                </Box>
              )
            },
          },
          {
            // Ixcham: belgilar SONI va kuchi; ro'yxat — tooltip va kartada
            // (1440 px da jadval surilmasin).
            field: 'signs', headerName: 'Belgilar', width: 150, sortable: false,
            valueGetter: (_value, row) => signsOf(row),
            exportValue: (_value, row) => signsOf(row).present.map((sign) => sign.short).join(', '),
            renderCell: (params) => {
              const { present, none, weakOnly } = params.value
              const title = present
                .map((sign) => `${sign.short}: ${(params.row[sign.name] || []).join(', ')}`)
                .join(' · ')
              let chip
              if (none) {
                chip = <Chip size="small" color="error" variant="outlined" icon={<WarningIcon />} label="Yo‘q" />
              } else if (weakOnly) {
                chip = <Chip size="small" color="warning" variant="outlined" icon={<WarningIcon />} label="Faqat fayl nomi" />
              } else {
                chip = (
                  <Chip
                    size="small"
                    label={`${present.length} ta belgi`}
                    sx={{ bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer' }}
                  />
                )
              }
              return (
                <Box sx={cell}>
                  <Tooltip title={none ? 'Client bu dasturni aniqlay olmaydi' : title}>{chip}</Tooltip>
                </Box>
              )
            },
          },
          {
            field: 'profiles', headerName: 'Profillar', width: 160, sortable: false,
            exportValue: (value) => (value || []).map((item) => item.name).join(', '),
            renderCell: (params) => (
              <Box sx={{ ...cell, minWidth: 0 }}><ProfilesCell profiles={params.value} /></Box>
            ),
          },
          {
            field: 'is_blocking', headerName: 'Yopilmasa', width: 120, sortable: false,
            exportValue: (value) => (value ? 'To‘sadi' : 'Ogohlantiradi'),
            renderCell: (params) => (
              <Box sx={cell}>
                {params.value
                  ? <Chip size="small" color="error" icon={<BlockIcon />} label="To‘sadi" />
                  : <Typography variant="body2" color="text.secondary">Ogohlantiradi</Typography>}
              </Box>
            ),
          },
        ]}
        toggleField="is_active"
        exportName="taqiqlangan-dasturlar"
        filters={[
          { name: 'category', label: 'Toifa', type: 'select', options: CATEGORY_OPTIONS },
          {
            name: 'is_active', label: 'Holat', type: 'select',
            options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
          },
        ]}
        fields={[
          { name: 'name', label: 'Nomi', required: true, maxLength: 100, colSpan: 6, section: 'Dastur' },
          {
            name: 'code', label: 'Kod', required: true, maxLength: 100, colSpan: 6, section: 'Dastur',
            transform: (value) => String(value || '').trim().toLowerCase(),
            helperText: 'Barqaror kalit, masalan “anydesk” — keyin o‘zgartirmang',
          },
          {
            name: 'category', label: 'Toifa', type: 'select', required: true, colSpan: 12, section: 'Dastur',
            options: CATEGORY_OPTIONS,
            helperText: (_isEdit, form) => {
              const meta = CATEGORY_META[form?.category]
              return meta
                ? `Topilganda proktor ekranida «${EVENT_LABEL[meta.event] || meta.event}» hodisasi chiqadi`
                : 'Hodisa turini belgilaydi'
            },
          },
          { ...signField(SIGNS[0]), validate: atLeastOneSign },
          ...SIGNS.slice(1).map(signField),
          {
            name: 'is_blocking', label: 'Yopib bo‘lmasa imtihonni to‘sadi', type: 'boolean', colSpan: 6, section: 'Xulq',
            helperText: 'O‘chiq: dastur baribir yopiladi va hodisa yoziladi, faqat imtihon to‘xtamaydi. Noto‘g‘ri yozuv butun markazni to‘xtatishi mumkin',
          },
          {
            name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Xulq',
            helperText: 'O‘chirilsa — profilda tursa ham client’ga yuborilmaydi',
          },
        ]}
      />

      {detail && (
        <RdpObjectDetailDialog
          row={detail.row}
          onClose={() => setDetail(null)}
          onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
        />
      )}
    </>
  )
}
