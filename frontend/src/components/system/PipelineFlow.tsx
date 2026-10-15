import type { ComponentType, ReactNode } from 'react'
import { alpha, useTheme } from '@mui/material/styles'
import type { SvgIconProps } from '@mui/material'
import { Box, Card, Stack, Typography } from '@mui/material'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'
import RouterIcon from '@mui/icons-material/RouterOutlined'
import ApiIcon from '@mui/icons-material/ApiOutlined'
import BoltIcon from '@mui/icons-material/BoltOutlined'
import StreamIcon from '@mui/icons-material/StreamOutlined'
import TaskIcon from '@mui/icons-material/SettingsSuggestOutlined'
import StorageIcon from '@mui/icons-material/StorageOutlined'
import ImageIcon from '@mui/icons-material/PhotoLibraryOutlined'
import ArrowIcon from '@mui/icons-material/EastRounded'

import { bytes, duration, levelOf, ms, num, pct, worst } from './format'
import type { Level } from './format'
import { Dot, levelColor } from './parts'
import type { ApiRecord } from '../../types/api'

interface StageProps {
  icon: ComponentType<SvgIconProps>
  title: string
  level: Level
  primary: ReactNode
  lines: ReactNode[]
}

function Stage({ icon: Icon, title, level, primary, lines }: StageProps) {
  const theme = useTheme()
  const color = level === 'ok' || level === 'unknown' ? theme.palette.primary.main : levelColor(theme, level)
  return (
    <Box
      sx={{
        p: 1.75, borderRadius: '20px', minWidth: 0, height: '100%',
        bgcolor: level === 'ok' || level === 'unknown' ? 'm3.surfaceContainerLow' : alpha(color, 0.1),
        border: `1px solid ${level === 'ok' || level === 'unknown' ? 'transparent' : alpha(color, 0.4)}`,
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Box
          sx={{
            width: 32, height: 32, borderRadius: '10px', display: 'grid', placeItems: 'center',
            bgcolor: alpha(color, 0.14), color,
          }}
        >
          <Icon sx={{ fontSize: 19 }} />
        </Box>
        <Typography variant="body2" fontWeight={650} noWrap sx={{ flex: 1 }}>{title}</Typography>
        <Dot level={level === 'unknown' ? 'unknown' : level} pulse={level === 'critical'} />
      </Stack>
      <Typography variant="h6" fontWeight={700} noWrap sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.3 }}>
        {primary}
      </Typography>
      {lines.map((line, index) => (
        // eslint-disable-next-line react/no-array-index-key
        <Typography key={index} variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
          {line}
        </Typography>
      ))}
    </Box>
  )
}

/**
 * Imtihon ma'lumoti qanday oqadi: client → nginx → API / WebSocket →
 * Redis oqimi → Celery ingest → PostgreSQL, rasmlar → disk.
 *
 * Bitta bosqich qizarsa, "qayerda tiqildi" savoliga javob shu yerda:
 * masalan API tez, lekin `lag` o'syapti — muammo ingest'da, nginx'da emas.
 */
export default function PipelineFlow({ status }: { status: ApiRecord }) {
  const theme = useTheme()
  const t = status.thresholds
  const process = status.process || {}
  const sessions = process.sessions || {}
  const computers = process.computers || {}
  const nginx = status.nginx || {}
  const minute = status.requests?.['1m'] || {}
  const five = status.requests?.['5m'] || {}
  const ports: ApiRecord[] = status.sockets?.ports || []
  const port = (name: string) => ports.find((item) => item.name === name)
  const events = (status.streams?.streams || []).find((item: ApiRecord) => item.name === 'events') || {}
  const tasks: ApiRecord[] = status.celery?.tasks || []
  const flush = tasks.find((item) => item.name === 'flush-event-buffer') || {}
  const ingestQueue = (status.celery?.queues || []).find((item: ApiRecord) => item.name === 'ingest')
  const pg = status.postgres || {}
  const shotsDisk = (status.disks?.mounts || []).find((item: ApiRecord) => (item.contains || []).includes('screenshots'))
  const storage = status.storage?.screenshots

  const apiLevel = five.count >= 50
    ? worst(levelOf(t, 'http_5xx_pct', five.error_pct), levelOf(t, 'http_p95_ms', five.p95_ms), levelOf(t, 'listen_backlog', port('api')?.backlog))
    : levelOf(t, 'listen_backlog', port('api')?.backlog)
  const ingestLevel: Level = flush.health === 'stale'
    ? 'critical'
    : worst(levelOf(t, 'celery_queue', ingestQueue?.length), flush.health === 'ok' ? 'ok' : 'unknown')

  const stages: StageProps[] = [
    {
      icon: ComputerIcon,
      title: 'Clientlar',
      level: sessions.silent ? 'warning' : 'ok',
      primary: `${num(sessions.in_progress)} imtihonda`,
      lines: [
        `${num((computers.online || 0) + (computers.in_exam || 0))} / ${num(computers.total)} kompyuter onlayn`,
        sessions.silent ? `${num(sessions.silent)} ta sessiyadan signal yo‘q` : `${num(sessions.open)} ochiq sessiya`,
      ],
    },
    {
      icon: RouterIcon,
      title: 'nginx',
      level: nginx.available ? (nginx.dropped_total > 0 ? 'warning' : 'ok') : 'unknown',
      primary: nginx.available ? `${num(nginx.active)} ulanish` : 'stub_status yo‘q',
      lines: nginx.available
        ? [`${num(nginx.requests_per_s, 1)} so‘rov/s`, `kutmoqda ${num(nginx.waiting)} · yozmoqda ${num(nginx.writing)}`]
        : [port('nginx_https') ? `${num(port('nginx_https')?.established)} HTTPS ulanish` : 'SYSTEM_MONITOR_NGINX_STATUS_URL'],
    },
    {
      icon: ApiIcon,
      title: 'HTTP API',
      level: apiLevel,
      primary: `${num(minute.rps, 1)} so‘rov/s`,
      lines: [
        `p95 ${ms(five.p95_ms)} · 5xx ${pct(five.error_pct, 2)}`,
        port('api') ? `navbat (backlog): ${num(port('api')?.backlog)}` : '5 daqiqalik ko‘rsatkich',
      ],
    },
    {
      icon: BoltIcon,
      title: 'WebSocket',
      level: port('ws') ? 'ok' : 'unknown',
      primary: port('ws') ? `${num(port('ws')?.established)} ulanish` : '—',
      lines: ['proktor buyruqlari va jonli kuzatuv'],
    },
    {
      icon: StreamIcon,
      title: 'Redis oqimi',
      level: worst(levelOf(t, 'stream_lag', events.lag), events.dead ? 'warning' : 'ok'),
      primary: `${num(events.in_per_s, 1)} hodisa/s`,
      lines: [`orqada (lag): ${num(events.lag)}`, `yozilmagan (:dead): ${num(events.dead)}`],
    },
    {
      icon: TaskIcon,
      title: 'Celery ingest',
      level: ingestLevel,
      primary: flush.last_run_age_s != null ? `${duration(flush.last_run_age_s)} oldin` : 'kuzatilmagan',
      lines: [
        `flush: ${flush.last_runtime_s != null ? ms(flush.last_runtime_s * 1000) : '—'}`,
        `navbat: ${num(ingestQueue?.length)}`,
      ],
    },
    {
      icon: StorageIcon,
      title: 'PostgreSQL',
      level: worst(
        levelOf(t, 'pg_connections_pct', pg.connections?.percent),
        levelOf(t, 'pg_idle_in_tx_s', pg.connections?.longest_idle_tx_s),
      ),
      primary: `${num(pg.rates?.commits_per_s, 0)} tranz/s`,
      lines: [
        `ulanish ${num(pg.connections?.total)} / ${num(pg.max_connections)}`,
        `yozish ${num(pg.rates?.inserts_per_s, 0)}/s · kesh ${pct(pg.rates?.cache_hit_pct)}`,
      ],
    },
    {
      icon: ImageIcon,
      title: 'Rasmlar (disk)',
      level: shotsDisk
        ? worst(levelOf(t, 'disk_pct', shotsDisk.percent), levelOf(t, 'disk_days_left', shotsDisk.days_left))
        : 'unknown',
      primary: shotsDisk ? `${bytes(shotsDisk.free, 0)} bo‘sh` : '—',
      lines: [
        storage ? `bugun +${num(storage.today_count)} (${bytes(storage.today_bytes)})` : 'hajm hali hisoblanmagan',
        shotsDisk?.days_left != null ? `~${shotsDisk.days_left} kunga yetadi` : (shotsDisk?.mount || ''),
      ],
    },
  ]

  return (
    <Card sx={{ p: { xs: 2, sm: 2.5 } }}>
      <Typography variant="subtitle1" fontWeight={650}>Imtihon ma’lumoti oqimi</Typography>
      <Typography variant="caption" color="text.secondary">
        Client so‘rovi qayerdan o‘tadi — qizargan bosqich tiqilgan joy
      </Typography>
      <Box
        sx={{
          mt: 2, display: 'grid', gap: 1,
          gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)', xl: 'repeat(8, minmax(0, 1fr))' },
          alignItems: 'stretch',
          // Keng ekranda bosqichlar orasida strelka.
          '& > .stage': { position: 'relative' },
          [theme.breakpoints.up('xl')]: {
            '& > .stage:not(:last-of-type)::after': {
              content: '""', position: 'absolute', right: -8, top: '50%', width: 8, height: 2,
              bgcolor: theme.palette.m3.outlineVariant,
            },
          },
        }}
      >
        {stages.map((stage) => (
          <Box className="stage" key={stage.title}>
            <Stage {...stage} />
          </Box>
        ))}
      </Box>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 1.5, color: 'text.disabled', display: { xs: 'none', md: 'flex' } }}>
        <Typography variant="caption">client</Typography>
        <ArrowIcon sx={{ fontSize: 14 }} />
        <Typography variant="caption">nginx</Typography>
        <ArrowIcon sx={{ fontSize: 14 }} />
        <Typography variant="caption">API / WebSocket</Typography>
        <ArrowIcon sx={{ fontSize: 14 }} />
        <Typography variant="caption">Redis (XADD, darhol javob)</Typography>
        <ArrowIcon sx={{ fontSize: 14 }} />
        <Typography variant="caption">Celery (5 s da bulk)</Typography>
        <ArrowIcon sx={{ fontSize: 14 }} />
        <Typography variant="caption">PostgreSQL</Typography>
      </Stack>
    </Card>
  )
}
