import { Box, Grid, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import LanIcon from '@mui/icons-material/LanOutlined'
import PortIcon from '@mui/icons-material/SettingsInputComponentOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import RouterIcon from '@mui/icons-material/RouterOutlined'

import { bitRate, levelOf, nginxError, num, pct } from './format'
import { Metric, MetricGrid, Mono, SectionCard, Unavailable } from './parts'
import type { ApiRecord } from '../../types/api'

const PORT_LABEL: Record<string, string> = {
  nginx_https: 'nginx (HTTPS)',
  nginx_http: 'nginx (HTTP)',
  api: 'HTTP API (gunicorn)',
  ws: 'WebSocket (uvicorn)',
  pgbouncer: 'PgBouncer',
  postgres: 'PostgreSQL',
  redis: 'Redis',
}

export default function NetworkPanel({ status }: { status: ApiRecord }) {
  const thresholds = status.thresholds
  const interfaces: ApiRecord[] = status.network?.interfaces || []
  const sockets = status.sockets || {}
  const ports: ApiRecord[] = sockets.ports || []
  const limits = status.limits || {}
  const nginx = status.nginx || {}

  return (
    <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
      <Grid item xs={12} lg={6}>
        <SectionCard icon={LanIcon} title="Tarmoq interfeyslari" subtitle="Tezlik — bit/s (tarmoq uskunalari birligida)">
          {!interfaces.length ? <Unavailable>Faol interfeys topilmadi.</Unavailable> : (
            <Box sx={{ overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
              <Table size="small" sx={{ minWidth: 460, '& td, & th': { whiteSpace: 'nowrap' } }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Interfeys</TableCell>
                    <TableCell align="right">Kiruvchi</TableCell>
                    <TableCell align="right">Chiquvchi</TableCell>
                    <TableCell align="right">Yuklama</TableCell>
                    <TableCell align="right">Xato/s</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {interfaces.map((nic) => (
                    <TableRow key={nic.name}>
                      <TableCell>
                        <Mono>{nic.name}</Mono>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                          {nic.speed_mbps ? `${num(nic.speed_mbps)} Mbit/s` : 'tezlik noma’lum'}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">{bitRate(nic.rx_bps)}</TableCell>
                      <TableCell align="right">{bitRate(nic.tx_bps)}</TableCell>
                      <TableCell align="right">{pct(nic.util_pct)}</TableCell>
                      <TableCell align="right" sx={{ color: nic.errors_per_s ? 'warning.main' : 'text.disabled' }}>
                        {num(nic.errors_per_s, 2)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}
        </SectionCard>
      </Grid>
      <Grid item xs={12} lg={6}>
        <SectionCard
          icon={PortIcon}
          title="Portlar"
          subtitle="Qabul navbati (backlog) va ochiq ulanishlar — `ss -ltn` / `ss -tn`"
        >
          {!sockets.available ? <Unavailable>Soket statistikasi o‘qilmadi.</Unavailable> : (
            <Box sx={{ overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
              <Table size="small" sx={{ minWidth: 420 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Xizmat</TableCell>
                    <TableCell align="right">Port</TableCell>
                    <TableCell align="right">Ulanishlar</TableCell>
                    <TableCell align="right">Navbat</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {ports.map((port) => {
                    const backlog = levelOf(thresholds, 'listen_backlog', port.backlog)
                    return (
                      <TableRow key={port.name}>
                        <TableCell>{PORT_LABEL[port.name] || port.name}</TableCell>
                        <TableCell align="right"><Mono>{port.port}</Mono></TableCell>
                        <TableCell align="right">{num(port.established)}</TableCell>
                        <TableCell
                          align="right"
                          sx={{ color: backlog === 'ok' ? 'text.disabled' : `${backlog === 'critical' ? 'error' : 'warning'}.main`, fontWeight: 600 }}
                        >
                          {sockets.source === 'proc' ? num(port.backlog) : '—'}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </Box>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Navbat 0 dan katta bo‘lib tursa — worker’lar ulanishlarni qabul qilishga ulgurmayapti.
          </Typography>
        </SectionCard>
      </Grid>
      <Grid item xs={12} lg={6}>
        <SectionCard icon={RouterIcon} title="nginx" subtitle="stub_status">
          {!nginx.available ? (
            <Unavailable>
              {nginx.configured
                ? <>{nginxError(nginx.error)}{nginx.url && <><br /><Mono>{nginx.url}</Mono></>}</>
                : 'Sozlanmagan: `.env` da `SYSTEM_MONITOR_NGINX_STATUS_URL=https://127.0.0.1/nginx_status`.'}
            </Unavailable>
          ) : (
            <MetricGrid min={120}>
              <Metric label="Faol ulanish" value={num(nginx.active)} />
              <Metric label="So‘rov/s" value={num(nginx.requests_per_s, 1)} />
              <Metric label="O‘qimoqda" value={num(nginx.reading)} />
              <Metric label="Yozmoqda" value={num(nginx.writing)} />
              <Metric label="Kutmoqda (keep-alive)" value={num(nginx.waiting)} />
              <Metric
                label="Tashlangan ulanish"
                value={num(nginx.dropped_total)}
                level={nginx.dropped_total ? 'warning' : undefined}
                tooltip="accepts − handled: worker_connections chegarasi"
              />
            </MetricGrid>
          )}
        </SectionCard>
      </Grid>
      <Grid item xs={12} lg={6}>
        <SectionCard icon={TuneIcon} title="Yadro chegaralari" subtitle="Ochiq fayllar va TCP soketlar (butun server)">
          {!Object.keys(limits).length ? <Unavailable>Faqat Linux’da (`/proc`).</Unavailable> : (
            <MetricGrid min={140}>
              <Metric
                label="Ochiq fayllar"
                value={pct(limits.files_percent)}
                hint={`${num(limits.files_open)} / ${num(limits.files_max)}`}
                level={levelOf(thresholds, 'fd_pct', limits.files_percent)}
              />
              <Metric label="TCP ishlatilmoqda" value={num(limits.tcp_inuse)} />
              <Metric
                label="TIME_WAIT"
                value={num(limits.tcp_time_wait)}
                tooltip="Ko'p bo'lsa — kimdir har so'rovga yangi TCP ulanish ochyapti (ulanish pool'i ishlamayapti)"
              />
              <Metric label="Yetim (orphan)" value={num(limits.tcp_orphan)} />
            </MetricGrid>
          )}
        </SectionCard>
      </Grid>
    </Grid>
  )
}
