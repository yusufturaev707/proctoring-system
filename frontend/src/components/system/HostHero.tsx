import { useState } from 'react'
import { alpha, useTheme } from '@mui/material/styles'
import { Box, Button, Chip, Collapse, Stack, Tooltip, Typography } from '@mui/material'
import OkIcon from '@mui/icons-material/CheckCircleRounded'
import WarnIcon from '@mui/icons-material/WarningRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import DnsIcon from '@mui/icons-material/DnsOutlined'
import CloudIcon from '@mui/icons-material/CloudOutlined'
import TimerIcon from '@mui/icons-material/TimerOutlined'
import ClockIcon from '@mui/icons-material/ScheduleOutlined'
import MemoryIcon from '@mui/icons-material/MemoryOutlined'
import ExpandIcon from '@mui/icons-material/ExpandMoreRounded'
import ArrowIcon from '@mui/icons-material/ArrowForwardRounded'

import { bytes, duration, VIRT_LABEL } from './format'
import type { Level } from './format'
import { levelColor } from './parts'
import type { ApiRecord } from '../../types/api'

const HEADLINE: Record<string, string> = {
  ok: 'Hammasi joyida',
  warning: 'E’tibor talab qiladi',
  critical: 'Kritik muammo bor',
}

/** Muammo bo'limi -> sahifa yorlig'i (bosilganda o'sha yorliqqa o'tadi). */
export const SECTION_TAB: Record<string, string> = {
  cpu: 'overview', memory: 'overview', pressure: 'overview', limits: 'network', history: 'overview',
  process: 'overview', disks: 'disks', network: 'network', sockets: 'network', services: 'services',
  host: 'services', postgres: 'data', redis: 'data', streams: 'data', celery: 'data',
  celery_queues: 'data', celery_tasks: 'data', requests: 'requests', nginx: 'network',
}

const VISIBLE = 4

interface HostHeroProps {
  status: ApiRecord
  onOpenTab: (tab: string) => void
}

/**
 * Sahifa tepasi: umumiy holat (bir qarashda javob) va muammolar.
 *
 * Har muammoda ikki qator — "nima bo'ldi" va "nima qilish kerak" (client
 * `Notice` bilan bir xil qoida): administrator imtihon kuni hujjat
 * qidirmasligi kerak.
 */
export default function HostHero({ status, onOpenTab }: HostHeroProps) {
  const theme = useTheme()
  const [expanded, setExpanded] = useState(false)
  const overall: Level = status.overall || 'unknown'
  const problems: ApiRecord[] = status.problems || []
  const host = status.host || {}
  const virt = host.virtualization || {}
  const timeSync = host.time_sync || {}
  const tone = overall === 'ok' ? theme.palette.success.main : levelColor(theme, overall)
  const Icon = overall === 'critical' ? ErrorIcon : overall === 'warning' ? WarnIcon : OkIcon
  const critical = problems.filter((item) => item.severity === 'critical').length
  const warnings = problems.length - critical

  const chips = [
    { icon: DnsIcon, label: host.hostname, tip: host.os },
    virt.type && { icon: CloudIcon, label: VIRT_LABEL[virt.type] || virt.type, tip: [virt.vendor, virt.product].filter(Boolean).join(' · ') },
    { icon: MemoryIcon, label: `${host.cpu_logical || '—'} vCPU · ${bytes(status.memory?.total, 0)}`, tip: host.cpu_model },
    { icon: TimerIcon, label: `Ishlayapti: ${duration(host.uptime_s)}`, tip: `Yadro: ${host.kernel || '—'}` },
    timeSync.available && {
      icon: ClockIcon,
      label: timeSync.synced ? 'Soat sinxron' : 'Soat sinxron EMAS',
      tip: timeSync.timezone,
      warn: timeSync.synced === false,
    },
  ].filter(Boolean) as { icon: typeof DnsIcon; label: string; tip?: string; warn?: boolean }[]

  return (
    <Box
      sx={{
        borderRadius: '28px', p: { xs: 2, sm: 3 }, mb: 2.5,
        bgcolor: alpha(tone, theme.palette.mode === 'dark' ? 0.16 : 0.1),
        border: `1px solid ${alpha(tone, 0.28)}`,
      }}
    >
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={{ xs: 2, md: 3 }} alignItems={{ md: 'center' }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
          <Box
            sx={{
              width: 56, height: 56, borderRadius: '18px', display: 'grid', placeItems: 'center',
              bgcolor: tone, color: theme.palette.getContrastText(tone), flexShrink: 0,
            }}
          >
            <Icon sx={{ fontSize: 32 }} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h5" fontWeight={700} sx={{ letterSpacing: '-0.01em' }}>
              {HEADLINE[overall] || 'Holat aniqlanmoqda'}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {problems.length === 0
                ? 'Barcha ko‘rsatkichlar SLO chegarasida'
                : [critical && `${critical} ta kritik`, warnings && `${warnings} ta ogohlantirish`].filter(Boolean).join(' · ')}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" flexWrap="wrap" useFlexGap gap={1} sx={{ justifyContent: { md: 'flex-end' } }}>
          {chips.map(({ icon: ChipIcon, label, tip, warn }) => (
            <Tooltip key={label} title={tip || ''}>
              <Chip
                icon={<ChipIcon />}
                label={label}
                sx={{
                  bgcolor: warn ? alpha(theme.palette.warning.main, 0.18) : 'm3.surfaceContainerLowest',
                  border: `1px solid ${theme.palette.m3.outlineVariant}`,
                  fontWeight: 600,
                }}
              />
            </Tooltip>
          ))}
        </Stack>
      </Stack>

      {problems.length > 0 && (
        <Box sx={{ mt: 2.5 }}>
          <Stack spacing={1}>
            {problems.slice(0, VISIBLE).map((item) => (
              <ProblemRow key={`${item.code}-${item.title}`} item={item} onOpenTab={onOpenTab} />
            ))}
          </Stack>
          {problems.length > VISIBLE && (
            <>
              <Collapse in={expanded} unmountOnExit>
                <Stack spacing={1} sx={{ mt: 1 }}>
                  {problems.slice(VISIBLE).map((item) => (
                    <ProblemRow key={`${item.code}-${item.title}`} item={item} onOpenTab={onOpenTab} />
                  ))}
                </Stack>
              </Collapse>
              <Button
                size="small"
                onClick={() => setExpanded((value) => !value)}
                endIcon={<ExpandIcon sx={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: '200ms' }} />}
                sx={{ mt: 1 }}
              >
                {expanded ? 'Yig‘ish' : `Yana ${problems.length - VISIBLE} ta`}
              </Button>
            </>
          )}
        </Box>
      )}
    </Box>
  )
}

function ProblemRow({ item, onOpenTab }: { item: ApiRecord; onOpenTab: (tab: string) => void }) {
  const theme = useTheme()
  const color = item.severity === 'critical' ? theme.palette.error.main : theme.palette.warning.main
  const Icon = item.severity === 'critical' ? ErrorIcon : WarnIcon
  const tab = SECTION_TAB[item.section]
  return (
    <Stack
      direction="row"
      spacing={1.5}
      alignItems="flex-start"
      sx={{
        p: 1.5, pr: 1, borderRadius: '16px', bgcolor: 'm3.surfaceContainerLowest',
        borderLeft: `4px solid ${color}`,
      }}
    >
      <Icon sx={{ color, mt: 0.25, fontSize: 22 }} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="body2" fontWeight={650}>{item.title}</Typography>
        {item.hint && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
            {item.hint}
          </Typography>
        )}
      </Box>
      {tab && (
        <Tooltip title="Batafsil">
          <Button
            size="small"
            onClick={() => onOpenTab(tab)}
            sx={{ minWidth: 0, px: 1, color: 'text.secondary', flexShrink: 0 }}
            aria-label="Batafsil"
          >
            <ArrowIcon fontSize="small" />
          </Button>
        </Tooltip>
      )}
    </Stack>
  )
}
