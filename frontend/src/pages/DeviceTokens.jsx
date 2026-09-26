import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Autocomplete, Badge, Box, Button, Chip, Dialog, DialogActions, DialogContent,
  DialogTitle, IconButton, Stack, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import LockOpenIcon from '@mui/icons-material/LockOpenOutlined'
import LinkIcon from '@mui/icons-material/LinkOutlined'
import DoneAllIcon from '@mui/icons-material/DoneAllOutlined'

import ResourcePage from '../components/data/ResourcePage'
import ConfirmDialog from '../components/ConfirmDialog'
import DeviceDetailSheet from '../components/devices/DeviceDetailSheet'
import { useAuth } from '../context/AuthContext'
import { LastSeenCell, regionZoneFilters, useComputerOptions, useRegionOptions, useZoneOptions } from './crud/shared'
import { deviceTokens as devicesApi } from '../api/endpoints'
import { useUi } from '../context/UiContext'
import { AI_PROFILE_LABEL, computerLabel, DEVICE_STATUS_LABEL } from '../utils/labels'

/**
 * Katakdagi matn — VERTIKAL MARKAZDA.
 *
 * `renderCell` dagi oddiy `Typography` katak tepasiga yopishadi, chiplar
 * esa markazda turadi va qator "sakrab" ko'rinardi (`LastSeenCell` bilan
 * bir xil tuzatish).
 */
function CellText({ value, mono, muted, tooltip = true }) {
  const text = value || '—'
  const node = (
    <Typography
      variant="body2"
      noWrap
      color={!value || muted ? 'text.disabled' : undefined}
      sx={mono ? { fontFamily: 'monospace', fontSize: 12.5 } : undefined}
    >
      {text}
    </Typography>
  )
  return (
    <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', minWidth: 0 }}>
      {tooltip && value ? <Tooltip title={value}>{node}</Tooltip> : node}
    </Box>
  )
}

/**
 * Qurilma tokenlari.
 *
 * Bu sahifa xavfsizlik nuqtai nazaridan muhim: tasdiqlanmagan qurilma
 * `/client/candidate/lookup/` ga so'rov yubora olmaydi, ya'ni JSHSHIR
 * qidiruvi yopiq qoladi. Admin har bir kompyuterni qo'lda tasdiqlaydi.
 *
 * Sahifa BARCHA qurilmalar bilan ochiladi va tab'larda sonlar turadi
 * (`stats/`). Ilgari u «Kutilmoqda» tabida ochilar edi: kutayotgan
 * qurilma bo'lmasa (odatiy holat) administrator bo'sh jadvalni ko'rar
 * va faol yoki bloklangan qurilmalar borligini ham bilmasdi.
 * Kutayotganlar esa yo'qolib ketmaydi — ular uchun alohida banner.
 */
export default function DeviceTokens() {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { options: zoneOptions } = useZoneOptions()
  const { options: regionOptions } = useRegionOptions()

  const [scope, setScope] = useState('all')
  const [revoking, setRevoking] = useState(null)
  const [approving, setApproving] = useState(null)
  const [unblocking, setUnblocking] = useState(null)
  const [rebinding, setRebinding] = useState(null)
  // Qator bosilganda — qurilmaning to'liq kartasi (yon varaq).
  const [detail, setDetail] = useState(null)
  const { can } = useAuth()
  const canManage = can('devices.manage')
  // Varaqdan amal ochilganda varaq yopiladi: amaldan keyin undagi
  // ma'lumot eskiradi, ro'yxat esa yangilanadi.
  const fromSheet = (setter) => (device) => {
    setDetail(null)
    setter(device)
  }

  const { data: stats } = useQuery({
    queryKey: ['device-tokens', 'stats'],
    queryFn: devicesApi.stats,
    refetchInterval: 30000,
  })

  // `['device-tokens']` prefiksi ro'yxatni ham, sonlarni ham yangilaydi.
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['device-tokens'] })

  const approveMutation = useMutation({
    mutationFn: (id) => devicesApi.approve(id),
    retry: false,
    onSuccess: (_, id) => {
      notify(
        unblocking?.id === id
          ? 'Qurilma blokdan chiqarildi'
          : 'Qurilma tasdiqlandi — endi so‘rov yubora oladi',
      )
      setApproving(null)
      setUnblocking(null)
      invalidate()
    },
    onError: notifyError,
  })

  const revokeMutation = useMutation({
    mutationFn: ({ id, reason }) => devicesApi.revoke(id, reason),
    retry: false,
    onSuccess: () => {
      notify('Qurilma bloklandi')
      setRevoking(null)
      invalidate()
    },
    onError: notifyError,
  })

  const rebindMutation = useMutation({
    mutationFn: ({ id, computer }) => devicesApi.update({ id, computer }),
    retry: false,
    onSuccess: () => {
      notify('Qurilma kompyuterga biriktirildi')
      setRebinding(null)
      invalidate()
    },
    onError: notifyError,
  })

  const columns = useMemo(
    () => [
      {
        // "CLIENT HOZIR ISHLAB TURIBDIMI". Qiymat DB'dan emas,
        // Redis'dan keladi (`devices.services.presence_map`) va
        // client har 45 soniyada yuboradigan signal bilan
        // yangilanadi. `status` (tasdiqlangan/bloklangan) BOSHQA
        // savol: u qurilmaga ruxsat berilganini bildiradi, bu esa
        // dastur shu daqiqada ochiqligini.
        field: 'is_online', headerName: 'Client', width: 100, sortable: false,
        exportValue: (value) => (value ? 'Online' : 'Offline'),
        description: 'Client dasturi shu daqiqada ishlab turibdimi (har 45 s signal)',
        renderCell: (params) => {
          const row = params.row || {}
          if (!params.value) {
            return <Chip size="small" variant="outlined" label="Offline" />
          }
          const inExam = row.online_state === 'exam'
          return (
            <Tooltip title={row.online_staff ? `Kirgan xodim: ${row.online_staff}` : ''}>
              <Chip
                size="small"
                color={inExam ? 'info' : 'success'}
                label={inExam ? 'Imtihonda' : 'Online'}
              />
            </Tooltip>
          )
        },
      },
      {
        field: 'computer_code', headerName: 'Kompyuter', width: 130, sortable: false,
        valueGetter: (value, row) => computerLabel(row.computer_number, value),
      },
      {
        field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 100, sortable: false,
        renderCell: (params) => <CellText value={params.value} />,
      },
      {
        field: 'status', headerName: 'Holat', width: 120, sortable: false,
        exportValue: (value) => DEVICE_STATUS_LABEL[value] || value,
        renderCell: (params) => (
          <Chip
            size="small"
            color={
              params.value === 'active' ? 'success' : params.value === 'revoked' ? 'error' : 'warning'
            }
            variant={params.value === 'pending' ? 'filled' : 'outlined'}
            label={DEVICE_STATUS_LABEL[params.value] || params.value}
          />
        ),
      },
      {
        // Apparat profili client O'LCHOVI: u handshake'da keladi va
        // panelda tuzatilmaydi. Ustunning butun ma'nosi shu savolda -
        // "qaysi mashinalarda kuzatuv CPU rejimida ishlayapti?".
        // O'sha mashinalarda chastota past va "hech narsa
        // aniqlanmadi" degan xulosaning vazni ham past, ya'ni ularni
        // imtihon kunidan OLDIN bilish kerak.
        field: 'performance_profile', headerName: 'Apparat profili', width: 120, sortable: false,
        exportValue: (value) => AI_PROFILE_LABEL[value] || value || '',
        description: 'Client apparatga qarab o‘zi tanlaydi — handshake’da yangilanadi',
        renderCell: (params) =>
          params.value
            ? (
              <Chip
                size="small"
                variant="outlined"
                color={params.value === 'high' || params.value === 'medium' ? 'success' : 'warning'}
                label={AI_PROFILE_LABEL[params.value] || params.value}
              />
            )
            : <CellText value="" />,
      },
      { field: 'last_used_at', headerName: 'Oxirgi faollik', width: 120, renderCell: LastSeenCell },
      {
        // UCHTA MANZIL, UCHTA MA'NO (`CLAUDE.md`). Bu — "qaysi MASHINA":
        // client serverga chiqadigan adapterning LAN manzili va
        // sessiyaga ham aynan shu yoziladi. Ilgari ustun yo'q edi, ya'ni
        // panelda mashinani IP bo'yicha topishning yo'li yo'q edi.
        field: 'reported_lan_ip', headerName: 'Mashina IP', width: 132, sortable: false,
        valueGetter: (value) => value || '—',
        description: 'Client o‘zi aytgan LAN manzil — qaysi mashina (sessiyaga ham shu yoziladi)',
      },
    ],
    [],
  )

  const count = (key) => (stats ? stats[key] ?? 0 : null)
  const pending = count('pending') || 0

  return (
    <>
      <ResourcePage
        title="Client qurilmalari"
        subtitle={
          stats
            ? `Jami ${stats.total} ta qurilma · hozir ${stats.online} tasi online`
            : 'Faqat tasdiqlangan qurilmalar backendga so‘rov yubora oladi'
        }
        queryKey="device-tokens"
        api={devicesApi}
        permission="devices.manage"
        // Token clientning o'zi ro'yxatdan o'tganda tug'iladi — uni
        // paneldan qo'lda yaratib bo'lmaydi. O'chirish ham yo'q: bekor
        // qilingan token ham audit izi sifatida saqlanib qolishi kerak,
        // shuning uchun backend `delete` metodini umuman qabul qilmaydi.
        // Tahrirlash formasi ham yo'q: yagona o'zgaradigan maydon —
        // kompyuter, va u alohida amal (qayta biriktirish).
        canCreate={false}
        canEdit={false}
        canDelete={false}
        searchPlaceholder="Qurilma ID, kompyuter, GPU yoki versiya…"
        onRowClick={(params) => setDetail(params.row)}
        // OMMAVIY TASDIQLASH. Yangi bino ulanganda yuzlab client bir
        // vaqtda ro'yxatdan o'tadi va ularni bittalab tasdiqlashga imtihon
        // oldidan jismonan ulgurilmaydi. Faqat KUTAYOTGANLARNI belgilash
        // mumkin: blokdan chiqarish — ongli, bittalab qaror (sabab ko'rinadi).
        isRowSelectable={({ row }) => row.status === 'pending'}
        bulkActions={[{
          key: 'approve',
          label: 'Tasdiqlash',
          icon: <DoneAllIcon />,
          confirmTitle: 'Qurilmalarni tasdiqlash',
          description: (count) =>
            `${count} ta qurilma tasdiqlanadi va talabgor JSHSHIR’ini qidira oladi. ` +
            'Faqat kutayotganlar tasdiqlanadi — bloklanganlarga tegilmaydi. ' +
            'Kompyuterlar aynan imtihon xonalarida turganiga ishonch hosil qiling.',
          confirmLabel: 'Tasdiqlash',
          run: devicesApi.bulkApprove,
          success: ({ approved, skipped }) =>
            `${approved} ta qurilma tasdiqlandi` + (skipped ? ` · ${skipped} tasi kutilmayotgan edi` : ''),
        }]}
        exportName="qurilma-tokenlari"
        columns={columns}
        fields={[]}
        height={620}
        // Holat 45 soniyada o'zgaradi — sahifani qo'lda yangilash
        // kutilmasligi kerak.
        refetchInterval={30000}
        staticParams={scope === 'all' ? {} : { status: scope }}
        filters={[
          ...regionZoneFilters({
            region: 'computer__zone__region', zone: 'computer__zone', regionOptions, zoneOptions,
          }),
          {
            name: 'online',
            label: 'Client holati',
            type: 'select',
            options: [
              { value: 'true', label: 'Online' },
              { value: 'false', label: 'Offline' },
            ],
          },
        ]}
        emptyDescription={
          scope === 'pending'
            ? 'Tasdiqlashni kutayotgan qurilma yo‘q'
            : 'Bu shartlarga mos qurilma topilmadi'
        }
        banner={
          pending > 0 && scope !== 'pending' ? (
            <Alert
              severity="warning"
              action={
                <Button color="inherit" size="small" onClick={() => setScope('pending')}>
                  Ko‘rish
                </Button>
              }
            >
              <strong>{pending} ta qurilma</strong> tasdiqlashni kutmoqda — tasdiqlanmaguncha
              ular JSHSHIR qidira olmaydi va imtihon ocha olmaydi.
            </Alert>
          ) : (
            <Alert severity="info">
              Client birinchi ishga tushganda o‘zini ro‘yxatga qo‘yadi, lekin
              <strong> tasdiqlanmaguncha</strong> hech qanday so‘rov qabul qilinmaydi.
              Bu «kimdir uydan client o‘rnatib, JSHSHIR qidiruvi ochdi» stsenariysini yopadi.
            </Alert>
          )
        }
        actionsWidth={140}
        rowActions={(row) => (
          <Stack direction="row" spacing={0.5} alignItems="center">
            {row.status === 'pending' && (
              <Button size="small" onClick={() => setApproving(row)} sx={{ borderRadius: 999 }}>
                Tasdiqlash
              </Button>
            )}
            {row.status === 'active' && (
              <Tooltip title="Bloklash">
                <IconButton size="small" color="error" aria-label="Bloklash" onClick={() => setRevoking(row)}>
                  <BlockIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            {row.status === 'revoked' && (
              <Tooltip title="Blokdan chiqarish">
                <IconButton size="small" color="primary" aria-label="Blokdan chiqarish" onClick={() => setUnblocking(row)}>
                  <LockOpenIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title="Boshqa kompyuterga biriktirish">
              <IconButton
                size="small"
                aria-label="Boshqa kompyuterga biriktirish"
                onClick={() => setRebinding(row)}
              >
                <LinkIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        )}
        headerActions={
          <ToggleButtonGroup
            size="small"
            exclusive
            value={scope}
            onChange={(_, value) => value && setScope(value)}
          >
            <ToggleButton value="all">Barchasi{countLabel(count('total'))}</ToggleButton>
            <ToggleButton value="pending">
              <Badge
                color="warning"
                variant="dot"
                invisible={!pending}
                sx={{ '& .MuiBadge-dot': { right: -6, top: 2 } }}
              >
                Kutilmoqda{countLabel(count('pending'))}
              </Badge>
            </ToggleButton>
            <ToggleButton value="active">Faol{countLabel(count('active'))}</ToggleButton>
            <ToggleButton value="revoked">Bloklangan{countLabel(count('revoked'))}</ToggleButton>
          </ToggleButtonGroup>
        }
      />

      <ConfirmDialog
        open={Boolean(approving)}
        title="Qurilmani tasdiqlash"
        description={
          'Tasdiqlangandan so‘ng bu kompyuter talabgor JSHSHIR’ini qidira oladi va ' +
          'imtihon sessiyasini boshlashi mumkin. Kompyuter aynan imtihon xonasida ' +
          'turganiga ishonch hosil qiling.'
        }
        details={approving ? <DeviceDetails device={approving} /> : null}
        confirmLabel="Tasdiqlash"
        loading={approveMutation.isPending}
        onConfirm={() => approveMutation.mutate(approving.id)}
        onClose={() => setApproving(null)}
      />

      <ConfirmDialog
        open={Boolean(unblocking)}
        title="Blokdan chiqarish"
        description={
          'Qurilma yana so‘rov yubora oladi. Blok sababi bartaraf etilganiga ishonch ' +
          'hosil qiling — blok tarixi audit jurnalida qoladi.'
        }
        details={
          unblocking ? (
            <Stack spacing={0.5}>
              <DeviceDetails device={unblocking} />
              <Detail label="Blok sababi" value={unblocking.revoke_reason || '—'} />
            </Stack>
          ) : null
        }
        confirmLabel="Blokdan chiqarish"
        loading={approveMutation.isPending}
        onConfirm={() => approveMutation.mutate(unblocking.id)}
        onClose={() => setUnblocking(null)}
      />

      <ConfirmDialog
        open={Boolean(revoking)}
        title="Qurilmani bloklash"
        description={`${revoking?.device_id || ''} — bu qurilmadan kelgan barcha so‘rovlar rad etiladi.`}
        confirmLabel="Bloklash"
        color="error"
        requireReason
        loading={revokeMutation.isPending}
        onConfirm={(reason) => revokeMutation.mutate({ id: revoking.id, reason })}
        onClose={() => setRevoking(null)}
      />

      <DeviceDetailSheet
        device={detail}
        canManage={canManage}
        onClose={() => setDetail(null)}
        onApprove={fromSheet(setApproving)}
        onRevoke={fromSheet(setRevoking)}
        onUnblock={fromSheet(setUnblocking)}
        onRebind={fromSheet(setRebinding)}
      />

      {rebinding && (
        <RebindDialog
          device={rebinding}
          loading={rebindMutation.isPending}
          onSave={(computer) => rebindMutation.mutate({ id: rebinding.id, computer })}
          onClose={() => setRebinding(null)}
        />
      )}
    </>
  )
}

const countLabel = (value) => (value == null ? '' : ` · ${value}`)

/**
 * Qurilmani boshqa kompyuterga biriktirish.
 *
 * Asosiy holat — mashina obrazi ko'chirilgan: `device_id` diskdagi fayl
 * bilan birga ko'chadi va handshake'dagi MAC tekshiruvi `mismatch`
 * beradi (client "Davom etish" ni bloklaydi). To'g'ri javob — qurilmani
 * client HAQIQATAN turgan kompyuterga o'tkazish. Server viloyat
 * doirasini va hisobdan chiqarilgan mashinani o'zi tekshiradi.
 */
function RebindDialog({ device, loading, onSave, onClose }) {
  const { options } = useComputerOptions()
  const [value, setValue] = useState(null)
  const current = options.find((option) => option.value === device.computer) || null
  const selected = value ?? current

  return (
    <Dialog open onClose={loading ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Kompyuterga biriktirish</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            Mashina obrazi ko‘chirilganda client boshqa kompyuterning qurilma ID’si bilan
            keladi va MAC tekshiruvi «boshqa kompyuter» deb to‘xtatadi. Qurilmani client
            aslida turgan kompyuterga biriktiring.
          </Typography>
          <DeviceDetails device={device} />
          <Autocomplete
            options={options}
            value={selected}
            onChange={(_, option) => setValue(option)}
            isOptionEqualToValue={(option, item) => option.value === item.value}
            getOptionLabel={(option) => option?.label || ''}
            renderInput={(params) => <TextField {...params} label="Kompyuter" autoFocus />}
            noOptionsText="Kompyuter topilmadi"
          />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={loading}>Bekor qilish</Button>
        <Button
          variant="contained"
          disabled={loading || !selected || selected.value === device.computer}
          onClick={() => onSave(selected.value)}
        >
          Biriktirish
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function DeviceDetails({ device }) {
  return (
    <Stack spacing={0.5}>
      <Detail label="Qurilma ID" value={device.device_id} mono />
      <Detail
        label="Hozirgi kompyuter"
        value={computerLabel(device.computer_number, device.computer_code) || '—'}
      />
      <Detail label="Bino" value={device.zone_name || '—'} />
      <Detail label="Mashina IP" value={device.reported_lan_ip || '—'} />
      <Detail label="Client versiyasi" value={device.app_version || '—'} />
      <Detail label="Fingerprint" value={device.hardware_fingerprint || '—'} mono />
    </Stack>
  )
}

function Detail({ label, value, mono }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography
        variant="body2"
        sx={{ fontFamily: mono ? 'monospace' : undefined, wordBreak: 'break-all' }}
      >
        {value}
      </Typography>
    </Box>
  )
}
