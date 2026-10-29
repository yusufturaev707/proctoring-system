import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel,
  FormGroup, MenuItem, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material'
import TerminalIcon from '@mui/icons-material/TerminalOutlined'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'

import { bba } from '../../api/endpoints'
import { useUi } from '../../context/UiContext'
import { JobStatusChip, resultText, Terminal } from './common'
import type { BulkSelection } from '../../api/endpoints'
import type { ApiRecord, Id } from '../../types/api'

/** Bitta kompyuter yoki tanlov (`ids` / filtrga mos `all`). */
export interface JobTarget {
  device?: ApiRecord
  selection?: BulkSelection
  count: number
}

const LOCK_FEATURE_LABEL: Record<string, string> = {
  task_manager: 'Task Manager',
  control_panel: 'Control Panel',
  usb: 'USB qurilmalar',
}

const SCRIPT_PLACEHOLDER: Record<string, string> = {
  powershell: 'Get-Process | Sort-Object CPU -Descending | Select-Object -First 10',
  cmd: 'ipconfig /all',
  sh: 'uname -a',
}

const ACTIVE_STATUSES = new Set(['pending', 'sent', 'received', 'running'])

/**
 * BBA Console'ga job yuborish. Turlar va ularning parametr shakli serverdan
 * (`bba/job-types/` — `apps/bba/jobs.py`), shu sababli forma va server
 * tekshiruvi ajralib ketmaydi. Xavfli turda belgi qo'yilmaguncha tugma o'chiq.
 *
 * Bitta kompyuterga yuborilganda natija shu oynada kuzatiladi (terminal
 * kabi) — job tarixini qidirib o'tirish shart emas.
 */
export default function SendJobDialog({
  target, initialType = 'collect_inventory', onClose, onSent,
}: { target: JobTarget; initialType?: string; onClose: () => void; onSent?: () => void }) {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { data: catalog } = useQuery({ queryKey: ['bba-job-types'], queryFn: bba.jobTypes, staleTime: 3600_000 })
  const types: ApiRecord[] = catalog?.types || []

  const [jobType, setJobType] = useState(initialType)
  const [scriptType, setScriptType] = useState('powershell')
  const [script, setScript] = useState('')
  const [features, setFeatures] = useState<string[]>([])
  const [startup, setStartup] = useState({ action: 'enable', name: '', command: '' })
  const [json, setJson] = useState('{}')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const [sentJobId, setSentJobId] = useState<Id | null>(null)

  const spec = useMemo(() => types.find((item) => item.code === jobType), [types, jobType])
  const single = Boolean(target.device)

  // Yuborilgan job holati (faqat bitta kompyuter) — yakunlanguncha har 2 s.
  // Holatni server Console'dan holat yurishida oladi (`BBA_STATUS_POLL_SECONDS`).
  const { data: tracked } = useQuery({
    queryKey: ['bba-jobs', 'tracked', sentJobId],
    queryFn: () => bba.jobs.detail(sentJobId!),
    enabled: sentJobId != null,
    refetchInterval: (query) => (
      query.state.data && !ACTIVE_STATUSES.has(query.state.data.status) ? false : 2000
    ),
  })

  const buildParams = (): ApiRecord | null => {
    if (!spec) return null
    switch (spec.params) {
      case 'script':
        if (!script.trim()) return fail('Skript matnini kiriting')
        return { script_type: scriptType, script_content: script }
      case 'features':
        if (!features.length) return fail('Kamida bitta funksiyani tanlang')
        return { features }
      case 'startup':
        if (!startup.name.trim()) return fail('Dastur nomini kiriting')
        if (startup.action === 'enable' && !startup.command.trim()) return fail('Dastur yo‘lini kiriting')
        return { action: startup.action, name: startup.name.trim(), command: startup.command.trim() }
      case 'json':
        try {
          const value = JSON.parse(json || '{}')
          if (!value || typeof value !== 'object' || Array.isArray(value)) return fail('Parametrlar JSON obyekt bo‘lishi kerak')
          return value
        } catch {
          return fail('JSON noto‘g‘ri')
        }
      default:
        return {}
    }
  }

  const fail = (message: string) => {
    setError(message)
    return null
  }

  const mutation = useMutation({
    mutationFn: (payload: ApiRecord) => (
      target.device
        ? bba.devices.sendJob(target.device.id, payload)
        : bba.devices.bulkSendJob(target.selection!, payload)
    ),
    retry: false,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['bba-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['bba-device-jobs'] })
      onSent?.()
      if (single) {
        setSentJobId(result.jobs?.[0]?.id ?? null)
        notify('Job yuborildi')
        if (jobType === 'run_script') setScript('')
        return
      }
      notify(
        `Job ${result.sent} ta kompyuterga yuborildi` + (result.failed ? ` · ${result.failed} tasiga yuborilmadi` : ''),
        result.failed ? 'warning' : 'success',
      )
      onClose()
    },
    onError: notifyError,
  })

  const submit = () => {
    setError('')
    const params = buildParams()
    if (params === null) return
    mutation.mutate({ job_type: jobType, params, confirm: Boolean(spec?.dangerous && confirmed) })
  }

  const busy = mutation.isPending || (tracked ? ACTIVE_STATUSES.has(tracked.status) : sentJobId != null)
  const targetLabel = target.device ? target.device.name : `${target.count} ta kompyuter`

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <TerminalIcon color="primary" />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h6" component="div">Job yuborish</Typography>
          <Typography variant="body2" color="text.secondary" noWrap>{targetLabel}</Typography>
        </Box>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <TextField
            select
            label="Turi"
            value={jobType}
            onChange={(event) => {
              setJobType(event.target.value)
              setConfirmed(false)
              setError('')
            }}
            fullWidth
          >
            {types.map((item) => (
              <MenuItem key={item.code} value={item.code}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <span>{item.label}</span>
                  {item.dangerous && <WarningIcon fontSize="inherit" color="warning" />}
                </Stack>
              </MenuItem>
            ))}
          </TextField>

          {spec?.params === 'script' && (
            <>
              <ToggleButtonGroup size="small" exclusive value={scriptType} onChange={(_, value) => value && setScriptType(value)}>
                <ToggleButton value="powershell">PowerShell</ToggleButton>
                <ToggleButton value="cmd">cmd</ToggleButton>
                <ToggleButton value="sh">sh</ToggleButton>
              </ToggleButtonGroup>
              <TextField
                label="Skript"
                value={script}
                onChange={(event) => setScript(event.target.value)}
                placeholder={SCRIPT_PLACEHOLDER[scriptType]}
                multiline
                minRows={5}
                maxRows={14}
                fullWidth
                slotProps={{ htmlInput: { style: { fontFamily: 'monospace', fontSize: 13 } } }}
              />
            </>
          )}

          {spec?.params === 'features' && (
            <FormGroup row>
              {(catalog?.lock_features || []).map((feature: string) => (
                <FormControlLabel
                  key={feature}
                  label={LOCK_FEATURE_LABEL[feature] || feature}
                  control={(
                    <Checkbox
                      checked={features.includes(feature)}
                      onChange={(event) => setFeatures((prev) => (
                        event.target.checked ? [...prev, feature] : prev.filter((item) => item !== feature)
                      ))}
                    />
                  )}
                />
              ))}
            </FormGroup>
          )}

          {spec?.params === 'startup' && (
            <>
              <ToggleButtonGroup
                size="small"
                exclusive
                value={startup.action}
                onChange={(_, value) => value && setStartup((prev) => ({ ...prev, action: value }))}
              >
                <ToggleButton value="enable">Avtostartga qo‘shish</ToggleButton>
                <ToggleButton value="disable">Avtostartdan olish</ToggleButton>
              </ToggleButtonGroup>
              <TextField
                label="Nomi"
                value={startup.name}
                onChange={(event) => setStartup((prev) => ({ ...prev, name: event.target.value }))}
                placeholder="Proctoring Client"
                fullWidth
              />
              <TextField
                label="Dastur yo‘li"
                value={startup.command}
                onChange={(event) => setStartup((prev) => ({ ...prev, command: event.target.value }))}
                placeholder="C:\Program Files\ProctoringClient\ProctoringClient.exe"
                helperText="Har bir foydalanuvchi uchun, har ishga tushishda (kompyuter darajasidagi Run kaliti)"
                fullWidth
                slotProps={{ htmlInput: { style: { fontFamily: 'monospace', fontSize: 13 } } }}
              />
            </>
          )}

          {spec?.params === 'json' && (
            <TextField
              label="Parametrlar (JSON)"
              value={json}
              onChange={(event) => setJson(event.target.value)}
              multiline
              minRows={4}
              fullWidth
              helperText="Console shu turdagi job uchun kutadigan parametrlar"
              slotProps={{ htmlInput: { style: { fontFamily: 'monospace', fontSize: 13 } } }}
            />
          )}

          {spec?.detail && (
            <Alert severity={spec.dangerous ? 'warning' : 'info'} icon={spec.dangerous ? <WarningIcon /> : undefined}>
              {spec.detail}
            </Alert>
          )}

          {spec?.dangerous && (
            <FormControlLabel
              control={<Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />}
              label={`Tushundim — «${spec.label}» ${targetLabel}ga yuborilsin`}
            />
          )}

          {error && <Alert severity="error">{error}</Alert>}

          {tracked && (
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle2">Natija</Typography>
                <JobStatusChip status={tracked.status} />
              </Stack>
              {ACTIVE_STATUSES.has(tracked.status) ? (
                <Typography variant="body2" color="text.secondary">
                  Kompyuter bajarishini kutmoqda… (o‘chiq bo‘lsa yoqilganda bajariladi)
                </Typography>
              ) : (
                <Terminal text={tracked.error || resultText(tracked.result)} />
              )}
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Yopish</Button>
        <Button
          variant="contained"
          color={spec?.dangerous ? 'error' : 'primary'}
          disableElevation
          disabled={!spec || busy || (spec.dangerous && !confirmed)}
          onClick={submit}
          sx={{ borderRadius: 999 }}
        >
          {busy && single ? 'Bajarilmoqda…' : 'Yuborish'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
