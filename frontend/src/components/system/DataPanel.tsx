import { useTheme } from '@mui/material/styles'
import { Box, Chip, Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from '@mui/material'
import PostgresIcon from '@mui/icons-material/StorageOutlined'
import RedisIcon from '@mui/icons-material/BoltOutlined'
import StreamIcon from '@mui/icons-material/StreamOutlined'
import TaskIcon from '@mui/icons-material/SettingsSuggestOutlined'

import { bytes, byteRate, duration, levelOf, ms, num, pct, worst } from './format'
import type { Level } from './format'
import { Dot, LevelChip, levelColor, Meter, Metric, MetricGrid, Mono, SectionCard, Unavailable } from './parts'
import type { ApiRecord } from '../../types/api'

function PostgresCard({ pg, thresholds, error }: { pg: ApiRecord | null; thresholds: ApiRecord; error?: string }) {
  if (!pg) {
    return (
      <SectionCard icon={PostgresIcon} title="PostgreSQL" level="critical">
        <Unavailable>Ulanib bo‘lmadi: {error || 'noma’lum xato'}</Unavailable>
      </SectionCard>
    )
  }
  const conn = pg.connections || {}
  const rates = pg.rates || {}
  const connLevel = levelOf(thresholds, 'pg_connections_pct', conn.percent)
  const level = worst(
    connLevel,
    levelOf(thresholds, 'pg_idle_in_tx_s', conn.longest_idle_tx_s),
    levelOf(thresholds, 'pg_long_query_s', conn.longest_query_s),
  )
  const tables: ApiRecord[] = pg.tables || []
  return (
    <SectionCard
      icon={PostgresIcon}
      title="PostgreSQL"
      subtitle={`${pg.version} · ${pg.database} · ${bytes(pg.size)} · ishlayapti ${duration(pg.uptime_s)}`}
      level={level}
    >
      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
        <Typography variant="caption" color="text.secondary" fontWeight={600}>Ulanishlar</Typography>
        <Typography variant="caption" fontWeight={700}>{num(conn.total)} / {num(pg.max_connections)}</Typography>
      </Stack>
      <Meter value={conn.percent} level={connLevel} />
      <Box sx={{ mt: 1.5 }}>
        <MetricGrid min={120}>
          <Metric label="Faol" value={num(conn.active)} />
          <Metric label="Bo‘sh (idle)" value={num(conn.idle)} />
          <Metric
            label="Ochiq tranzaksiya"
            value={num(conn.idle_in_transaction)}
            hint={conn.idle_in_transaction ? `eng uzuni ${duration(conn.longest_idle_tx_s)}` : undefined}
            level={levelOf(thresholds, 'pg_idle_in_tx_s', conn.longest_idle_tx_s)}
          />
          <Metric label="Qulf kutmoqda" value={num(conn.lock_waiting)} level={conn.lock_waiting ? 'warning' : undefined} />
          <Metric
            label="Eng uzun so‘rov"
            value={duration(conn.longest_query_s)}
            level={levelOf(thresholds, 'pg_long_query_s', conn.longest_query_s)}
          />
          <Metric label="Tranz/s" value={num(rates.commits_per_s, 0)} hint={`rollback ${num(rates.rollbacks_per_s, 1)}/s`} />
          <Metric label="Yozish/s" value={num(rates.inserts_per_s, 0)} hint={`yangilash ${num(rates.updates_per_s, 0)}/s`} />
          <Metric
            label="Kesh samarasi"
            value={pct(rates.cache_hit_pct, 2)}
            level={(rates.commits_per_s || 0) >= 5 ? levelOf(thresholds, 'pg_cache_hit_pct', rates.cache_hit_pct) : undefined}
            tooltip="Bloklarning xotiradan o'qilgan ulushi; < 99% — shared_buffers yetmayapti"
          />
          <Metric label="Vaqtinchalik fayl" value={byteRate(rates.temp_bytes_per_s)} tooltip="work_mem yetmagan saralash/hash" />
          <Metric label="Deadlock (jami)" value={num(pg.deadlocks_total)} />
        </MetricGrid>
      </Box>
      {tables.length > 0 && (
        <Box sx={{ mt: 2, overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
          <Typography variant="caption" color="text.secondary" fontWeight={600}>Eng katta jadvallar</Typography>
          <Table size="small" sx={{ minWidth: 420 }}>
            <TableHead>
              <TableRow>
                <TableCell>Jadval</TableCell>
                <TableCell align="right">Hajm</TableCell>
                <TableCell align="right">Qatorlar</TableCell>
                <TableCell align="right">O‘lik qator</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tables.map((table) => {
                // Kichik jadvalda `reltuples` taxmini eskirgan bo'ladi (ANALYZE
                // hali yurmagan) va ulush ma'nosiz katta chiqadi — ko'rsatilmaydi.
                const sample = table.rows + table.dead_rows
                const deadShare = sample >= 1000 ? (table.dead_rows / sample) * 100 : null
                return (
                  <TableRow key={table.name}>
                    <TableCell>
                      <Mono>{table.name}</Mono>
                      {table.partitions > 0 && (
                        <Typography component="span" variant="caption" color="text.secondary"> · {table.partitions} partitsiya</Typography>
                      )}
                    </TableCell>
                    <TableCell align="right">{bytes(table.size)}</TableCell>
                    <TableCell align="right">~{num(table.rows)}</TableCell>
                    <TableCell align="right" sx={{ color: (deadShare ?? 0) > 20 ? 'warning.main' : 'text.secondary' }}>
                      <Tooltip title="Autovacuum hali tozalamagan qatorlar">
                        <span>{pct(deadShare, 0)}</span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Box>
      )}
    </SectionCard>
  )
}

function RedisCard({ redis, thresholds, error }: { redis: ApiRecord | null; thresholds: ApiRecord; error?: string }) {
  if (!redis) {
    return (
      <SectionCard icon={RedisIcon} title="Redis" level="critical">
        <Unavailable>Ulanib bo‘lmadi: {error || 'noma’lum xato'}</Unavailable>
      </SectionCard>
    )
  }
  const rates = redis.rates || {}
  const memLevel = levelOf(thresholds, 'redis_memory_pct', redis.memory_percent)
  const policyOk = redis.maxmemory_policy === 'noeviction'
  const level = worst(memLevel, policyOk ? 'ok' : 'critical', levelOf(thresholds, 'redis_cpu_pct', rates.cpu_pct))
  const keyspace = Object.entries(redis.keyspace || {}) as [string, number][]
  return (
    <SectionCard
      icon={RedisIcon}
      title="Redis"
      subtitle={`v${redis.version} · ishlayapti ${duration(redis.uptime_s)}`}
      level={level}
    >
      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
        <Typography variant="caption" color="text.secondary" fontWeight={600}>Xotira</Typography>
        <Typography variant="caption" fontWeight={700}>
          {bytes(redis.used_memory)} / {redis.maxmemory ? bytes(redis.maxmemory) : 'cheklanmagan'}
        </Typography>
      </Stack>
      <Meter value={redis.memory_percent ?? 0} level={redis.maxmemory ? memLevel : 'warning'} />
      <Box sx={{ mt: 1.5 }}>
        <MetricGrid min={120}>
          <Metric
            label="Siyosat"
            value={redis.maxmemory_policy || '—'}
            level={policyOk ? 'ok' : 'critical'}
            tooltip="noeviction SHART: boshqasi sessiya tokenlarini o'chiradi"
          />
          <Metric
            label="Yadro (bitta)"
            value={pct(rates.cpu_pct)}
            level={levelOf(thresholds, 'redis_cpu_pct', rates.cpu_pct)}
            tooltip="Redis buyruqlarni bitta yadroda bajaradi — 100% uning shifti"
          />
          <Metric label="Buyruq/s" value={num(rates.commands_per_s, 0)} />
          <Metric label="Clientlar" value={num(redis.clients)} hint={`bloklangan ${num(redis.blocked_clients)}`} />
          <Metric label="Kesh topilishi" value={pct(rates.hit_pct)} />
          <Metric label="Fragmentatsiya" value={redis.fragmentation != null ? num(redis.fragmentation, 2) : '—'} />
          <Metric
            label="Diskka saqlash"
            value={redis.rdb_last_bgsave_status === 'ok' ? 'OK' : (redis.rdb_last_bgsave_status || '—')}
            hint={redis.rdb_last_save_age_s != null ? `${duration(redis.rdb_last_save_age_s)} oldin` : undefined}
            level={redis.rdb_last_bgsave_status && redis.rdb_last_bgsave_status !== 'ok' ? 'warning' : undefined}
          />
          <Metric label="Rad etilgan ulanish" value={num(redis.rejected_connections)} level={redis.rejected_connections ? 'warning' : undefined} />
        </MetricGrid>
      </Box>
      {keyspace.length > 0 && (
        <Stack direction="row" flexWrap="wrap" useFlexGap gap={0.75} sx={{ mt: 1.5 }}>
          {keyspace.map(([db, keys]) => (
            <Chip key={db} size="small" label={`${db}: ${num(keys)} kalit`} sx={{ bgcolor: 'm3.surfaceContainerHigh' }} />
          ))}
        </Stack>
      )}
    </SectionCard>
  )
}

const STREAM_LABEL: Record<string, string> = { events: 'Hodisalar', screenshots: 'Skrinshotlar' }

function StreamsCard({ streams, thresholds }: { streams: ApiRecord[]; thresholds: ApiRecord }) {
  const level = worst(...streams.map((item) => levelOf(thresholds, 'stream_lag', item.lag)))
  return (
    <SectionCard icon={StreamIcon} title="Ingest oqimlari" subtitle="Client → Redis (XADD) → Celery → PostgreSQL" level={level}>
      <Stack spacing={1.25}>
        {streams.map((stream) => (
          <Box key={stream.name} sx={{ p: 1.5, borderRadius: '14px', border: 1, borderColor: 'm3.outlineVariant' }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="body2" fontWeight={650}>
                {STREAM_LABEL[stream.name] || stream.name} <Typography component="span" variant="caption" color="text.secondary"><Mono>{stream.key}</Mono></Typography>
              </Typography>
              <Typography variant="caption" color="text.secondary">{num(stream.consumers)} o‘quvchi</Typography>
            </Stack>
            <MetricGrid min={100}>
              <Metric label="Kirish/s" value={num(stream.in_per_s, 1)} />
              <Metric label="Orqada (lag)" value={num(stream.lag)} level={levelOf(thresholds, 'stream_lag', stream.lag)} />
              <Metric label="Kutilmoqda" value={num(stream.pending)} tooltip="O'qilgan, lekin DB'ga hali yozilmagan (PEL)" />
              <Metric
                label="Yozilmagan"
                value={num(stream.dead)}
                level={stream.dead ? 'warning' : undefined}
                tooltip="Batch ham, qator-ma-qator ham yozib bo'lmagan yozuvlar — dalil yo'qolmagan, :dead oqimida"
              />
            </MetricGrid>
          </Box>
        ))}
      </Stack>
    </SectionCard>
  )
}

const HEALTH: Record<string, { level: Level; label: string }> = {
  ok: { level: 'ok', label: 'OK' },
  stale: { level: 'critical', label: 'Kechikkan' },
  failed: { level: 'warning', label: 'Xato' },
  never: { level: 'unknown', label: 'Hali yo‘q' },
}

function CeleryCard({ celery, thresholds }: { celery: ApiRecord; thresholds: ApiRecord }) {
  const theme = useTheme()
  const tasks: ApiRecord[] = celery.tasks || []
  const queues: ApiRecord[] = celery.queues || []
  const level = worst(
    ...tasks.map((task) => (task.health === 'stale' ? (task.queue === 'ingest' ? 'critical' : 'warning') : 'ok') as Level),
    ...queues.map((queue) => levelOf(thresholds, 'celery_queue', queue.length)),
  )
  return (
    <SectionCard icon={TaskIcon} title="Celery" subtitle="Navbatlar va davriy vazifalar oxirgi marta qachon bajarilgani" level={level}>
      {!celery.available && !queues.length ? null : (
        <Stack direction="row" flexWrap="wrap" useFlexGap gap={1} sx={{ mb: 1.5 }}>
          {queues.map((queue) => {
            const queueLevel = levelOf(thresholds, 'celery_queue', queue.length)
            return (
              <Chip
                key={queue.name}
                icon={<Box sx={{ pl: 1, display: 'flex' }}><Dot level={queueLevel} /></Box>}
                label={`${queue.name}: ${num(queue.length)}`}
                sx={{ bgcolor: 'm3.surfaceContainerHigh', fontWeight: 600 }}
              />
            )
          })}
        </Stack>
      )}
      {!celery.tracking && (
        <Box sx={{ mb: 1.5 }}>
          <Unavailable>
            Vazifalar hali kuzatilmagan: Celery ishchilari yangi kod bilan qayta ishga tushirilishi kerak
            (signal ishchida ulanadi).
          </Unavailable>
        </Box>
      )}
      <Box sx={{ overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
        <Table size="small" sx={{ minWidth: 560 }}>
          <TableHead>
            <TableRow>
              <TableCell>Vazifa</TableCell>
              <TableCell>Jadval</TableCell>
              <TableCell align="right">Oxirgi</TableCell>
              <TableCell align="right">Davomiyligi</TableCell>
              <TableCell align="right">Xato (24 s)</TableCell>
              <TableCell>Holat</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {tasks.map((task) => {
              const health = HEALTH[task.health] || HEALTH.never
              const taskLevel = task.health === 'stale' && task.queue !== 'ingest' ? 'warning' : health.level
              return (
                <TableRow key={task.name} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight={600} noWrap>{task.name}</Typography>
                    <Typography variant="caption" color="text.secondary"><Mono>{task.queue}</Mono></Typography>
                  </TableCell>
                  <TableCell><Typography variant="caption">{task.schedule}</Typography></TableCell>
                  <TableCell align="right">{task.last_run_age_s != null ? `${duration(task.last_run_age_s)} oldin` : '—'}</TableCell>
                  <TableCell align="right">{task.last_runtime_s != null ? ms(task.last_runtime_s * 1000) : '—'}</TableCell>
                  <TableCell align="right" sx={{ color: task.failures_24h ? levelColor(theme, 'warning') : 'text.disabled' }}>
                    {num(task.failures_24h)}
                  </TableCell>
                  <TableCell><LevelChip level={taskLevel} label={health.label} /></TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </Box>
    </SectionCard>
  )
}

export default function DataPanel({ status }: { status: ApiRecord }) {
  const thresholds = status.thresholds
  const errors = status.errors || {}
  return (
    <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
      <Grid item xs={12} xl={6}>
        <PostgresCard pg={status.postgres} thresholds={thresholds} error={errors.postgres} />
      </Grid>
      <Grid item xs={12} xl={6}>
        <Stack spacing={{ xs: 1.5, sm: 2.5 }}>
          <RedisCard redis={status.redis} thresholds={thresholds} error={errors.redis} />
          <StreamsCard streams={status.streams?.streams || []} thresholds={thresholds} />
        </Stack>
      </Grid>
      <Grid item xs={12}>
        <CeleryCard celery={status.celery || {}} thresholds={thresholds} />
      </Grid>
    </Grid>
  )
}
