import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, Collapse, Drawer, IconButton, LinearProgress, Stack, Tab, Tabs, Tooltip, Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import HubIcon from '@mui/icons-material/HubOutlined'
import RefreshIcon from '@mui/icons-material/RefreshOutlined'
import TerminalIcon from '@mui/icons-material/TerminalOutlined'
import PowerIcon from '@mui/icons-material/PowerSettingsNewOutlined'
import AddIcon from '@mui/icons-material/AddToQueueOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import MemoryIcon from '@mui/icons-material/MemoryOutlined'
import FingerprintIcon from '@mui/icons-material/FingerprintOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import AppsIcon from '@mui/icons-material/AppsOutlined'
import RocketIcon from '@mui/icons-material/RocketLaunchOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import WindowsIcon from '@mui/icons-material/DesktopWindowsOutlined'
import RouterIcon from '@mui/icons-material/RouterOutlined'
import ScheduleIcon from '@mui/icons-material/ScheduleOutlined'

import ConfirmDialog from '../ConfirmDialog'
import { bba } from '../../api/endpoints'
import { useUi } from '../../context/UiContext'
import { dateText, Field, HeaderIcon, Section, useCopy } from '../data/DetailFields'
import { BBA_STATUS_LABEL, formatDateTime } from '../../utils/labels'
import { BBA_STATUS_TONE, BbaStatus, JobStatusChip, resultText, Terminal, uptime } from './common'
import {
  Empty, HardwareIdsPanel, HardwarePanel, NetworkPanel, SoftwarePanel, StartupPanel,
} from './InventoryPanels'
import { JobIcon } from './icons'
import SendJobDialog from './SendJobDialog'
import ImportDialog from './ImportDialog'
import type { HeaderTone } from '../data/DetailFields'
import type { ApiRecord, Id } from '../../types/api'

const TABS = [
  { label: 'Umumiy', icon: InfoIcon },
  { label: 'Hardware', icon: MemoryIcon },
  { label: 'Hardware ID', icon: FingerprintIcon },
  { label: 'Tarmoq', icon: LanIcon },
  { label: 'Dasturlar', icon: AppsIcon },
  { label: 'Avtostart', icon: RocketIcon },
  { label: 'Job’lar', icon: HistoryIcon },
] as const

const HEADER_TONE: Record<string, HeaderTone> = {
  success: 'success', error: 'error', default: 'neutral',
}

const CONNECTIVITY_LABEL: Record<string, string> = {
  connected: 'Ulandi',
  disconnected_graceful: 'Normal o‘chdi',
  disconnected_unexpected: 'Aloqa uzildi',
  agent_reported_offline: 'Agent: internet yo‘q edi',
}

/**
 * BBA kompyuterining to'liq kartasi — yon varaq, tablar bilan.
 *
 * Holat (yoniq/o'chiq) WebSocket bilan o'rnida yangilanadi (`useBbaLive`
 * `['bba-device', id]` keshini ham to'g'rilaydi). Inventory — serverdagi
 * oxirgi nusxa; «Yangilash» uni Console'dan qayta oladi.
 */
export default function BbaDeviceSheet({
  deviceId, canJobs, canImport, onClose,
}: { deviceId: Id | null; canJobs: boolean; canImport: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const copy = useCopy()
  const [tab, setTab] = useState(0)
  const [jobOpen, setJobOpen] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [startupToggle, setStartupToggle] = useState<ApiRecord | null>(null)
  const [waking, setWaking] = useState(false)

  const { data: device, isLoading } = useQuery({
    queryKey: ['bba-device', deviceId],
    queryFn: () => bba.devices.detail(deviceId!),
    enabled: deviceId != null,
  })

  const refresh = useMutation({
    mutationFn: () => bba.devices.refreshInventory(deviceId!),
    retry: false,
    onSuccess: (data) => {
      queryClient.setQueryData(['bba-device', deviceId], data)
      queryClient.invalidateQueries({ queryKey: ['bba-devices'] })
      notify('Inventory yangilandi')
    },
    onError: notifyError,
  })

  const wake = useMutation({
    mutationFn: () => bba.devices.wake(deviceId!),
    retry: false,
    onSuccess: (data) => {
      const result = data.results?.[0] || {}
      if (result.status === 'already_online') notify('Kompyuter allaqachon yoniq', 'info')
      else if (result.status === 'error') notify(result.message || 'Yoqib bo‘lmadi', 'warning')
      else notify('Yoqish signali yuborildi (xonadagi yoniq kompyuter orqali)')
      setWaking(false)
    },
    onError: (error) => {
      setWaking(false)
      notifyError(error)
    },
  })

  const toggleStartup = useMutation({
    mutationFn: (app: ApiRecord) => bba.devices.sendJob(deviceId!, {
      job_type: 'manage_startup_app',
      params: {
        action: app.enabled ? 'disable' : 'enable',
        name: app.name, type: app.type, hive: app.hive, path: app.path, command: app.command,
      },
    }),
    retry: false,
    onSuccess: () => {
      notify('Job yuborildi — o‘zgarish keyingi inventory’da ko‘rinadi')
      setStartupToggle(null)
      queryClient.invalidateQueries({ queryKey: ['bba-device-jobs'] })
    },
    onError: notifyError,
  })

  const inventory: ApiRecord | null = device?.inventory || null
  const hw = inventory?.Hardware
  const tone = BBA_STATUS_TONE[device?.status] || 'default'

  return (
    <Drawer
      anchor="right"
      open={deviceId != null}
      onClose={onClose}
      slotProps={{
        paper: {
          sx: {
            width: { xs: '100%', sm: 640 },
            bgcolor: 'm3.surfaceContainerLow',
            borderTopLeftRadius: { sm: 28 },
            borderBottomLeftRadius: { sm: 28 },
          },
        },
      }}
    >
      {isLoading && <LinearProgress />}
      {device && (
        <Stack sx={{ height: '100%' }}>
          <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ px: 3, pt: 3, pb: 1.5 }}>
            <HeaderIcon tone={device.revoked_at ? 'error' : HEADER_TONE[tone] || 'neutral'}><HubIcon /></HeaderIcon>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h6" noWrap sx={{ lineHeight: 1.3 }}>{device.name}</Typography>
              <Typography variant="body2" color="text.secondary" noWrap>
                {[device.bba_region_name, device.room_name].filter(Boolean).join(' · ') || 'Xonaga biriktirilmagan'}
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                <BbaStatus device={device} />
                {device.primary_ip && (
                  <Chip size="small" variant="outlined" label={device.primary_ip} sx={{ fontFamily: 'monospace' }} />
                )}
                {device.computer_detail && <Chip size="small" color="info" label={`Bizda: ${device.computer_detail.label}`} />}
              </Stack>
            </Box>
            <IconButton onClick={onClose} aria-label="Yopish" sx={{ mt: -0.5, mr: -1 }}>
              <CloseIcon />
            </IconButton>
          </Stack>

          <Stack direction="row" spacing={1} sx={{ px: 3, pb: 1.5 }} flexWrap="wrap" useFlexGap>
            <Button
              size="small" variant="outlined" startIcon={<RefreshIcon />} disabled={refresh.isPending}
              onClick={() => refresh.mutate()} sx={{ borderRadius: 999 }}
            >
              Inventory’ni yangilash
            </Button>
            {canJobs && (
              <Button
                size="small" variant="outlined" startIcon={<TerminalIcon />}
                onClick={() => setJobOpen('collect_inventory')} sx={{ borderRadius: 999 }}
              >
                Job yuborish
              </Button>
            )}
            {canJobs && device.status !== 'online' && (
              <Tooltip title="Wake-on-LAN — xonadagi boshqa yoniq kompyuter orqali">
                <span>
                  <Button
                    size="small" variant="outlined" color="success" startIcon={<PowerIcon />}
                    disabled={wake.isPending} onClick={() => setWaking(true)} sx={{ borderRadius: 999 }}
                  >
                    Yoqish
                  </Button>
                </span>
              </Tooltip>
            )}
            {canImport && !device.computer_detail && (
              <Button
                size="small" variant="contained" disableElevation startIcon={<AddIcon />}
                onClick={() => setImportOpen(true)} sx={{ borderRadius: 999 }}
              >
                Ro‘yxatga qo‘shish
              </Button>
            )}
          </Stack>

          <Tabs
            value={tab}
            onChange={(_, value) => setTab(value)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ px: 1.5, borderBottom: 1, borderColor: 'divider' }}
          >
            {TABS.map(({ label, icon: TabIcon }) => (
              <Tab
                key={label}
                label={label}
                icon={<TabIcon fontSize="small" />}
                iconPosition="start"
                sx={{ minWidth: 0, minHeight: 48, px: 1.5, textTransform: 'none', fontWeight: 600 }}
              />
            ))}
          </Tabs>
          {refresh.isPending && <LinearProgress />}

          <Box sx={{ flex: 1, overflowY: 'auto', p: 2 }}>
            {device.inventory_error && (
              <Alert severity="warning" sx={{ mb: 1.5 }}>Inventory olinmadi: {device.inventory_error}</Alert>
            )}
            {tab === 0 && <Overview device={device} inventory={inventory} copy={copy} />}
            {tab === 1 && <HardwarePanel hw={inventory ? hw || {} : null} />}
            {tab === 2 && <HardwareIdsPanel hw={inventory ? hw || {} : null} />}
            {tab === 3 && <NetworkPanel nics={inventory?.NetworkConfig} device={device} />}
            {tab === 4 && <SoftwarePanel software={inventory?.InstalledSoftware} hasInventory={Boolean(inventory)} />}
            {tab === 5 && (
              <StartupPanel
                apps={inventory?.StartupApps}
                hasInventory={Boolean(inventory)}
                canJobs={canJobs}
                busy={toggleStartup.isPending}
                onToggle={setStartupToggle}
                onAdd={() => setJobOpen('manage_startup_app')}
              />
            )}
            {tab === 6 && <JobsPanel deviceId={device.id} />}
          </Box>
        </Stack>
      )}

      {jobOpen && device && (
        <SendJobDialog
          target={{ device, count: 1 }}
          initialType={jobOpen}
          onClose={() => setJobOpen(null)}
        />
      )}
      {importOpen && device && (
        <ImportDialog target={{ device, count: 1 }} onClose={() => setImportOpen(false)} />
      )}
      <ConfirmDialog
        open={Boolean(startupToggle)}
        title={startupToggle?.enabled ? 'Avtostartdan olish' : 'Avtostartga qaytarish'}
        description={`«${startupToggle?.name}» Windows ishga tushganda ${startupToggle?.enabled ? 'ishga tushmaydi' : 'yana ishga tushadi'}.`}
        confirmLabel={startupToggle?.enabled ? 'O‘chirish' : 'Yoqish'}
        loading={toggleStartup.isPending}
        onConfirm={() => startupToggle && toggleStartup.mutate(startupToggle)}
        onClose={() => setStartupToggle(null)}
      />
      <ConfirmDialog
        open={waking}
        title="Kompyuterni yoqish"
        description={
          'Wake-on-LAN signali xonadagi boshqa YONIQ kompyuter orqali yuboriladi. ' +
          'Xonada yoniq kompyuter bo‘lmasa yoki BIOS’da WoL o‘chiq bo‘lsa, yoqilmaydi.'
        }
        confirmLabel="Yoqish"
        loading={wake.isPending}
        onConfirm={() => wake.mutate()}
        onClose={() => setWaking(false)}
      />
    </Drawer>
  )
}

function Overview({
  device, inventory, copy,
}: { device: ApiRecord; inventory: ApiRecord | null; copy: (value: string) => void }) {
  const computer = device.computer_detail
  return (
    <>
      <Section title="Holat">
        <Field label="Holat" value={BBA_STATUS_LABEL[device.status] || device.status} />
        <Field label="Holat o‘zgargan" value={dateText(device.status_changed_at)} icon={<ScheduleIcon />} />
        <Field label="Oxirgi aloqa (Console)" value={dateText(device.last_seen_at)} />
        <Field label="Ishlab turibdi" value={device.status === 'online' ? uptime(inventory?.LastBootAt) : ''} hint="—" />
        {device.revoked_at && <Field label="Console’dan chiqarilgan" value={dateText(device.revoked_at)} warn />}
        {!device.is_visible && (
          <Field label="Console ro‘yxatida yo‘q" value={dateText(device.missing_since)} warn />
        )}
      </Section>

      <Section title="Bizdagi kompyuter">
        {computer ? (
          <>
            <Field label="Kompyuter" value={computer.label} />
            <Field label="Bino" value={[computer.region_name, computer.zone_name].filter(Boolean).join(' · ')} />
            <Field label="MAC (bizda)" value={computer.mac_address} mono onCopy={copy} />
            {!computer.is_active && <Field label="Holat" value="Hisobdan chiqarilgan" warn />}
          </>
        ) : (
          <Field
            label="Ro‘yxatda yo‘q"
            value=""
            hint="Kompyuterlar ro‘yxatida bu mashinaning (UUID, MAC) juftligi topilmadi"
          />
        )}
      </Section>

      <Section title="Kompyuter">
        <Field label="Console nomi" value={device.hostname_code} icon={<HubIcon />} />
        <Field label="Windows nomi" value={device.hostname} icon={<WindowsIcon />} />
        <Field label="Operatsion tizim" value={inventory?.OSVersion} hint="Inventory yo‘q" icon={<WindowsIcon />} />
        <Field label="System UUID" value={device.system_uuid} mono onCopy={copy} hint="Inventory’da yo‘q (yoki to‘ldiruvchi)" icon={<FingerprintIcon />} />
        <Field label="Faol MAC" value={device.primary_mac} mono onCopy={copy} icon={<LanIcon />} />
        <Field label="IP manzil" value={device.primary_ip} mono onCopy={copy} hint="Inventory’da yo‘q" icon={<RouterIcon />} />
        <Field label="Agent versiyasi" value={device.agent_version} />
        <Field label="Console ID" value={device.console_id} mono onCopy={copy} />
        <Field label="Ro‘yxatdan o‘tgan" value={dateText(device.enrolled_at)} />
        <Field
          label="Inventory"
          value={device.inventory_captured_at ? `${formatDateTime(device.inventory_captured_at)} (agent yig‘gan)` : ''}
          hint="Hali yig‘ilmagan"
        />
      </Section>

      <ConnectivitySection deviceId={device.id} />
    </>
  )
}

function ConnectivitySection({ deviceId }: { deviceId: Id }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['bba-device-connectivity', deviceId],
    queryFn: () => bba.devices.connectivity(deviceId),
    retry: false,
  })
  const events: ApiRecord[] = data?.events || []
  return (
    <Section title="Yoqilish / o‘chish tarixi">
      {isLoading && <LinearProgress />}
      {error && <Box sx={{ p: 2 }}><Typography variant="body2" color="error">Console’dan olinmadi</Typography></Box>}
      {!isLoading && !error && !events.length && (
        <Box sx={{ p: 2 }}><Typography variant="body2" color="text.secondary">Hodisa yo‘q</Typography></Box>
      )}
      {events.map((event, index) => (
        <Stack
          key={index}
          direction="row"
          alignItems="center"
          spacing={1}
          sx={{ px: 2, py: 1, borderTop: index ? 1 : 0, borderColor: 'divider' }}
        >
          <Chip
            size="small"
            variant="outlined"
            color={event.kind === 'connected' ? 'success' : event.kind === 'disconnected_unexpected' ? 'error' : 'default'}
            label={CONNECTIVITY_LABEL[event.kind] || event.kind}
          />
          <Typography variant="body2" sx={{ flex: 1 }}>{formatDateTime(event.occurred_at)}</Typography>
        </Stack>
      ))}
    </Section>
  )
}

function JobsPanel({ deviceId }: { deviceId: Id }) {
  const [open, setOpen] = useState<string | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['bba-device-jobs', deviceId],
    queryFn: () => bba.devices.jobHistory(deviceId),
    retry: false,
    refetchInterval: 15000,
  })
  const { data: catalog } = useQuery({ queryKey: ['bba-job-types'], queryFn: bba.jobTypes, staleTime: 3600_000 })
  const labels: Record<string, string> = Object.fromEntries(
    (catalog?.types || []).map((item: ApiRecord) => [item.code, item.label]),
  )
  const jobs: ApiRecord[] = data?.jobs || []
  if (isLoading) return <LinearProgress />
  if (error) return <Empty>Console job tarixini bermadi</Empty>
  if (!jobs.length) return <Empty>Bu kompyuterga job yuborilmagan</Empty>
  return (
    <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', overflow: 'hidden' }}>
      {jobs.map((job, index) => {
        const key = String(job.console_job_id ?? index)
        return (
          <Box key={key} sx={{ borderTop: index ? 1 : 0, borderColor: 'divider' }}>
            <Stack
              direction="row"
              spacing={1.5}
              alignItems="center"
              onClick={() => setOpen(open === key ? null : key)}
              sx={{ px: 2, py: 1, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}
            >
              <JobIcon type={job.type} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap>{labels[job.type] || job.type}</Typography>
                <Typography variant="caption" color="text.secondary" noWrap display="block">
                  {formatDateTime(job.issued_at)}
                  {job.issued_by ? ` · ${job.issued_by}` : ''}
                  {job.from_panel ? ' · paneldan' : ' · Console’dan'}
                </Typography>
              </Box>
              <JobStatusChip status={job.status} />
            </Stack>
            <Collapse in={open === key} unmountOnExit>
              <Box sx={{ px: 2, pb: 1.5 }}>
                {job.params && Object.keys(job.params).length > 0 && (
                  <Typography variant="caption" component="pre" sx={{ m: 0, mb: 1, whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                    {JSON.stringify(job.params, null, 2)}
                  </Typography>
                )}
                <Terminal text={job.result ? resultText(job.result) : 'Natija hali yo‘q'} maxHeight={220} />
              </Box>
            </Collapse>
          </Box>
        )
      })}
    </Box>
  )
}
