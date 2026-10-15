import { memo } from 'react'
import type { ReactNode } from 'react'
import { alpha, useTheme } from '@mui/material/styles'
import { Box, Card, Grid, Stack, Tooltip, Typography } from '@mui/material'

import { bytes, byteRate, levelOf, num, pct, worst } from './format'
import type { Level } from './format'
import { levelColor, Ring } from './parts'
import type { ApiRecord } from '../../types/api'

interface GaugeCardProps {
  title: string
  value: number | null | undefined
  level: Level
  label: string
  caption?: string
  children?: ReactNode
}

function GaugeCard({ title, value, level, label, caption, children }: GaugeCardProps) {
  // Halqa va sarlavha bir qatorda, tafsilot ostida TO'LIQ kenglikda: 4 ustunli
  // tartibda (1440–1600 px) halqa yonidagi ustunga ~120 px qolardi va
  // "Disk kutish (iowait)" kabi yorliqlar kesilardi.
  return (
    <Card sx={{ height: '100%', p: { xs: 2, sm: 2.5 } }}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Ring value={value} level={level} label={label} size={96} thickness={10} />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={650} noWrap>{title}</Typography>
          {caption && <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>{caption}</Typography>}
        </Box>
      </Stack>
      <Stack spacing={0.75} sx={{ mt: 2 }}>{children}</Stack>
    </Card>
  )
}

function Row({ label, value, level }: { label: string; value: ReactNode; level?: Level }) {
  const theme = useTheme()
  const color = level && level !== 'ok' && level !== 'unknown' ? levelColor(theme, level) : undefined
  return (
    <Stack direction="row" justifyContent="space-between" spacing={1}>
      <Typography variant="caption" color="text.secondary" noWrap>{label}</Typography>
      <Typography variant="caption" fontWeight={700} noWrap sx={{ color, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </Typography>
    </Stack>
  )
}

/**
 * Har yadro alohida ustun: umumiy CPU 30% bo'lsa ham bitta yadro 100%
 * bo'lishi mumkin (GIL'li jarayon) — o'rtacha buni yashiradi.
 */
const CoreStrip = memo(function CoreStrip({ cores, thresholds }: { cores: number[]; thresholds: ApiRecord }) {
  const theme = useTheme()
  if (!cores.length) return null
  return (
    <Tooltip title={`Yadrolar: ${cores.map((value) => `${Math.round(value)}%`).join(' · ')}`}>
      <Stack direction="row" spacing="2px" alignItems="flex-end" sx={{ height: 28, mt: 0.5 }}>
        {cores.map((value, index) => {
          const level = levelOf(thresholds, 'cpu_pct', value)
          return (
            <Box
              // eslint-disable-next-line react/no-array-index-key
              key={index}
              sx={{
                flex: 1, height: '100%', borderRadius: '3px', position: 'relative', overflow: 'hidden',
                bgcolor: 'm3.surfaceContainerHighest',
              }}
            >
              <Box
                sx={{
                  position: 'absolute', bottom: 0, left: 0, right: 0, height: `${Math.max(4, value)}%`,
                  bgcolor: level === 'ok' ? alpha(theme.palette.primary.main, 0.75) : levelColor(theme, level),
                  transition: `height ${theme.motion.base}ms ${theme.motion.easing}`,
                }}
              />
            </Box>
          )
        })}
      </Stack>
    </Tooltip>
  )
})

export default function ResourceGauges({ status }: { status: ApiRecord }) {
  const t = status.thresholds
  const cpu = status.cpu || {}
  const breakdown = cpu.breakdown || {}
  const memory = status.memory || {}
  const pressure = status.pressure || {}
  const cores = cpu.cores || []
  const coreCount = status.host?.cpu_logical || cores.length || 1
  const load: number[] = cpu.load || []
  const mounts: ApiRecord[] = status.disks?.mounts || []
  const disk = mounts.reduce<ApiRecord | null>((acc, item) => (!acc || item.percent > acc.percent ? item : acc), null)
  const screenshotDisk = mounts.find((item) => (item.contains || []).includes('screenshots'))
  const io: ApiRecord[] = status.disks?.io || []
  const busiest = io.reduce<ApiRecord | null>((acc, item) => (!acc || (item.util_pct || 0) > (acc.util_pct || 0) ? item : acc), null)

  const cpuLevel = worst(levelOf(t, 'cpu_pct', cpu.percent), levelOf(t, 'steal_pct', breakdown.steal))
  const memLevel = worst(levelOf(t, 'memory_pct', memory.percent), memory.swap_in_bps > 0 ? 'critical' : 'ok')
  const loadLevel = levelOf(t, 'load_per_core', cpu.load_per_core)
  const diskLevel = disk ? worst(levelOf(t, 'disk_pct', disk.percent), levelOf(t, 'disk_days_left', disk.days_left)) : 'unknown'
  const psi = (name: string) => pressure?.[name]?.some?.avg60

  return (
    <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
      <Grid item xs={12} sm={6} lg={3}>
        <GaugeCard title="Protsessor" value={cpu.percent} level={cpuLevel} label={pct(cpu.percent, 0)} caption={`${coreCount} vCPU`}>
          <Row label="Foydalanuvchi" value={pct(breakdown.user)} />
          <Row label="Tizim" value={pct(breakdown.system)} />
          <Row label="Disk kutish (iowait)" value={pct(breakdown.iowait)} level={levelOf(t, 'iowait_pct', breakdown.iowait)} />
          <Tooltip title="ESXi: VM fizik yadroni kutgan vaqt. Bu VM ichidan emas, xostdan tuzatiladi.">
            <Box><Row label="Steal (ESXi)" value={pct(breakdown.steal)} level={levelOf(t, 'steal_pct', breakdown.steal)} /></Box>
          </Tooltip>
          <CoreStrip cores={cores} thresholds={t} />
        </GaugeCard>
      </Grid>
      <Grid item xs={12} sm={6} lg={3}>
        <GaugeCard title="Xotira" value={memory.percent} level={memLevel} label={pct(memory.percent, 0)} caption={bytes(memory.total, 0)}>
          <Row label="Ishlatilgan" value={bytes(memory.used)} />
          <Row label="Mavjud" value={bytes(memory.available)} />
          <Row label="Kesh (bo‘shatiladi)" value={bytes(memory.cached)} />
          <Row
            label="Swap"
            value={memory.swap_total ? `${bytes(memory.swap_used)} / ${bytes(memory.swap_total, 0)}` : 'yo‘q'}
            level={levelOf(t, 'swap_used_pct', memory.swap_percent)}
          />
          {memory.swap_in_bps > 0 && <Row label="Swap’dan o‘qish" value={byteRate(memory.swap_in_bps)} level="critical" />}
        </GaugeCard>
      </Grid>
      <Grid item xs={12} sm={6} lg={3}>
        <GaugeCard
          title="Yuklama"
          value={Math.min(100, (cpu.load_per_core || 0) * 50)}
          level={loadLevel}
          label={load[0] != null ? num(load[0], 2) : '—'}
          caption={`load average · yadroga ${num(cpu.load_per_core, 2)}`}
        >
          <Row label="1 / 5 / 15 daqiqa" value={load.length ? load.map((value) => num(value, 2)).join(' / ') : '—'} />
          {psi('cpu') != null && <Row label="CPU kutish (PSI)" value={pct(psi('cpu'))} level={levelOf(t, 'pressure_some_pct', psi('cpu'))} />}
          {psi('io') != null && <Row label="Disk kutish (PSI)" value={pct(psi('io'))} level={levelOf(t, 'pressure_some_pct', psi('io'))} />}
          {psi('memory') != null && <Row label="Xotira kutish (PSI)" value={pct(psi('memory'))} level={levelOf(t, 'pressure_some_pct', psi('memory'))} />}
          <Typography variant="caption" color="text.disabled">
            Yadroga 1.0 dan ko‘pi — navbat
          </Typography>
        </GaugeCard>
      </Grid>
      <Grid item xs={12} sm={6} lg={3}>
        <GaugeCard
          title="Disk"
          value={disk?.percent}
          level={diskLevel}
          label={pct(disk?.percent, 0)}
          caption={disk?.mount || '—'}
        >
          <Row label="Bo‘sh" value={bytes(disk?.free)} />
          {screenshotDisk && screenshotDisk !== disk && (
            <Row label={`Skrinshotlar (${screenshotDisk.mount})`} value={pct(screenshotDisk.percent, 0)} level={levelOf(t, 'disk_pct', screenshotDisk.percent)} />
          )}
          <Row
            label="To‘lishiga"
            value={disk?.days_left != null ? `~${disk.days_left} kun` : 'hisoblanmoqda'}
            level={levelOf(t, 'disk_days_left', disk?.days_left)}
          />
          <Row
            label={`Bandligi${busiest ? ` (${busiest.device})` : ''}`}
            value={pct(busiest?.util_pct)}
            level={levelOf(t, 'disk_util_pct', busiest?.util_pct)}
          />
        </GaugeCard>
      </Grid>
    </Grid>
  )
}
