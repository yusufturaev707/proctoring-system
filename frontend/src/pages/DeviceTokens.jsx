import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckCircleOutline'
import BlockIcon from '@mui/icons-material/BlockOutlined'

import ResourcePage from '../components/data/ResourcePage'
import ConfirmDialog from '../components/ConfirmDialog'
import { LastSeenCell, useZoneOptions } from './crud/shared'
import { deviceTokens as devicesApi } from '../api/endpoints'
import { useUi } from '../context/UiContext'
import { DEVICE_STATUS_LABEL } from '../utils/labels'

/**
 * Qurilma tokenlari.
 *
 * Bu sahifa xavfsizlik nuqtai nazaridan muhim: tasdiqlanmagan qurilma
 * `/client/candidate/lookup/` ga so'rov yubora olmaydi, ya'ni JSHSHIR
 * qidiruvi yopiq qoladi. Admin har bir kompyuterni qo'lda tasdiqlaydi.
 */
export default function DeviceTokens() {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { options: zoneOptions } = useZoneOptions()

  const [scope, setScope] = useState('pending')
  const [revoking, setRevoking] = useState(null)
  const [approving, setApproving] = useState(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['device-tokens'] })

  const approveMutation = useMutation({
    mutationFn: (id) => devicesApi.approve(id),
    retry: false,
    onSuccess: () => {
      notify('Qurilma tasdiqlandi — endi so‘rov yubora oladi')
      setApproving(null)
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

  const columns = useMemo(
    () => [
      {
        field: 'device_id', headerName: 'Qurilma ID', width: 230, sortable: false,
        renderCell: (params) => (
          <Tooltip title={params.value || ''}>
            <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5 }} noWrap>
              {params.value}
            </Typography>
          </Tooltip>
        ),
      },
      { field: 'computer_code', headerName: 'Kompyuter', width: 145, sortable: false },
      { field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 140, sortable: false },
      { field: 'app_version', headerName: 'Versiya', width: 105, sortable: false },
      {
        field: 'status', headerName: 'Holat', width: 150, sortable: false,
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
      { field: 'last_used_at', headerName: 'Oxirgi faollik', width: 155, renderCell: LastSeenCell },
      {
        field: 'last_ip', headerName: 'Manba IP', width: 135, sortable: false,
        valueGetter: (value) => value || '—',
        description: 'Server so‘rovda ko‘rgan manzil — kirish ruxsati shu bo‘yicha tekshiriladi',
      },
      {
        // Client O'ZI aniqlagan tashqi manzil. Bu ISHONCHSIZ qiymat va
        // kirish ruxsatini hal qilmaydi — u administratorga "bu bino
        // qaysi IP bilan chiqadi" degan savolga javob beradi, ya'ni
        // `AllowedPublicIp` ni to'g'ri to'ldirish uchun kerak. Server
        // bino ichida tursa, `last_ip` LAN manzilini ko'rsatadi va bu
        // ustunsiz tashqi manzilni bilishning yo'li yo'q.
        field: 'reported_public_ip', headerName: 'Tashqi IP', width: 145, sortable: false,
        valueGetter: (value) => value || '—',
        description: 'Client o‘zi aniqlagan tashqi manzil (ma’lumot uchun, ruxsat tekshiruvida ishlatilmaydi)',
      },
      {
        field: 'revoke_reason', headerName: 'Blok sababi', flex: 1, minWidth: 160, sortable: false,
        renderCell: (params) =>
          params.value
            ? <Typography variant="body2" noWrap>{params.value}</Typography>
            : <Typography variant="body2" color="text.disabled">—</Typography>,
      },
    ],
    [],
  )

  return (
    <>
      <ResourcePage
        title="Qurilma tokenlari"
        subtitle="Faqat tasdiqlangan qurilmalar backendga so‘rov yubora oladi"
        queryKey="device-tokens"
        api={devicesApi}
        permission="devices.manage"
        // Token clientning o'zi ro'yxatdan o'tganda tug'iladi — uni
        // paneldan qo'lda yaratib bo'lmaydi. O'chirish ham yo'q: bekor
        // qilingan token ham audit izi sifatida saqlanib qolishi kerak,
        // shuning uchun backend `delete` metodini umuman qabul qilmaydi.
        canCreate={false}
        canEdit={false}
        canDelete={false}
        searchPlaceholder="Qurilma ID, fingerprint yoki versiya…"
        exportName="qurilma-tokenlari"
        columns={columns}
        fields={[]}
        height={620}
        staticParams={scope === 'all' ? {} : { status: scope }}
        filters={[
          { name: 'computer__zone', label: 'Bino', type: 'select', options: zoneOptions },
        ]}
        emptyDescription={
          scope === 'pending'
            ? 'Tasdiqlashni kutayotgan qurilma yo‘q'
            : 'Bu shartlarga mos qurilma topilmadi'
        }
        banner={
          <Alert severity="info">
            Client birinchi ishga tushganda o‘zini ro‘yxatga qo‘yadi, lekin
            <strong> tasdiqlanmaguncha</strong> hech qanday so‘rov qabul qilinmaydi.
            Bu «kimdir uydan client o‘rnatib, JSHSHIR qidiruvi ochdi» stsenariysini yopadi.
          </Alert>
        }
        rowActions={(row) => (
          <Stack direction="row" spacing={0.5}>
            {row.status === 'pending' && (
              <Button size="small" startIcon={<CheckIcon />} onClick={() => setApproving(row)}>
                Tasdiqlash
              </Button>
            )}
            {row.status === 'active' && (
              <Button
                size="small"
                color="error"
                startIcon={<BlockIcon />}
                onClick={() => setRevoking(row)}
              >
                Blok
              </Button>
            )}
          </Stack>
        )}
        headerActions={
          <ToggleButtonGroup
            size="small"
            exclusive
            value={scope}
            onChange={(_, value) => value && setScope(value)}
          >
            <ToggleButton value="pending">Kutilmoqda</ToggleButton>
            <ToggleButton value="active">Faol</ToggleButton>
            <ToggleButton value="revoked">Bloklangan</ToggleButton>
            <ToggleButton value="all">Barchasi</ToggleButton>
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
        details={
          approving ? (
            <Stack spacing={0.5}>
              <Detail label="Qurilma ID" value={approving.device_id} mono />
              <Detail label="Kompyuter" value={approving.computer_code || '—'} />
              <Detail label="Bino" value={approving.zone_name || '—'} />
              <Detail label="Client versiyasi" value={approving.app_version || '—'} />
              <Detail label="Fingerprint" value={approving.hardware_fingerprint || '—'} mono />
            </Stack>
          ) : null
        }
        confirmLabel="Tasdiqlash"
        loading={approveMutation.isPending}
        onConfirm={() => approveMutation.mutate(approving.id)}
        onClose={() => setApproving(null)}
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
    </>
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
