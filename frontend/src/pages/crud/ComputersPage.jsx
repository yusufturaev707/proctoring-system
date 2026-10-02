import { useState } from 'react'
import { Button, Chip, Stack, Tooltip, Typography } from '@mui/material'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import DeleteIcon from '@mui/icons-material/DeleteOutline'

import ResourcePage from '../../components/data/ResourcePage'
import {
  DeviceStatusCell, camerasOfZone, deviceStatusText, useCameraOptions,
  regionZoneFilters, useRegionOptions, useZoneOptions, zonesOfRegion,
} from './shared'
import { computers as computersApi } from '../../api/endpoints'
import ComputerImportDialog from '../../components/computers/ComputerImportDialog'
import ComputerDetailDialog from '../../components/computers/ComputerDetailDialog'
import { useAuth } from '../../context/AuthContext'
import { normalizeMachineUuid } from '../../utils/validation'

/**
 * Machine UUID katagi: boshi va oxiri (oxirgi 12 belgi odatda mashinaga
 * xos qism - Dell'da xizmat yorlig'i), to'liq qiymat tooltip'da.
 * To'liq 36 belgi jadvalni 1440 px ekranda gorizontal surardi.
 */
function MachineUuidCell({ value }) {
  if (!value) {
    return (
      <Tooltip title="UUID yozilmagan — client birinchi ulanganda MAC orqali o‘zi bog‘lanadi yoki qo‘lda kiriting">
        <Chip size="small" variant="outlined" color="warning" label="UUID yo‘q" />
      </Tooltip>
    )
  }
  return (
    <Tooltip title={value}>
      <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5 }} noWrap>
        {`${value.slice(0, 8)}…${value.slice(-12)}`}
      </Typography>
    </Tooltip>
  )
}

export default function ComputersPage() {
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()
  const { options: cameraOptions } = useCameraOptions()
  const { can } = useAuth()
  const [importOpen, setImportOpen] = useState(false)
  // Qator bosilganda - kompyuterning to'liq kartasi. `openEdit` sahifaning
  // o'z formasini ochadi: kartadagi "Tahrirlash" ikkinchi forma yasamaydi.
  const [detail, setDetail] = useState(null)

  return (
    <>
    <ResourcePage
      title="Kompyuterlar"
      subtitle="Imtihon ish stantsiyalari — client faqat ro‘yxatdagi kompyuterdan ulanadi"
      queryKey="computers"
      restorable
      api={computersApi}
      permission="devices.manage"
      searchPlaceholder="Raqam, inventar, UUID, IP yoki MAC…"
      defaultSort={{ field: 'number', sort: 'asc' }}
      defaults={{ is_active: true }}
      getRowLabel={(row) => row?.label || row?.inventory_code}
      onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
      deleteConfirmPhrase
      deleteDescription="Kompyuterga bog‘langan sessiyalar tarixi saqlanib qoladi, lekin qurilma tokeni bekor bo‘ladi."
      // Ustunlar ixcham: inventar kodi, bino va oxirgi signal jadvaldan
      // olingan (inventar kodi tahrirlash formasida qoladi).
      columns={[
        {
          field: 'id', headerName: 'ID', width: 80,
          renderCell: (params) => (
            <Typography variant="body2" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
              {params.value}
            </Typography>
          ),
        },
        {
          // Bino alohida ustun emas — viloyat ustidagi tooltip'da.
          field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 150, sortable: false,
          renderCell: (params) => (
            <Tooltip title={params.row.zone_name || ''}>
              <Typography variant="body2" noWrap>{params.value || '—'}</Typography>
            </Tooltip>
          ),
        },
        {
          field: 'mac_address', headerName: 'MAC', width: 160,
          renderCell: (params) => (
            params.value
              ? <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5 }}>{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled">—</Typography>
          ),
        },
        {
          field: 'ip_address', headerName: 'IP', width: 135,
          renderCell: (params) => params.value || <Typography variant="body2" color="text.disabled">—</Typography>,
        },
        {
          // Xonadagi tartib raqami (stolga yozilgan) - operator mashinani
          // shu bo'yicha qidiradi, standart saralash ham shu. Sarlavha
          // «№» EMAS — u DataTable'ning qator tartib raqami ustuni.
          field: 'number', headerName: 'Raqam', width: 85,
          renderCell: (params) => (
            params.value
              ? <Typography variant="body2" sx={{ fontWeight: 600 }}>{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled">—</Typography>
          ),
        },
        {
          // ASOSIY IDENTIFIKATOR (ona plata SMBIOS UUID).
          field: 'machine_uuid', headerName: 'Machine UUID', width: 190,
          renderCell: MachineUuidCell,
        },
        {
          field: 'cameras_detail', headerName: 'Kameralar', width: 150, sortable: false,
          exportValue: (value) => (value || []).map((item) => item.name).join(', '),
          renderCell: (params) => {
            const list = params.value || []
            if (!list.length) {
              return <Typography variant="body2" color="text.disabled">Biriktirilmagan</Typography>
            }
            return (
              <Stack direction="row" spacing={0.5} alignItems="center">
                <Chip size="small" variant="outlined" label={`${list.length} ta`} />
                <Typography variant="caption" color="text.secondary" noWrap>
                  {list.map((item) => item.name).join(', ')}
                </Typography>
              </Stack>
            )
          },
        },
        {
          field: 'status', headerName: 'Holat', width: 140,
          renderCell: DeviceStatusCell, exportValue: deviceStatusText,
        },
        // «Faol» ustuni `toggleField` dan — ResourcePage uni oxiriga qo'shadi.
      ]}
      // OMMAVIY O'CHIRISH — yumshoq, "Savat"dan tiklanadi. Imtihondagi
      // mashinani server o'tkazib yuboradi (javobda soni). Savatda amal
      // yo'q: u yerdagilar allaqachon o'chirilgan.
      bulkActions={({ filters }) => (filters.deleted === 'only' ? [] : [{
        key: 'delete',
        label: 'O‘chirish',
        icon: <DeleteIcon />,
        color: 'error',
        confirmTitle: 'Kompyuterlarni o‘chirish',
        description: (count) =>
          `${count} ta kompyuter o‘chiriladi va ularning qurilmalari ishlamay qoladi. ` +
          'Hozir imtihon ketayotgan mashinalar o‘tkazib yuboriladi. Yozuvlar «Savat»dan tiklanadi.',
        confirmLabel: 'O‘chirish',
        // Ko'p yozuvda sonni qo'lda yozish — tasodifiy "Enter" ga qarshi.
        confirmPhrase: (count) => (count > 1 ? String(count) : null),
        run: computersApi.bulkDelete,
        success: ({ deleted, skipped_in_exam: skipped }) =>
          `${deleted} ta kompyuter o‘chirildi` + (skipped ? ` · ${skipped} tasi imtihonda — o‘tkazib yuborildi` : ''),
      }])}
      toggleField="is_active"
      // Holat client signali bilan 45 soniyada yangilanadi
      // (`devices.services.touch_presence`) — ro'yxat ham o'zi
      // yangilanishi kerak, aks holda ekrandagi "offline" allaqachon
      // eskirgan bo'ladi.
      refetchInterval={30000}
      exportName="kompyuterlar"
      headerActions={can('devices.manage') && (
        <Button
          variant="outlined"
          startIcon={<UploadFileOutlinedIcon />}
          onClick={() => setImportOpen(true)}
          sx={{ borderRadius: 999 }}
        >
          Excel'dan import
        </Button>
      )}
      formMaxWidth="md"
      filters={[
        ...regionZoneFilters({ regionOptions, zoneOptions }),
        {
          name: 'status', label: 'Holat', type: 'select',
          options: [
            { value: 'online', label: 'Online' },
            { value: 'offline', label: 'Offline' },
            { value: 'in_exam', label: 'Imtihonda' },
            { value: 'blocked', label: 'Bloklangan' },
          ],
        },
      ]}
      fields={[
        // Zanjir: Viloyat -> Bino -> Kameralar.
        //
        // Viloyat `transient` — kompyuterda bunday maydon yo'q va u
        // serverga yuborilmaydi. U faqat binolar ro'yxatini toraytiradi:
        // 400 ta bino ichidan qidirish o'rniga admin avval viloyatni
        // tanlaydi va 15 tadan birini tanlaydi.
        {
          name: 'region', label: 'Viloyat', type: 'select', required: true,
          transient: true, options: regionOptions, colSpan: 6,
          resets: ['zone', 'cameras'],
          helperText: 'Binolar ro‘yxatini toraytirish uchun',
        },
        {
          name: 'zone', label: 'Bino', type: 'select', required: true,
          options: (form) => zonesOfRegion(zoneOptions, form.region),
          colSpan: 6, dependsOn: 'region', resets: ['cameras'],
          blockedText: 'Avval viloyatni tanlang',
          emptyOptionsText: 'Bu viloyatda bino yo‘q — avval bino qo‘shing',
        },
        {
          // IXTIYORIY: hamma markazda ham mashinalar raqamlanmagan.
          // Majburiy qilish mavjud yozuvlarni tahrirlashda
          // to'ldirishga majbur qilardi - to'g'ri javobni esa
          // faqat o'sha markaz biladi.
          name: 'number', label: 'Kompyuter raqami', type: 'number',
          min: 1, max: 32767, colSpan: 6,
          helperText: 'Xonadagi tartib raqami. Bino ichida unikal bo‘lishi kerak',
        },
        {
          name: 'inventory_code', label: 'Inventar kodi', required: true,
          maxLength: 50, pattern: 'slug', colSpan: 6,
          helperText: 'Faqat harf, raqam, `-` va `_`. Tizim bo‘ylab unikal.',
        },
        {
          // IDENTIFIKATOR - (UUID, MAC) JUFTLIGI. UUID ona platadagi SMBIOS
          // UUID; yangi kompyuterda majburiy, UUID'dan oldingi yozuvni
          // tahrirlashda bo'sh qolishi mumkin (client uni MAC orqali o'zi
          // bog'laydi). O'zi unikal EMAS - bir partiyadagi platalarda bir xil.
          name: 'machine_uuid', label: 'Machine UUID',
          pattern: 'uuid', colSpan: 12, maxLength: 38,
          transform: normalizeMachineUuid,
          validate: (value, form) => (
            !value && !form._meta?.isEdit ? 'Machine UUID kiritilishi shart' : null
          ),
          helperText:
            'Mashinada: wmic csproduct get uuid yoki PowerShell ' +
            '(Get-CimInstance Win32_ComputerSystemProduct).UUID. Bir partiyadagi platalarda ' +
            'takrorlanishi mumkin — mashinani UUID va MAC birga belgilaydi.',
        },
        {
          name: 'ip_address', label: 'IP manzil',
          pattern: 'ipv4', colSpan: 6,
          helperText: 'Ixtiyoriy (DHCP tarmog‘ida o‘zgaradi). Berilsa — bino ichida unikal',
        },
        {
          // MAJBURIY (tahrirlashda ham): UUID takrorlanadi va MAC'siz
          // yozuvni bir partiyadagi boshqa mashinalardan ajratib bo'lmaydi.
          name: 'mac_address', label: 'MAC manzil', required: true,
          pattern: 'mac', colSpan: 6,
          helperText: 'Imtihon mashinasidagi yagona faol adapter (Wi-Fi o‘chiq). Tarmoq kartasi almashsa — shu yerda yangilang',
          // MAC serverda ham normalizatsiya qilinadi, lekin bu yerda
          // kiritishni yagona shaklga keltirish dublikat xatolarini kamaytiradi.
          transform: (value) => String(value || '').replace(/-/g, ':').toUpperCase(),
        },
        {
          name: 'cameras', label: 'Biriktirilgan kameralar', type: 'multiselect',
          // FAQAT tanlangan binodagi kameralar. Boshqa binoning kamerasini
          // biriktirish jismonan ma'nosiz — u bu xonani ko'rmaydi.
          options: (form) => camerasOfZone(cameraOptions, form.zone),
          colSpan: 12, section: 'Kuzatuv', dependsOn: 'zone',
          blockedText: 'Avval binoni tanlang',
          emptyOptionsText: 'Bu binoda kamera ro‘yxatga olinmagan',
          helperText:
            'Shu ish stantsiyasini kuzatuvchi IP kameralar. Bo‘sh qoldirilsa, ' +
            'sessiya faqat ekran va veb-kamera bo‘yicha kuzatiladi.',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Kuzatuv' },
      ]}
    />
    <ComputerImportDialog open={importOpen} onClose={() => setImportOpen(false)} />
    {detail && (
      <ComputerDetailDialog
        row={detail.row}
        // "Savat"dagi (o'chirilgan) yozuv tahrirlanmaydi - avval tiklanadi.
        canEdit={can('devices.manage') && !detail.row.deleted_at}
        onEdit={(row) => {
          const { openEdit } = detail
          setDetail(null)
          openEdit(row)
        }}
        onClose={() => setDetail(null)}
      />
    )}
    </>
  )
}
