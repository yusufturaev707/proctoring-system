import { useMemo, useState } from 'react'
import {
  Alert, Box, Button, Chip, Drawer, Divider, IconButton, Stack, Tooltip, Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import OpenIcon from '@mui/icons-material/OpenInNewOutlined'

import ResourcePage from '../components/data/ResourcePage'
import { useUserOptions } from './crud/shared'
import { auditLogs as auditApi } from '../api/endpoints'
import { AUDIT_ACTION_LABEL, formatDateTime } from '../utils/labels'

/**
 * Chetlashtirish, o'chirish va qurilma bloklash — qaytarib bo'lmaydigan
 * yoki talabgor huquqiga bevosita ta'sir qiluvchi amallar. Ular ro'yxatda
 * ajralib turishi kerak: apellyatsiyani tekshirayotgan odam aynan shu
 * qatorlarni qidiradi.
 */
const DANGEROUS = new Set([
  'session_terminate', 'delete', 'device_revoke', 'identity_reject',
])

const OBJECT_TYPES = [
  'ExamSession', 'TechnicalProblem', 'User', 'Role', 'Region', 'Zone',
  'Computer', 'Camera', 'DeviceToken', 'Exam', 'ExamSchedule', 'Setting',
]

export default function AuditLogs() {
  const { options: userOptions } = useUserOptions()
  const [detail, setDetail] = useState(null)

  const columns = useMemo(
    () => [
      {
        field: 'created_at', headerName: 'Vaqt', width: 175,
        valueGetter: (value) => formatDateTime(value),
      },
      { field: 'actor_username', headerName: 'Kim', width: 155, sortable: false },
      {
        field: 'action', headerName: 'Amal', width: 190, sortable: false,
        exportValue: (value, row) => AUDIT_ACTION_LABEL[value] || row.action_display || value,
        renderCell: (params) => (
          <Chip
            size="small"
            color={DANGEROUS.has(params.value) ? 'error' : 'default'}
            variant={DANGEROUS.has(params.value) ? 'filled' : 'outlined'}
            label={AUDIT_ACTION_LABEL[params.value] || params.row.action_display || params.value}
          />
        ),
      },
      { field: 'object_type', headerName: 'Obyekt', width: 145, sortable: false },
      { field: 'object_id', headerName: 'ID', width: 85, sortable: false },
      {
        field: 'ip_address', headerName: 'IP', width: 135, sortable: false,
        valueGetter: (value) => value || '—',
      },
      {
        field: 'meta', headerName: 'Tafsilot', flex: 1, minWidth: 220, sortable: false,
        exportValue: (value) => (Object.keys(value || {}).length ? JSON.stringify(value) : ''),
        renderCell: (params) => {
          const text = Object.keys(params.value || {}).length ? JSON.stringify(params.value) : ''
          if (!text) return <Typography variant="body2" color="text.disabled">—</Typography>
          return (
            <Tooltip title="To‘liq ko‘rish uchun bosing">
              <Typography
                variant="caption"
                sx={{ fontFamily: 'monospace', cursor: 'pointer' }}
                noWrap
                onClick={(event) => {
                  event.stopPropagation()
                  setDetail(params.row)
                }}
              >
                {text}
              </Typography>
            </Tooltip>
          )
        },
      },
      {
        field: '__open', headerName: '', width: 56, sortable: false, align: 'right',
        renderCell: (params) => (
          <Tooltip title="Yozuv tafsiloti">
            <IconButton
              size="small"
              onClick={(event) => {
                event.stopPropagation()
                setDetail(params.row)
              }}
            >
              <OpenIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ),
      },
    ],
    [],
  )

  return (
    <>
      <ResourcePage
        title="Audit jurnali"
        subtitle="«Kim, kimni, qachon, qaysi IP dan» — apellyatsiya va sud uchun"
        queryKey="audit-logs"
        api={auditApi}
        // Audit yozuvi o'zgartirilmaydi va o'chirilmaydi — aks holda u
        // dalil sifatida qiymatini yo'qotadi. Backend ham buni faqat
        // `ReadOnlyModelViewSet` qilib beradi; bu yerdagi bayroqlar
        // shunchaki UI'ni shunga moslaydi.
        permission="audit.view"
        canCreate={false}
        canEdit={false}
        canDelete={false}
        searchPlaceholder="Login, obyekt ID yoki IP…"
        exportName="audit"
        columns={columns}
        height={640}
        emptyDescription="Tanlangan shartlarga mos audit yozuvi topilmadi"
        filters={[
          {
            name: 'action', label: 'Amal turi', type: 'select',
            options: Object.entries(AUDIT_ACTION_LABEL).map(([value, label]) => ({ value, label })),
          },
          { name: 'actor', label: 'Kim', type: 'select', options: userOptions },
          {
            name: 'object_type', label: 'Obyekt turi', type: 'select',
            options: OBJECT_TYPES.map((value) => ({ value, label: value })),
          },
          { name: 'date_from', label: 'Sanadan', type: 'date' },
          { name: 'date_to', label: 'Sanagacha', type: 'date' },
        ]}
        fields={[]}
      />

      <Drawer
        anchor="right"
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        slotProps={{ paper: { sx: { width: { xs: '100%', sm: 480 } } } }}
      >
        {detail && (
          <Box sx={{ p: 3 }}>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
              <Typography variant="h6">Audit yozuvi #{detail.id}</Typography>
              <IconButton onClick={() => setDetail(null)} aria-label="Yopish">
                <CloseIcon />
              </IconButton>
            </Stack>

            {DANGEROUS.has(detail.action) && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                Bu qaytarib bo‘lmaydigan amal. Sabab va ijrochi quyida qayd etilgan.
              </Alert>
            )}

            <Stack divider={<Divider flexItem />} spacing={1.5}>
              <Row label="Vaqt" value={formatDateTime(detail.created_at)} />
              <Row label="Ijrochi" value={detail.actor_username || '—'} />
              <Row
                label="Amal"
                value={AUDIT_ACTION_LABEL[detail.action] || detail.action_display || detail.action}
              />
              <Row label="Obyekt" value={`${detail.object_type || '—'} #${detail.object_id || '—'}`} />
              <Row label="IP manzil" value={detail.ip_address || '—'} />
              <Row label="So‘rov ID" value={detail.request_id || '—'} mono />
              <Row label="User-Agent" value={detail.user_agent || '—'} wrap />
            </Stack>

            <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mt: 3 }}>
              Qo‘shimcha ma’lumot
            </Typography>
            <Box
              component="pre"
              sx={{
                mt: 1, p: 1.5, borderRadius: 2, bgcolor: 'surface.subtle',
                fontSize: 12.5, overflow: 'auto', maxHeight: 320, m: 0,
                fontFamily: 'monospace',
              }}
            >
              {JSON.stringify(detail.meta || {}, null, 2)}
            </Box>

            {detail.object_type === 'ExamSession' && detail.object_id && (
              <Button
                fullWidth
                variant="outlined"
                sx={{ mt: 2 }}
                href={`/sessions/${detail.object_id}`}
              >
                Sessiyani ochish
              </Button>
            )}
          </Box>
        )}
      </Drawer>
    </>
  )
}

function Row({ label, value, mono, wrap }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography
        variant="body2"
        sx={{
          fontFamily: mono ? 'monospace' : undefined,
          wordBreak: wrap ? 'break-word' : undefined,
        }}
      >
        {value}
      </Typography>
    </Box>
  )
}
