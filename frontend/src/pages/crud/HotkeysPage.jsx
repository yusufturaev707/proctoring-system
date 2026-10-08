import { useState } from 'react'
import { Box, Stack, Tooltip, Typography } from '@mui/material'
import KeyboardIcon from '@mui/icons-material/KeyboardOutlined'
import LabelIcon from '@mui/icons-material/LabelOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'
import ErrorIcon from '@mui/icons-material/ErrorOutline'

import ResourcePage from '../../components/data/ResourcePage'
import HotkeyDetailDialog from '../../components/controls/HotkeyDetailDialog'
import HotkeyInput from '../../components/controls/HotkeyInput'
import { Keycaps, ProfilesCell } from '../../components/controls/ControlBits'
import { hotkeys as hotkeysApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { normalizeHotkey, parseHotkey } from '../../utils/hotkeys'

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

const FORM_SECTIONS = {
  'Kombinatsiya': { icon: KeyboardIcon, description: 'Client klaviatura qulfi taqqoslaydigan kod' },
  'Nomi': { icon: LabelIcon, description: 'Panel va sozlama profilida ko‘rinadigan nom' },
  'Holat': { icon: ToggleIcon },
}

const renderCode = ({ value, onChange, disabled, error }) => (
  <HotkeyInput value={value} onChange={onChange} disabled={disabled} error={error} />
)

/**
 * Bloklanadigan klaviatura kombinatsiyalari.
 *
 * Client `code` ni past darajali hook'da taqqoslaydi va TANIMAGAN kodni
 * bloklamaydi — shuning uchun kod client lug'ati bilan tekshiriladi
 * (`utils/hotkeys.js`, server `controls/hotkeys.py`). Yozuv o'zi hech
 * narsa qilmaydi: client faqat sozlama profiliga kiritilganini oladi
 * («Profillar» ustuni).
 */
export default function HotkeysPage() {
  const { canShared } = useAuth()
  const canManage = canShared('controls.manage')
  const [detail, setDetail] = useState(null)

  return (
    <>
      <ResourcePage
        // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
        shared
        title="Tezkor tugmalar"
        subtitle="Imtihon paytida bloklanadigan klaviatura kombinatsiyalari — qatorni bosing, to‘liq karta ochiladi"
        queryKey="hotkeys"
        api={hotkeysApi}
        permission="controls.manage"
        searchPlaceholder="Nomi yoki kodi bo‘yicha…"
        defaultSort={{ field: 'name', sort: 'asc' }}
        defaults={{ is_active: true }}
        getRowLabel={(row) => row?.name}
        deleteDescription="Kombinatsiya o‘chirilsa, u barcha profillardan chiqadi va client uni endi bloklamaydi."
        formMaxWidth="sm"
        formIcon={<KeyboardIcon />}
        formTitle={(isEdit, row) => (isEdit ? `«${row?.name}» — tahrirlash` : 'Yangi tezkor tugma')}
        formSections={FORM_SECTIONS}
        formDescription="Yangi yozuvni «Client sozlamalari» dagi profilga qo‘shmaguncha client uni bloklamaydi."
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        columns={[
          {
            field: 'code', headerName: 'Kombinatsiya', flex: 1, minWidth: 220,
            renderCell: (params) => {
              const { error } = parseHotkey(params.value)
              return (
                <Stack direction="row" spacing={1} alignItems="center" sx={{ ...cell, minWidth: 0 }}>
                  <Keycaps code={params.value} size="small" />
                  {error && (
                    <Tooltip title={`Client tanimaydi: ${error}`}>
                      <ErrorIcon fontSize="small" color="error" />
                    </Tooltip>
                  )}
                </Stack>
              )
            },
          },
          {
            field: 'name', headerName: 'Nomi', flex: 1, minWidth: 170,
            renderCell: (params) => (
              <Typography variant="body2" fontWeight={600} noWrap sx={cell}>{params.value}</Typography>
            ),
          },
          {
            field: 'profiles', headerName: 'Profillar', flex: 1, minWidth: 200, sortable: false,
            exportValue: (value) => (value || []).map((item) => item.name).join(', '),
            renderCell: (params) => (
              <Box sx={{ ...cell, minWidth: 0 }}><ProfilesCell profiles={params.value} /></Box>
            ),
          },
        ]}
        toggleField="is_active"
        exportName="tezkor-tugmalar"
        filters={[
          {
            name: 'is_active', label: 'Holat', type: 'select',
            options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
          },
        ]}
        fields={[
          {
            name: 'code', type: 'custom', colSpan: 12, section: 'Kombinatsiya',
            render: renderCode,
            // Server bilan bir xil shakl (`clean_hotkey`): PATCH'da
            // `Alt+Tab` va `alt+tab` "o'zgarish" deb sanalmaydi.
            transform: normalizeHotkey,
            validate: (value) => parseHotkey(value).error || null,
          },
          {
            name: 'name', label: 'Nomi', required: true, maxLength: 100, colSpan: 12, section: 'Nomi',
            helperText: 'Masalan: “Oyna almashtirish (Alt+Tab)”',
          },
          {
            name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Holat',
            helperText: 'O‘chirilsa — profilda tursa ham client’ga yuborilmaydi',
          },
        ]}
      />

      {detail && (
        <HotkeyDetailDialog
          row={detail.row}
          onClose={() => setDetail(null)}
          onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
        />
      )}
    </>
  )
}

