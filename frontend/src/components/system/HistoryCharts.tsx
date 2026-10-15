import { memo, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { alpha, useTheme } from '@mui/material/styles'
import { Box, Card, Grid, Stack, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import {
  Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { system } from '../../api/endpoints'
import { ChartSkeleton } from '../feedback/Skeletons'
import { EmptyState } from '../feedback/States'
import { bitRate, byteRate, bytes, clock, ms, num, pct } from './format'
import type { ApiRecord } from '../../types/api'

type Formatter = (value: number | null | undefined) => string

interface Series {
  key: string
  name: string
  color: string
  kind?: 'area' | 'line'
  stack?: string
  axis?: 'left' | 'right'
  format?: Formatter
}

interface TimeChartProps {
  title: string
  subtitle?: string
  data: ApiRecord[]
  series: Series[]
  format: Formatter
  rightFormat?: Formatter
  domain?: [number, number | 'auto']
  height?: number
}

function ChartTip({ active, payload, label, series }: ApiRecord) {
  if (!active || !payload?.length) return null
  return (
    <Box sx={{ bgcolor: 'background.paper', border: 1, borderColor: 'divider', borderRadius: '12px', boxShadow: 4, px: 1.5, py: 1, minWidth: 170 }}>
      <Typography variant="caption" color="text.secondary" fontWeight={650}>{clock(label)}</Typography>
      {payload.map((entry: ApiRecord) => {
        const def = (series as Series[]).find((item) => item.key === entry.dataKey)
        return (
          <Stack key={entry.dataKey} direction="row" spacing={1} alignItems="center" sx={{ mt: 0.25 }}>
            <Box sx={{ width: 9, height: 9, borderRadius: '3px', bgcolor: entry.color }} />
            <Typography variant="body2" sx={{ flex: 1 }}>{entry.name}</Typography>
            <Typography variant="body2" fontWeight={700}>{def?.format ? def.format(entry.value) : entry.value}</Typography>
          </Stack>
        )
      })}
    </Box>
  )
}

const TimeChart = memo(function TimeChart({
  title, subtitle, data, series, format, rightFormat, domain, height = 210,
}: TimeChartProps) {
  const theme = useTheme()
  const hasRight = series.some((item) => item.axis === 'right')
  const tick = { fontSize: 11, fill: theme.chart.axis }
  return (
    <Card sx={{ p: { xs: 2, sm: 2.5 }, height: '100%' }}>
      <Typography variant="subtitle2" fontWeight={650}>{title}</Typography>
      {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
      <Stack direction="row" flexWrap="wrap" useFlexGap gap={1.5} sx={{ mt: 0.75, mb: 1 }}>
        {series.map((item) => (
          <Stack key={item.key} direction="row" spacing={0.5} alignItems="center">
            <Box sx={{ width: 10, height: 3, borderRadius: 2, bgcolor: item.color }} />
            <Typography variant="caption" color="text.secondary">{item.name}</Typography>
          </Stack>
        ))}
      </Stack>
      <Box sx={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: hasRight ? 0 : 8, left: 0, bottom: 0 }} syncId="system-history">
            <defs>
              {series.map((item) => (
                <linearGradient key={item.key} id={`sys-${item.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={item.color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={item.color} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={theme.chart.grid} />
            <XAxis
              dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']}
              tickFormatter={clock} tick={tick} axisLine={false} tickLine={false} minTickGap={36}
            />
            <YAxis
              yAxisId="left" tick={tick} axisLine={false} tickLine={false} width={64}
              tickFormatter={(value: number) => format(value)} domain={domain || [0, 'auto']}
            />
            {hasRight && (
              <YAxis
                yAxisId="right" orientation="right" tick={tick} axisLine={false} tickLine={false} width={56}
                tickFormatter={(value: number) => (rightFormat || format)(value)}
              />
            )}
            <Tooltip content={<ChartTip series={series} />} cursor={{ stroke: alpha(theme.palette.primary.main, 0.35) }} />
            {series.map((item) => (item.kind === 'line' ? (
              <Line
                key={item.key} yAxisId={item.axis || 'left'} type="monotone" dataKey={item.key} name={item.name}
                stroke={item.color} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls
              />
            ) : (
              <Area
                key={item.key} yAxisId={item.axis || 'left'} type="monotone" dataKey={item.key} name={item.name}
                stroke={item.color} strokeWidth={1.75} fill={`url(#sys-${item.key})`} stackId={item.stack}
                dot={false} isAnimationActive={false} connectNulls
              />
            )))}
          </ComposedChart>
        </ResponsiveContainer>
      </Box>
    </Card>
  )
})

const RANGES = [
  { value: '1h', label: '1 soat' },
  { value: '6h', label: '6 soat' },
  { value: '24h', label: '24 soat' },
]

interface HistoryChartsProps {
  range: string
  onRange: (range: string) => void
}

/**
 * Tarix grafiklari: barchasi bitta vaqt o'qida (`syncId`) — kursor bitta
 * lahzani hamma grafikda ko'rsatadi ("p95 o'sgan paytda CPU/disk qanday edi").
 */
export default function HistoryCharts({ range, onRange }: HistoryChartsProps) {
  const theme = useTheme()
  const query = useQuery({
    queryKey: ['system-history', range],
    queryFn: () => system.history(range),
    refetchInterval: 30000,
  })
  const host: ApiRecord[] = query.data?.host || []
  const requests: ApiRecord[] = query.data?.requests || []
  const c = theme.chart.colors
  const p = theme.palette

  const charts = useMemo(() => {
    const percent: Formatter = (value) => pct(value, 0)
    // Kichik qiymatlarda (0.2 so'rov/s) butun son o'qda "0 0 0" bo'lardi.
    const count: Formatter = (value) => num(value, value != null && Math.abs(value) < 10 ? 1 : 0)
    return [
      {
        title: 'Protsessor', subtitle: 'Ustma-ust: foydalanuvchi, tizim, disk kutish, steal (ESXi)',
        data: host, format: percent, domain: [0, 100] as [number, number],
        series: [
          { key: 'user', name: 'Foydalanuvchi', color: c[0], stack: 'cpu', format: percent },
          { key: 'system', name: 'Tizim', color: c[1], stack: 'cpu', format: percent },
          { key: 'iowait', name: 'iowait', color: p.warning.main, stack: 'cpu', format: percent },
          { key: 'steal', name: 'Steal', color: p.error.main, stack: 'cpu', format: percent },
        ],
      },
      {
        title: 'Xotira', data: host, format: percent, domain: [0, 100] as [number, number],
        series: [
          { key: 'mem', name: 'RAM', color: c[2], format: percent },
          { key: 'swap', name: 'Swap', color: p.error.main, kind: 'line' as const, format: percent },
        ],
      },
      {
        title: 'So‘rovlar', subtitle: 'Sekundiga so‘rov va p95 javob vaqti',
        data: requests, format: count, rightFormat: ms,
        series: [
          { key: 'rps', name: 'so‘rov/s', color: c[0], format: (value: number | null | undefined) => num(value, 1) },
          { key: 'p95_ms', name: 'p95', color: p.warning.main, kind: 'line' as const, axis: 'right' as const, format: ms },
        ],
      },
      {
        title: 'Xatolar', subtitle: 'Oraliqdagi soni: 5xx, 429 (throttle), 4xx',
        data: requests, format: count,
        series: [
          { key: 'c5', name: '5xx', color: p.error.main, kind: 'line' as const, format: count },
          { key: 's429', name: '429', color: p.warning.main, kind: 'line' as const, format: count },
          { key: 'c4', name: '4xx', color: c[3], kind: 'line' as const, format: count },
        ],
      },
      {
        title: 'Yuklama va imtihondagilar', subtitle: 'load average (chap) va jarayondagi sessiyalar (o‘ng)',
        data: host, format: (value: number | null | undefined) => num(value, 1), rightFormat: count,
        series: [
          { key: 'sessions', name: 'Sessiyalar', color: c[4], axis: 'right' as const, format: count },
          { key: 'load1', name: 'load 1m', color: c[0], kind: 'line' as const, format: (value: number | null | undefined) => num(value, 2) },
        ],
      },
      {
        title: 'Disk', subtitle: 'O‘qish/yozish tezligi va eng band qurilma',
        data: host, format: (value: number | null | undefined) => bytes(value, 0), rightFormat: percent,
        series: [
          { key: 'disk_w', name: 'Yozish', color: c[1], format: byteRate },
          { key: 'disk_r', name: 'O‘qish', color: c[0], format: byteRate },
          { key: 'disk_util', name: 'Bandlik', color: p.warning.main, kind: 'line' as const, axis: 'right' as const, format: percent },
        ],
      },
      {
        title: 'Tarmoq', data: host, format: (value: number | null | undefined) => bitRate(value).replace('/s', ''),
        series: [
          { key: 'net_rx', name: 'Kiruvchi', color: c[0], format: bitRate },
          { key: 'net_tx', name: 'Chiquvchi', color: c[2], format: bitRate },
        ],
      },
      {
        title: 'Ma’lumotlar oqimi', subtitle: 'PostgreSQL tranz/s, Redis oqimi orqada (lag), WebSocket',
        data: host, format: count, rightFormat: count,
        series: [
          { key: 'pg_tps', name: 'tranz/s', color: c[0], format: (value: number | null | undefined) => num(value, 0) },
          { key: 'ws', name: 'WebSocket', color: c[2], kind: 'line' as const, format: count },
          { key: 'lag', name: 'lag', color: p.error.main, kind: 'line' as const, axis: 'right' as const, format: count },
        ],
      },
    ]
  }, [host, requests, c, p])

  return (
    <Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1} sx={{ mb: 1.5 }}>
        <Box>
          <Typography variant="subtitle1" fontWeight={650}>Tarix</Typography>
          <Typography variant="caption" color="text.secondary">
            Har 30 s da bitta nuqta (Celery beat); so‘rovlar — daqiqalik
          </Typography>
        </Box>
        <ToggleButtonGroup size="small" exclusive value={range} onChange={(_, value) => value && onRange(value)}>
          {RANGES.map((item) => (
            <ToggleButton key={item.value} value={item.value} sx={{ px: 1.5 }}>{item.label}</ToggleButton>
          ))}
        </ToggleButtonGroup>
      </Stack>
      {query.isLoading ? (
        <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
          {[0, 1, 2, 3].map((index) => (
            <Grid item xs={12} lg={6} key={index}><Card sx={{ p: 2 }}><ChartSkeleton height={220} /></Card></Grid>
          ))}
        </Grid>
      ) : !host.length && !requests.length ? (
        <Card>
          <EmptyState
            title="Tarix hali yo‘q"
            description="Nuqtalarni `monitoring.sample_system` vazifasi yozadi — Celery beat va maintenance ishchisi ishlayotganini tekshiring."
            dense
          />
        </Card>
      ) : (
        <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
          {charts.map((chart) => (
            <Grid item xs={12} lg={6} key={chart.title}>
              <TimeChart {...chart} />
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  )
}
