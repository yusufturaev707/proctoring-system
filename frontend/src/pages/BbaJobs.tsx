import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, Tooltip, Typography,
} from '@mui/material'
import CancelIcon from '@mui/icons-material/CancelOutlined'
import ReplayIcon from '@mui/icons-material/ReplayOutlined'

import ResourcePage from '../components/data/ResourcePage'
import { JobStatusChip, resultText, Terminal } from '../components/bba/common'
import { JobIcon } from '../components/bba/icons'
import { LastSeenCell } from './crud/shared'
import { bba } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'
import { useBbaLive } from '../hooks/useBbaLive'
import { BBA_JOB_STATUS_LABEL, formatDateTime } from '../utils/labels'
import type { AppColumn, FilterDef } from '../components/data/types'
import type { ApiRecord, Id } from '../types/api'

const jobsApi = { list: bba.jobs.list }
const CANCELLABLE = new Set(['pending', 'sent'])
const RESENDABLE = new Set(['sent', 'failed', 'timeout', 'cancelled'])

/**
 * Paneldan BBA kompyuterlariga yuborilgan job'lar — KIM yuborgani bilan
 * (Console tarixida yuboruvchi integratsiya hisobi bo'lib ko'rinadi).
 * Holat Console'dan server yurishida yangilanadi va WebSocket bilan keladi.
 */
export default function BbaJobs() {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { can } = useAuth()
  const canJobs = can('bba.jobs')
  useBbaLive()
  const [detail, setDetail] = useState<ApiRecord | null>(null)
  const { data: catalog } = useQuery({ queryKey: ['bba-job-types'], queryFn: bba.jobTypes, staleTime: 3600_000 })

  const action = useMutation({
    mutationFn: ({ id, kind }: { id: Id; kind: 'cancel' | 'resend' }) => (
      kind === 'cancel' ? bba.jobs.cancel(id) : bba.jobs.resend(id)
    ),
    retry: false,
    onSuccess: (_, { kind }) => {
      notify(kind === 'cancel' ? 'Job bekor qilindi' : 'Job qayta yuborildi')
      queryClient.invalidateQueries({ queryKey: ['bba-jobs'] })
    },
    onError: notifyError,
  })

  const columns = useMemo(
    (): AppColumn[] => [
      { field: 'created_at', headerName: 'Yuborilgan', width: 140, renderCell: LastSeenCell },
      { field: 'device_name', headerName: 'Kompyuter', flex: 1, minWidth: 140, sortable: false },
      {
        field: 'job_label', headerName: 'Job', flex: 1, minWidth: 180, sortable: false,
        renderCell: (params) => (
          <Stack direction="row" spacing={1.25} alignItems="center" sx={{ height: '100%', minWidth: 0 }}>
            <JobIcon type={params.row.job_type} size={28} />
            <Typography variant="body2" noWrap>{params.value}</Typography>
          </Stack>
        ),
      },
      {
        field: 'status', headerName: 'Holat', width: 140,
        exportValue: (value) => BBA_JOB_STATUS_LABEL[value] || value,
        renderCell: (params) => (
          <Box sx={{ height: '100%', display: 'flex', alignItems: 'center' }}>
            <JobStatusChip status={params.value} />
          </Box>
        ),
      },
      { field: 'issued_by_username', headerName: 'Yuborgan', width: 140, sortable: false },
      { field: 'completed_at', headerName: 'Tugagan', width: 130, sortable: false, renderCell: LastSeenCell },
    ],
    [],
  )

  const filters = useMemo(
    (): FilterDef[] => [
      {
        name: 'status', label: 'Holat',
        options: Object.entries(BBA_JOB_STATUS_LABEL).map(([value, label]) => ({ value, label })),
      },
      {
        name: 'job_type', label: 'Job turi',
        options: (catalog?.types || []).map((item: ApiRecord) => ({ value: item.code, label: item.label })),
      },
    ],
    [catalog],
  )

  return (
    <>
      <ResourcePage
        title="Agent joblar"
        subtitle="Paneldan yuborilgan buyruqlar: kim, qachon, qaysi kompyuterga va natijasi"
        queryKey="bba-jobs"
        api={jobsApi}
        permission="bba.view"
        canCreate={false}
        canEdit={false}
        canDelete={false}
        columns={columns}
        fields={[]}
        filters={filters}
        searchPlaceholder="Kompyuter yoki xodim…"
        exportName="bba-joblar"
        refetchInterval={30000}
        onRowClick={(params) => setDetail(params.row)}
        emptyDescription="Paneldan hali job yuborilmagan"
        actionsWidth={100}
        rowActions={(row) => (canJobs ? (
          <Stack direction="row" spacing={0.25}>
            {CANCELLABLE.has(row.status) && (
              <Tooltip title="Bekor qilish">
                <IconButton
                  size="small" aria-label="Bekor qilish" disabled={action.isPending}
                  onClick={() => action.mutate({ id: row.id, kind: 'cancel' })}
                >
                  <CancelIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            {RESENDABLE.has(row.status) && row.console_job_id && (
              <Tooltip title="Qayta yuborish">
                <IconButton
                  size="small" aria-label="Qayta yuborish" disabled={action.isPending}
                  onClick={() => action.mutate({ id: row.id, kind: 'resend' })}
                >
                  <ReplayIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Stack>
        ) : null)}
      />

      <Dialog open={Boolean(detail)} onClose={() => setDetail(null)} fullWidth maxWidth="sm">
        {detail && (
          <>
            <DialogTitle>
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="h6" component="span" sx={{ flex: 1 }}>{detail.job_label}</Typography>
                <JobStatusChip status={detail.status} />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {detail.device_name} · {detail.issued_by_username} · {formatDateTime(detail.created_at)}
              </Typography>
            </DialogTitle>
            <DialogContent dividers>
              <Stack spacing={1.5}>
                {detail.params && Object.keys(detail.params).length > 0 && (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>Parametrlar</Typography>
                    <Terminal text={
                      detail.job_type === 'run_script'
                        ? `[${detail.params.script_type}]\n${detail.params.script_content}`
                        : JSON.stringify(detail.params, null, 2)
                    }
                    />
                  </Box>
                )}
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Natija</Typography>
                  <Terminal text={detail.error || (detail.result ? resultText(detail.result) : 'Natija hali yo‘q')} />
                </Box>
                {detail.console_job_id && (
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                    Console job ID: {detail.console_job_id}
                    {detail.bulk_operation_id ? ` · bulk: ${detail.bulk_operation_id}` : ''}
                  </Typography>
                )}
              </Stack>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setDetail(null)}>Yopish</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </>
  )
}
