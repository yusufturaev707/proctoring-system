import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { alpha, useTheme } from '@mui/material/styles'
import {
  Box, Button, Card, Chip, Grid, LinearProgress, Stack, Table, TableBody, TableCell, TableHead,
  TableRow, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import SpeedIcon from '@mui/icons-material/SpeedOutlined'
import RouteIcon from '@mui/icons-material/AltRouteOutlined'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'

import { system } from '../../api/endpoints'
import { TableSkeleton } from '../feedback/Skeletons'
import { EmptyState } from '../feedback/States'
import { levelOf, ms, num, pct, worst } from './format'
import type { Level } from './format'
import { levelColor, Metric, MetricGrid, Mono, SectionCard } from './parts'
import type { ApiRecord } from '../../types/api'

const WINDOWS = [
  { key: '1m', label: 'Oxirgi daqiqa' },
  { key: '5m', label: '5 daqiqa' },
  { key: '60m', label: '1 soat' },
]

const METHOD_COLOR: Record<string, 'primary' | 'success' | 'warning' | 'error' | 'default'> = {
  GET: 'primary', POST: 'success', PATCH: 'warning', PUT: 'warning', DELETE: 'error',
}

function WindowCard({ label, data, thresholds }: { label: string; data: ApiRecord; thresholds: ApiRecord }) {
  const enough = (data.count || 0) >= 50
  const level: Level = enough
    ? worst(levelOf(thresholds, 'http_5xx_pct', data.error_pct), levelOf(thresholds, 'http_p95_ms', data.p95_ms))
    : 'unknown'
  return (
    <SectionCard icon={SpeedIcon} title={label} subtitle={`${num(data.count)} so‘rov`} level={level}>
      <MetricGrid min={110}>
        <Metric label="so‘rov/s" value={num(data.rps, data.rps < 1 ? 2 : 1)} />
        <Metric label="p50" value={ms(data.p50_ms)} />
        <Metric label="p95" value={ms(data.p95_ms)} level={enough ? levelOf(thresholds, 'http_p95_ms', data.p95_ms) : undefined} />
        <Metric label="p99" value={ms(data.p99_ms)} />
        <Metric
          label="5xx"
          value={`${num(data.status?.['5xx'])} · ${pct(data.error_pct, 2)}`}
          level={enough ? levelOf(thresholds, 'http_5xx_pct', data.error_pct) : undefined}
        />
        <Metric
          label="429 / 503"
          value={`${num(data.status?.['429'])} / ${num(data.status?.['503'])}`}
          tooltip="429 — throttle (chegara), 503 — vaqtincha mavjud emas (Redis/DB zaxira yo‘li)"
        />
      </MetricGrid>
    </SectionCard>
  )
}

function StatusBar({ data }: { data: ApiRecord }) {
  const theme = useTheme()
  const status = data.status || {}
  const parts = [
    { key: '2xx', label: '2xx', color: theme.palette.success.main },
    { key: '3xx', label: '3xx', color: theme.palette.info.main },
    { key: '4xx', label: '4xx', color: theme.palette.warning.main },
    { key: '5xx', label: '5xx', color: theme.palette.error.main },
  ]
  const total = parts.reduce((sum, part) => sum + (status[part.key] || 0), 0)
  if (!total) return null
  return (
    <Box>
      <Box sx={{ display: 'flex', height: 12, borderRadius: 999, overflow: 'hidden', bgcolor: 'm3.surfaceContainerHighest' }}>
        {parts.map((part) => (status[part.key] ? (
          <Tooltip key={part.key} title={`${part.label}: ${num(status[part.key])}`}>
            <Box sx={{ width: `${(status[part.key] / total) * 100}%`, bgcolor: part.color, minWidth: 3 }} />
          </Tooltip>
        ) : null))}
      </Box>
      <Stack direction="row" flexWrap="wrap" useFlexGap gap={1.5} sx={{ mt: 1 }}>
        {parts.map((part) => (
          <Stack key={part.key} direction="row" spacing={0.5} alignItems="center">
            <Box sx={{ width: 9, height: 9, borderRadius: '3px', bgcolor: part.color }} />
            <Typography variant="caption" color="text.secondary">
              {part.label} — {num(status[part.key])} ({pct(((status[part.key] || 0) / total) * 100)})
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  )
}

const bound = (value: number) => (value >= 1000 ? `${value / 1000} s` : `${value} ms`)

/** Javob vaqti taqsimoti: "sekin so'rovlar qancha" — o'rtacha buni yashiradi. */
function LatencyHistogram({ data, thresholds }: { data: ApiRecord; thresholds: ApiRecord }) {
  const theme = useTheme()
  const rows = (data.histogram || []).map((bucket: ApiRecord, index: number, all: ApiRecord[]) => {
    const lower = index === 0 ? 0 : all[index - 1].le_ms
    return {
      name: bucket.le_ms == null ? `> ${bound(lower)}` : `≤ ${bound(bucket.le_ms)}`,
      count: bucket.count,
      // Chelakdagi so'rovlar PASTKI chegaradan sekin: "≤ 500 ms" chelagi
      // hali SLO ichida, "≤ 1 s" esa yo'q.
      level: levelOf(thresholds, 'http_p95_ms', lower + 0.001),
    }
  })
  if (!rows.some((row: ApiRecord) => row.count > 0)) return null
  return (
    <Box sx={{ height: 200 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fontSize: 10, fill: theme.chart.axis }} axisLine={false} tickLine={false} interval={0} />
          <YAxis tick={{ fontSize: 11, fill: theme.chart.axis }} axisLine={false} tickLine={false} width={48} allowDecimals={false} />
          <ChartTooltip
            cursor={{ fill: alpha(theme.palette.primary.main, 0.06) }}
            formatter={(value: number) => [num(value), 'so‘rov']}
          />
          <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={36}>
            {rows.map((row: ApiRecord) => (
              <Cell key={row.name} fill={row.level === 'ok' ? theme.chart.colors[0] : levelColor(theme, row.level)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  )
}

const ROUTE_MINUTES = [5, 15, 60]
const VISIBLE_ROUTES = 20

function RoutesTable({ thresholds }: { thresholds: ApiRecord }) {
  const theme = useTheme()
  const [minutes, setMinutes] = useState(15)
  const [showAll, setShowAll] = useState(false)
  const query = useQuery({
    queryKey: ['system-requests', minutes],
    queryFn: () => system.requests(minutes),
    refetchInterval: 15000,
  })
  const routes: ApiRecord[] = useMemo(() => query.data?.routes || [], [query.data])
  const visible = showAll ? routes : routes.slice(0, VISIBLE_ROUTES)

  return (
    <SectionCard
      icon={RouteIcon}
      title="Marshrutlar"
      subtitle="Server vaqtini nima egallayapti — umumiy vaqt ulushi bo‘yicha"
      action={(
        <ToggleButtonGroup size="small" exclusive value={minutes} onChange={(_, value) => value && setMinutes(value)}>
          {ROUTE_MINUTES.map((value) => (
            <ToggleButton key={value} value={value} sx={{ px: 1.25 }}>{value === 60 ? '1 soat' : `${value} daq`}</ToggleButton>
          ))}
        </ToggleButtonGroup>
      )}
    >
      {query.isLoading ? (
        <TableSkeleton rows={6} columns={6} showToolbar={false} />
      ) : !routes.length ? (
        <EmptyState title="So‘rovlar yo‘q" description="Bu oraliqda API’ga so‘rov kelmagan." dense />
      ) : (
        <Box sx={{ overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
          <Table size="small" sx={{ minWidth: 760 }}>
            <TableHead>
              <TableRow>
                <TableCell>Marshrut</TableCell>
                <TableCell align="right">So‘rov</TableCell>
                <TableCell align="right">so‘rov/s</TableCell>
                <TableCell align="right">O‘rtacha</TableCell>
                <TableCell align="right">p95</TableCell>
                <TableCell align="right">4xx</TableCell>
                <TableCell align="right">5xx</TableCell>
                <TableCell sx={{ width: 160 }}>Vaqt ulushi</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((route) => {
                const p95Level = levelOf(thresholds, 'http_p95_ms', route.p95_ms)
                return (
                  <TableRow key={route.route} hover>
                    <TableCell sx={{ maxWidth: 360 }}>
                      <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                        {route.method && (
                          <Chip
                            size="small" label={route.method} color={METHOD_COLOR[route.method] || 'default'}
                            variant="outlined" sx={{ height: 20, fontSize: 11, flexShrink: 0 }}
                          />
                        )}
                        <Typography variant="body2" noWrap title={route.path}><Mono>{route.path}</Mono></Typography>
                      </Stack>
                    </TableCell>
                    <TableCell align="right">{num(route.count)}</TableCell>
                    <TableCell align="right">{num(route.rps, 2)}</TableCell>
                    <TableCell align="right">{ms(route.avg_ms)}</TableCell>
                    <TableCell align="right" sx={{ color: p95Level === 'ok' ? undefined : levelColor(theme, p95Level), fontWeight: 600 }}>
                      {ms(route.p95_ms)}
                    </TableCell>
                    <TableCell align="right" sx={{ color: route.errors_4xx ? 'warning.main' : 'text.disabled' }}>
                      {num(route.errors_4xx)}
                    </TableCell>
                    <TableCell align="right" sx={{ color: route.errors_5xx ? 'error.main' : 'text.disabled', fontWeight: route.errors_5xx ? 700 : 400 }}>
                      {num(route.errors_5xx)}
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <LinearProgress
                          variant="determinate" value={Math.min(100, route.time_share_pct)}
                          sx={{ flex: 1, height: 6, bgcolor: 'm3.surfaceContainerHighest' }}
                        />
                        <Typography variant="caption" sx={{ width: 42, textAlign: 'right' }}>{pct(route.time_share_pct, 0)}</Typography>
                      </Stack>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
          {routes.length > VISIBLE_ROUTES && (
            <Button size="small" onClick={() => setShowAll((value) => !value)} sx={{ mt: 1 }}>
              {showAll ? 'Qisqartirish' : `Hammasi (${routes.length})`}
            </Button>
          )}
        </Box>
      )}
    </SectionCard>
  )
}

export default function RequestsPanel({ status }: { status: ApiRecord }) {
  const requests = status.requests || {}
  const thresholds = status.thresholds
  const hour = requests['60m'] || {}
  return (
    // `Stack` emas — `Grid` ning manfiy chekkasini o'chirardi (SystemStatus).
    <Box sx={{ display: 'grid', gap: { xs: 1.5, sm: 2.5 } }}>
      <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
        {WINDOWS.map((window) => (
          <Grid item xs={12} md={4} key={window.key}>
            <WindowCard label={window.label} data={requests[window.key] || {}} thresholds={thresholds} />
          </Grid>
        ))}
      </Grid>
      <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
        <Grid item xs={12} lg={5}>
          <Card sx={{ p: { xs: 2, sm: 2.5 }, height: '100%' }}>
            <Typography variant="subtitle2" fontWeight={650}>Status kodlari (1 soat)</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
              4xx — client xatosi (ruxsat, throttle), 5xx — server xatosi
            </Typography>
            {hour.count ? <StatusBar data={hour} /> : <Typography variant="body2" color="text.secondary">So‘rovlar yo‘q</Typography>}
          </Card>
        </Grid>
        <Grid item xs={12} lg={7}>
          <Card sx={{ p: { xs: 2, sm: 2.5 }, height: '100%' }}>
            <Typography variant="subtitle2" fontWeight={650}>Javob vaqti taqsimoti (1 soat)</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              Sariq/qizil ustunlar — SLO (p95 &lt; 500 ms) dan sekin so‘rovlar
            </Typography>
            <LatencyHistogram data={hour} thresholds={thresholds} />
          </Card>
        </Grid>
      </Grid>
      <RoutesTable thresholds={thresholds} />
    </Box>
  )
}
