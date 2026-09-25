import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { alpha, useTheme } from '@mui/material/styles'
import {
  Alert, Box, Card, CardHeader, Chip, Grid, IconButton, LinearProgress, Stack,
  Table, TableBody, TableCell, TableHead, TableRow, ToggleButton,
  ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import GroupsIcon from '@mui/icons-material/GroupsOutlined'
import PlayIcon from '@mui/icons-material/PlayCircleOutline'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import WarningIcon from '@mui/icons-material/ReportProblemOutlined'
import BuildIcon from '@mui/icons-material/BuildCircleOutlined'
import DoneIcon from '@mui/icons-material/TaskAltOutlined'
import RefreshIcon from '@mui/icons-material/RefreshOutlined'
import CloudOffIcon from '@mui/icons-material/CloudOffOutlined'
import CloudDoneIcon from '@mui/icons-material/CloudDoneOutlined'
import ArrowIcon from '@mui/icons-material/ArrowForwardOutlined'

import PageHeader from '../components/PageHeader'
import { TablePager } from '../components/data/DataTable'
import StatCard from '../components/StatCard'
import { ChartCard, DonutChart, RankedBarChart } from '../components/charts/ChartKit'
import { StatRowSkeleton } from '../components/feedback/Skeletons'
import { EmptyState, ErrorState } from '../components/feedback/States'
import { StaggerItem, useDeferredLoading } from '../components/motion/Transitions'
import { dashboard } from '../api/endpoints'
import { EVENT_LABEL } from '../utils/labels'

const REFRESH_OPTIONS = [
  { value: 0, label: 'Off' },
  { value: 15000, label: '15s' },
  { value: 60000, label: '1d' },
]

export default function Dashboard() {
  const navigate = useNavigate()
  const theme = useTheme()
  const [refreshMs, setRefreshMs] = useState(15000)

  const summaryQuery = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: () => dashboard.summary(),
    refetchInterval: refreshMs || false,
  })

  const zonesQuery = useQuery({
    queryKey: ['dashboard-zones'],
    queryFn: () => dashboard.zones(),
    refetchInterval: refreshMs || false,
  })

  const showSkeleton = useDeferredLoading(summaryQuery.isLoading)

  const summary = summaryQuery.data?.summary || {}
  const platform = summaryQuery.data?.external_platform || {}
  const zones = zonesQuery.data?.zones || []
  const platformDown = platform.state === 'open'

  const eventChart = useMemo(
    () =>
      (summaryQuery.data?.events || []).slice(0, 8).map((item) => ({
        name: EVENT_LABEL[item.type] || item.type,
        count: item.count,
        type: item.type,
      })),
    [summaryQuery.data],
  )

  const statusChart = useMemo(
    () =>
      [
        { name: 'Jarayonda', value: summary.in_progress || 0, status: 'in_progress', color: theme.palette.success.main },
        { name: 'Tayyor', value: summary.ready || 0, status: 'ready', color: theme.palette.info.main },
        { name: 'Tugatilgan', value: summary.finished || 0, status: 'finished', color: theme.palette.text.disabled },
        { name: 'Chetlashtirilgan', value: summary.terminated || 0, status: 'terminated', color: theme.palette.error.main },
        { name: 'Texnik muammo', value: summary.technical || 0, status: 'technical_problem', color: theme.palette.warning.main },
      ].filter((item) => item.value > 0),
    [summary, theme],
  )

  const goToSessions = (params) => {
    const query = new URLSearchParams(params).toString()
    navigate(`/sessions${query ? `?${query}` : ''}`)
  }

  if (summaryQuery.error && !summaryQuery.data) {
    return (
      <>
        <PageHeader title="Boshqaruv paneli" />
        <Card><ErrorState error={summaryQuery.error} onRetry={summaryQuery.refetch} /></Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Boshqaruv paneli"
        subtitle={`Bugungi imtihon holati${summary.date ? ` — ${summary.date}` : ''}`}
        actions={
          <Stack direction="row" spacing={1} alignItems="center">
            <Tooltip title={platformDown ? 'Tashqi platforma javob bermayapti' : 'Tashqi platforma normal'}>
              <Chip
                size="small"
                icon={platformDown ? <CloudOffIcon /> : <CloudDoneIcon />}
                color={platformDown ? 'error' : 'success'}
                variant={platformDown ? 'filled' : 'outlined'}
                label={platformDown ? 'ntest: uzilgan' : 'ntest: normal'}
              />
            </Tooltip>

            <ToggleButtonGroup
              size="small"
              exclusive
              value={refreshMs}
              onChange={(_, value) => value != null && setRefreshMs(value)}
            >
              {REFRESH_OPTIONS.map((option) => (
                <ToggleButton key={option.value} value={option.value} sx={{ px: 1.25 }}>
                  {option.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>

            <Tooltip title="Yangilash">
              <IconButton
                onClick={() => { summaryQuery.refetch(); zonesQuery.refetch() }}
                disabled={summaryQuery.isFetching}
              >
                <RefreshIcon
                  sx={{
                    animation: summaryQuery.isFetching ? 'spin 900ms linear infinite' : 'none',
                    '@keyframes spin': { to: { transform: 'rotate(360deg)' } },
                  }}
                />
              </IconButton>
            </Tooltip>
          </Stack>
        }
      />

      {platformDown && (
        <Alert severity="warning" sx={{ mb: 2.5 }}>
          Tashqi test platformasiga ulanish uzilgan (circuit breaker ochiq).
          Yangi talabgorlar imtihonni boshlay olmaydi; joriy sessiyalar davom etadi.
        </Alert>
      )}

      {/* --- Ko'rsatkichlar: har biri bosiladi va ro'yxatga filtr bilan o'tadi --- */}
      {showSkeleton ? (
        <StatRowSkeleton count={6} />
      ) : (
        <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
          {[
            { label: 'Jami sessiya', value: summary.total, icon: GroupsIcon, color: 'primary', params: {} },
            { label: 'Jarayonda', value: summary.in_progress, icon: PlayIcon, color: 'success', params: { status: 'in_progress' } },
            { label: 'Tugatilgan', value: summary.finished, icon: DoneIcon, color: 'info', params: { status: 'finished' } },
            { label: 'Yuqori xavf', value: summary.high_risk, icon: WarningIcon, color: 'warning', hint: 'Xavf ballari ≥ 50', to: '/live' },
            { label: 'Chetlashtirilgan', value: summary.terminated, icon: BlockIcon, color: 'error', params: { status: 'terminated' } },
            { label: 'Texnik muammo', value: summary.technical, icon: BuildIcon, color: 'warning', to: '/technical-problems' },
          ].map((tile, index) => (
            // Telefonda IKKI ustun: bittadan bo'lganda oltita karta ~900 px
            // egallab, grafiklarni birinchi ekrandan butunlay chiqarib yuborardi.
            <Grid item xs={6} sm={4} lg={2} key={tile.label}>
              <StaggerItem index={index}>
                <StatCard
                  label={tile.label}
                  value={tile.value}
                  icon={tile.icon}
                  color={tile.color}
                  hint={tile.hint}
                  onClick={() => (tile.to ? navigate(tile.to) : goToSessions(tile.params))}
                />
              </StaggerItem>
            </Grid>
          ))}
        </Grid>
      )}

      <Grid container spacing={{ xs: 1.5, sm: 2.5 }} sx={{ mt: { xs: 0, sm: 0.5 } }}>
        <Grid item xs={12} lg={7}>
          <ChartCard
            title="Eng ko‘p uchragan hodisalar"
            subheader="Ustunni bosing — o‘sha hodisa turi bo‘yicha sessiyalar ochiladi"
            loading={summaryQuery.isLoading}
            isEmpty={eventChart.length === 0}
            emptyText="Bugun hodisa qayd etilmagan"
            height={330}
          >
            <RankedBarChart
              data={eventChart}
              height={330}
              onSelect={(entry) => navigate(`/live?event=${entry.type}`)}
            />
          </ChartCard>
        </Grid>

        <Grid item xs={12} lg={5}>
          <ChartCard
            title="Sessiyalar taqsimoti"
            subheader="Segmentni bosing — filtrlangan ro‘yxat"
            loading={summaryQuery.isLoading}
            isEmpty={statusChart.length === 0}
            emptyText="Bugun sessiya yo‘q"
            height={280}
          >
            <DonutChart
              data={statusChart}
              height={280}
              centerLabel="Jami sessiya"
              onSelect={(entry) => goToSessions({ status: entry.status })}
            />
          </ChartCard>
        </Grid>

        <Grid item xs={12}>
          <Card>
            <CardHeader
              title="Binolar bo‘yicha kesim"
              subheader="Qatorni bosing — o‘sha binoning jonli kuzatuvi"
            />
            <ZoneTable
              zones={zones}
              loading={zonesQuery.isLoading}
              onSelect={(zone) => navigate(`/live?zone=${zone.id}`)}
            />
          </Card>
        </Grid>
      </Grid>
    </>
  )
}

function ZoneTable({ zones, loading, onSelect }) {
  const theme = useTheme()
  // Respublika administratori uchun bu yuzlab bino — sahifalanadi.
  // Ma'lumot bitta so'rovda keladi (dashboard kesimi), shuning uchun
  // sahifalash brauzerda; futer DataTable'niki bilan bir xil.
  const [page, setPage] = useState({ page: 0, pageSize: 25 })
  const visible = zones.slice(page.page * page.pageSize, (page.page + 1) * page.pageSize)

  if (loading) {
    return (
      <Box sx={{ p: 2 }}>
        {Array.from({ length: 4 }).map((_, index) => (
          <LinearProgress key={index} sx={{ my: 2, opacity: 1 - index * 0.2 }} />
        ))}
      </Box>
    )
  }

  if (!zones.length) {
    return <EmptyState title="Bino ma’lumoti yo‘q" description="Avval bino va kompyuterlarni qo‘shing" dense />
  }

  return (
    <>
    <Box sx={{ overflowX: 'auto' }}>
      {/* Telefonda siqilmaydi, suriladi — bino nomi 4 qatorga bo'linardi. */}
      <Table size="small" sx={{ minWidth: 760 }}>
        <TableHead>
          <TableRow>
            <TableCell align="right" width={52}>№</TableCell>
            <TableCell>Viloyat</TableCell>
            <TableCell>Bino</TableCell>
            <TableCell align="right">Jami</TableCell>
            <TableCell align="right">Faol</TableCell>
            <TableCell align="right">Chetlashtirilgan</TableCell>
            <TableCell align="right">Texnik</TableCell>
            <TableCell sx={{ minWidth: 190 }}>Bandlik</TableCell>
            <TableCell width={44} />
          </TableRow>
        </TableHead>
        <TableBody>
          {visible.map((zone, position) => {
            const index = page.page * page.pageSize + position
            const ratio = zone.total ? Math.round((zone.active / zone.total) * 100) : 0
            const hasIssues = zone.terminated > 0 || zone.problems > 0

            return (
              <TableRow
                key={zone.id}
                hover
                onClick={() => onSelect?.(zone)}
                sx={{
                  cursor: 'pointer',
                  // Muammoli bino chap chetida rangli chiziq bilan
                  // belgilanadi — ro'yxatni skanerlashda darhol ko'zga tashlanadi.
                  borderLeft: 3,
                  borderColor: hasIssues ? 'warning.main' : 'transparent',
                }}
              >
                <TableCell align="right">
                  <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {index + 1}
                  </Typography>
                </TableCell>
                <TableCell>{zone.region__name}</TableCell>
                <TableCell>
                  <Typography variant="body2" fontWeight={600}>
                    {zone.name} <Typography component="span" variant="caption" color="text.secondary">({zone.number})</Typography>
                  </Typography>
                </TableCell>
                <TableCell align="right">{zone.total}</TableCell>
                <TableCell align="right">
                  <Typography variant="body2" color="success.main" fontWeight={700}>{zone.active}</Typography>
                </TableCell>
                <TableCell align="right">
                  {zone.terminated > 0
                    ? <Chip size="small" color="error" label={zone.terminated} />
                    : <Typography variant="body2" color="text.disabled">—</Typography>}
                </TableCell>
                <TableCell align="right">
                  {zone.problems > 0
                    ? <Chip size="small" color="warning" label={zone.problems} />
                    : <Typography variant="body2" color="text.disabled">—</Typography>}
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Box
                      sx={{
                        flex: 1, height: 7, borderRadius: 999, overflow: 'hidden',
                        bgcolor: alpha(theme.palette.text.secondary, 0.14),
                      }}
                    >
                      <Box
                        sx={{
                          width: `${ratio}%`, height: '100%', borderRadius: 999,
                          bgcolor: 'success.main',
                          transition: (t) => t.transitions.create('width', { duration: 420 }),
                        }}
                      />
                    </Box>
                    <Typography variant="caption" fontWeight={700} sx={{ minWidth: 34 }}>
                      {ratio}%
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>
                  <ArrowIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </Box>
    {zones.length > 25 && (
      <TablePager
        rowCount={zones.length}
        rowsOnPage={visible.length}
        paginationModel={page}
        onPaginationModelChange={setPage}
      />
    )}
    </>
  )
}
