import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Alert, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Stack, Switch, TextField, ToggleButton, ToggleButtonGroup,
  Tooltip, Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckCircleOutline'

import ResourcePage from '../components/data/ResourcePage'
import { regionZoneFilters, useRegionOptions, useZoneOptions } from './crud/shared'
import { technicalProblems as tpApi } from '../api/endpoints'
import { useUi } from '../context/UiContext'
import { TP_KIND_LABEL, formatDateTime, fromNow } from '../utils/labels'

const KIND_OPTIONS = Object.entries(TP_KIND_LABEL).map(([value, label]) => ({ value, label }))

const EMPTY_DECISION = { overtime_minutes: 0, note: '', resume_session: true }

export default function TechnicalProblems() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { notify, notifyError } = useUi()
  const { options: zoneOptions } = useZoneOptions()
  const { options: regionOptions } = useRegionOptions()

  const [scope, setScope] = useState('unresolved')
  const [resolving, setResolving] = useState(null)
  const [decision, setDecision] = useState(EMPTY_DECISION)

  const resolveMutation = useMutation({
    mutationFn: ({ id, payload }) => tpApi.resolve(id, payload),
    retry: false,
    onSuccess: () => {
      notify('Qaror qabul qilindi')
      setResolving(null)
      queryClient.invalidateQueries({ queryKey: ['technical-problems'] })
    },
    onError: notifyError,
  })

  const openDecision = (row) => {
    setDecision(EMPTY_DECISION)
    setResolving(row)
  }

  const columns = useMemo(
    () => [
      { field: 'candidate_name', headerName: 'Talabgor', flex: 1.3, minWidth: 180, sortable: false },
      { field: 'zone_name', headerName: 'Bino', width: 130, sortable: false },
      {
        field: 'kind', headerName: 'Turi', width: 120, sortable: false,
        exportValue: (value) => TP_KIND_LABEL[value] || value,
        renderCell: (params) => (
          <Chip size="small" variant="outlined" label={TP_KIND_LABEL[params.value] || params.value} />
        ),
      },
      { field: 'description', headerName: 'Tavsif', flex: 1.5, minWidth: 200, sortable: false },
      {
        field: 'started_at', headerName: 'Boshlangan', width: 165,
        // Eksportga nisbiy vaqt («2 soat oldin») emas, aniq sana ketadi —
        // fayl keyinroq ochilganda «2 soat oldin» ma'nosini yo'qotadi.
        exportValue: (value) => formatDateTime(value),
        // Kutish vaqti bu ekranda eng muhim ustun: operator eng uzoq
        // kutgan talabgorni birinchi ko'rishi kerak. Aniq sana tooltipda.
        renderCell: (params) => (
          <Tooltip title={formatDateTime(params.value)}>
            <Typography variant="body2">{fromNow(params.value)}</Typography>
          </Tooltip>
        ),
      },
      {
        field: 'overtime', headerName: 'Qo‘shimcha vaqt', width: 140, sortable: false,
        valueGetter: (value) => (value ? String(value).split('.')[0] : '—'),
      },
      {
        field: 'is_resolved', headerName: 'Holat', width: 130, sortable: false,
        exportValue: (value) => (value ? 'Hal qilingan' : 'Kutilmoqda'),
        renderCell: (params) => (
          <Chip
            size="small"
            color={params.value ? 'success' : 'warning'}
            variant={params.value ? 'outlined' : 'filled'}
            label={params.value ? 'Hal qilingan' : 'Kutilmoqda'}
          />
        ),
      },
      {
        field: 'resolved_by_name', headerName: 'Kim hal qildi', width: 145, sortable: false,
        valueGetter: (value) => value || '—',
      },
    ],
    [],
  )

  return (
    <>
      <ResourcePage
        title="Texnik muammolar"
        subtitle="Qo‘shimcha vaqt berish qarorlari shu yerda qayd etiladi"
        queryKey="technical-problems"
        api={tpApi}
        permission="technical.resolve"
        // Muammoni client yoki operator boshlaydi, panel esa unga QAROR
        // qabul qiladi. Shuning uchun bu yerda "qo'shish" yo'q — qo'lda
        // yaratilgan yozuv hech qanday sessiyaga bog'lanmagan bo'lardi.
        canCreate={false}
        canEdit={false}
        canDelete={false}
        searchPlaceholder="Talabgor familiyasi yoki tavsif…"
        defaultSort={{ field: 'started_at', sort: 'desc' }}
        exportName="texnik-muammolar"
        columns={columns}
        fields={[]}
        height={620}
        // Toggle qaysi to'plam ko'rsatilishini belgilaydi; `staticParams`
        // orqali uzatilgani uchun uni o'zgartirish `useResource` ichida
        // yangi query kalitini beradi va sahifa avtomatik 1 ga qaytadi.
        staticParams={
          scope === 'unresolved'
            ? { unresolved: 'true' }
            : scope === 'resolved'
              ? { is_resolved: 'true' }
              : {}
        }
        filters={[
          { name: 'kind', label: 'Turi', type: 'select', options: KIND_OPTIONS },
          ...regionZoneFilters({
            region: 'session__zone__region', zone: 'session__zone', regionOptions, zoneOptions,
          }),
        ]}
        emptyDescription={
          scope === 'unresolved'
            ? 'Hal qilinmagan texnik muammo yo‘q — hammasi joyida'
            : 'Bu shartlarga mos yozuv topilmadi'
        }
        onRowClick={(params) => params.row.session && navigate(`/sessions/${params.row.session}`)}
        rowActions={(row) =>
          row.is_resolved ? null : (
            <Tooltip title="Qaror qabul qilish">
              <Button
                size="small"
                startIcon={<CheckIcon />}
                onClick={(event) => {
                  event.stopPropagation()
                  openDecision(row)
                }}
              >
                Qaror
              </Button>
            </Tooltip>
          )
        }
        headerActions={
          <ToggleButtonGroup
            size="small"
            exclusive
            value={scope}
            onChange={(_, value) => value && setScope(value)}
          >
            <ToggleButton value="unresolved">Kutilmoqda</ToggleButton>
            <ToggleButton value="resolved">Hal qilingan</ToggleButton>
            <ToggleButton value="all">Barchasi</ToggleButton>
          </ToggleButtonGroup>
        }
      />

      <Dialog
        open={Boolean(resolving)}
        onClose={resolveMutation.isPending ? undefined : () => setResolving(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Texnik muammo bo‘yicha qaror</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2.5}>
            {resolving && (
              <Alert severity="info" icon={false}>
                <Typography variant="subtitle2">{resolving.candidate_name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {TP_KIND_LABEL[resolving.kind] || resolving.kind} · {resolving.zone_name || '—'} ·
                  {' '}boshlangan: {formatDateTime(resolving.started_at)}
                </Typography>
                {resolving.description && (
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{resolving.description}</Typography>
                )}
              </Alert>
            )}

            <TextField
              label="Qo‘shimcha vaqt (daqiqa)"
              type="number"
              value={decision.overtime_minutes}
              onChange={(event) =>
                setDecision((prev) => ({
                  ...prev,
                  overtime_minutes: clamp(Number(event.target.value)),
                }))
              }
              inputProps={{ min: 0, max: 240 }}
              helperText="Talabgorga beriladigan kompensatsiya vaqti (0–240)"
            />

            <TextField
              label="Izoh"
              value={decision.note}
              onChange={(event) => setDecision((prev) => ({ ...prev, note: event.target.value }))}
              multiline
              minRows={2}
              inputProps={{ maxLength: 500 }}
              helperText="Bu matn audit yozuviga tushadi"
            />

            <FormControlLabel
              control={
                <Switch
                  checked={decision.resume_session}
                  onChange={(event) =>
                    setDecision((prev) => ({ ...prev, resume_session: event.target.checked }))
                  }
                />
              }
              label="Sessiyani davom ettirish"
            />

            {!decision.resume_session && (
              <Alert severity="warning">
                Sessiya davom ettirilmasa, talabgor imtihonga qayta kira olmaydi —
                uni faqat yangi sessiya bilan tiklash mumkin.
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setResolving(null)} color="inherit" disabled={resolveMutation.isPending}>
            Bekor qilish
          </Button>
          <Button
            variant="contained"
            disabled={resolveMutation.isPending}
            onClick={() => resolveMutation.mutate({ id: resolving.id, payload: decision })}
          >
            {resolveMutation.isPending ? 'Saqlanmoqda…' : 'Tasdiqlash'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

const clamp = (value) => Math.min(240, Math.max(0, Number.isFinite(value) ? value : 0))
