import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Badge, Box, Card, IconButton, Stack, Tab, Tabs, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/RefreshOutlined'

import PageHeader from '../components/PageHeader'
import { PageSkeleton } from '../components/feedback/Skeletons'
import { ErrorState } from '../components/feedback/States'
import { system } from '../api/endpoints'
import HostHero, { SECTION_TAB } from '../components/system/HostHero'
import ResourceGauges from '../components/system/ResourceGauges'
import PipelineFlow from '../components/system/PipelineFlow'
import HistoryCharts from '../components/system/HistoryCharts'
import RequestsPanel from '../components/system/RequestsPanel'
import ServicesPanel from '../components/system/ServicesPanel'
import DisksPanel from '../components/system/DisksPanel'
import DataPanel from '../components/system/DataPanel'
import NetworkPanel from '../components/system/NetworkPanel'
import type { ApiRecord } from '../types/api'

const TABS = [
  { value: 'overview', label: 'Umumiy' },
  { value: 'requests', label: 'So‘rovlar' },
  { value: 'services', label: 'Servislar' },
  { value: 'disks', label: 'Disklar' },
  { value: 'data', label: 'Ma’lumotlar' },
  { value: 'network', label: 'Tarmoq' },
]

const REFRESH_OPTIONS = [
  { value: 0, label: 'Off' },
  { value: 5000, label: '5s' },
  { value: 15000, label: '15s' },
]

/** Yorliq bo'yicha muammolar soni (yorliqdagi nishon). */
function problemCounts(problems: ApiRecord[]): Record<string, { count: number; critical: boolean }> {
  const result: Record<string, { count: number; critical: boolean }> = {}
  for (const item of problems) {
    const tab = SECTION_TAB[item.section] || 'overview'
    const entry = result[tab] || { count: 0, critical: false }
    entry.count += 1
    entry.critical = entry.critical || item.severity === 'critical'
    result[tab] = entry
  }
  return result
}

/**
 * Server holati — imtihon kuni administrator uchun "hammasi joyidami?".
 *
 * Ma'lumot backend `apps/monitoring` dan: jonli holat 5 s da (serverda
 * 3 s keshlanadi — bir nechta administrator yuk qo'shmaydi), tarix
 * 30 s da. Prometheus/Grafana o'rnini BOSMAYDI (`deploy/MONITORING.md`):
 * bu — tez qaror uchun, uzoq muddatli tahlil uchun emas.
 */
export default function SystemStatus() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((item) => item.value === params.get('tab')) ? params.get('tab')! : 'overview'
  const [refreshMs, setRefreshMs] = useState(5000)
  const [range, setRange] = useState('1h')

  const query = useQuery({
    queryKey: ['system-status'],
    queryFn: () => system.status(),
    refetchInterval: refreshMs || false,
    // Sahifa fonda bo'lsa so'ramaymiz: server yig'ishi arzon, lekin behuda.
    refetchIntervalInBackground: false,
  })

  const openTab = useCallback((value: string) => {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (value === 'overview') next.delete('tab')
      else next.set('tab', value)
      return next
    }, { replace: true })
  }, [setParams])

  const status = query.data
  const counts = problemCounts(status?.problems || [])
  const updated = status?.generated_at ? new Date(status.generated_at) : null

  const header = (
    <PageHeader
      title="Server holati"
      subtitle={status?.host?.hostname ? `${status.host.hostname} · ${status.host.os}` : 'Resurslar, servislar va so‘rovlar'}
      actions={(
        <Stack direction="row" spacing={1} alignItems="center">
          {updated && (
            <Tooltip title={`Yig‘ish: ${status?.collect_ms} ms · tezlik oynasi: ${status?.window_s} s`}>
              <Typography variant="caption" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
                {updated.toLocaleTimeString('ru-RU')}
              </Typography>
            </Tooltip>
          )}
          <ToggleButtonGroup
            size="small" exclusive value={refreshMs}
            onChange={(_, value) => value != null && setRefreshMs(value)}
          >
            {REFRESH_OPTIONS.map((option) => (
              <ToggleButton key={option.value} value={option.value} sx={{ px: 1.25 }}>{option.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Tooltip title="Yangilash">
            <span>
              <IconButton onClick={() => query.refetch()} disabled={query.isFetching} aria-label="Yangilash">
                <RefreshIcon sx={{
                  animation: query.isFetching ? 'spin 0.9s linear infinite' : 'none',
                  '@keyframes spin': { to: { transform: 'rotate(360deg)' } },
                }}
                />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      )}
    />
  )

  if (query.isLoading) {
    return <>{header}<PageSkeleton /></>
  }
  if (query.error && !status) {
    return <>{header}<Card><ErrorState error={query.error} onRetry={query.refetch} /></Card></>
  }
  if (!status) return header

  return (
    <>
      {header}
      <HostHero status={status} onOpenTab={openTab} />

      <Box sx={{ mb: 2.5, borderBottom: 1, borderColor: 'divider' }}>
        <Tabs
          value={tab}
          onChange={(_, value) => openTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
        >
          {TABS.map((item) => {
            const count = counts[item.value]
            return (
              <Tab
                key={item.value}
                value={item.value}
                label={count ? (
                  <Badge
                    badgeContent={count.count}
                    color={count.critical ? 'error' : 'warning'}
                    sx={{ '& .MuiBadge-badge': { right: -14, top: 2 } }}
                  >
                    {item.label}
                  </Badge>
                ) : item.label}
                sx={count ? { pr: 3.5 } : undefined}
              />
            )
          })}
        </Tabs>
      </Box>

      {tab === 'overview' && (
        // `Stack` emas: u bolalarning chekkasini 0 qiladi va `Grid` ning
        // manfiy chekkasi yo'qolib, kartalar sarlavhadan 20 px siljiydi.
        <Box sx={{ display: 'grid', gap: { xs: 1.5, sm: 2.5 } }}>
          <ResourceGauges status={status} />
          <PipelineFlow status={status} />
          <HistoryCharts range={range} onRange={setRange} />
        </Box>
      )}
      {tab === 'requests' && <RequestsPanel status={status} />}
      {tab === 'services' && <ServicesPanel status={status} />}
      {tab === 'disks' && <DisksPanel status={status} />}
      {tab === 'data' && <DataPanel status={status} />}
      {tab === 'network' && <NetworkPanel status={status} />}
    </>
  )
}
