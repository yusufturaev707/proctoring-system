import { memo } from 'react'
import type { ComponentType, ReactNode } from 'react'
import { alpha, useTheme } from '@mui/material/styles'
import type { Theme } from '@mui/material/styles'
import type { SvgIconProps } from '@mui/material'
import { Box, Card, Chip, LinearProgress, Stack, Tooltip, Typography } from '@mui/material'

import { LEVEL_COLOR, LEVEL_LABEL } from './format'
import type { Level } from './format'

/**
 * Server holati sahifasining MD3 bo'laklari.
 *
 * Rang faqat HOLATNI bildiradi (normal / ogohlantirish / kritik) —
 * bezak uchun rang ishlatilmaydi, aks holda qizil "disk 91%" boshqa
 * rangli kartalar orasida yo'qolib ketardi. Neytral narsa — `m3` sirt
 * rollarida.
 */

export function levelColor(theme: Theme, level: Level): string {
  return level === 'unknown' ? theme.palette.text.disabled : theme.palette[LEVEL_COLOR[level]].main
}

/** Bo'lim kartasi: tonal ikonka, sarlavha, izoh, o'ng tomonda amal. */
export interface SectionCardProps {
  icon: ComponentType<SvgIconProps>
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  level?: Level
  children: ReactNode
  dense?: boolean
}

export function SectionCard({ icon: Icon, title, subtitle, action, level, children, dense }: SectionCardProps) {
  const theme = useTheme()
  const tone = level && level !== 'ok' && level !== 'unknown' ? levelColor(theme, level) : null
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', ...(tone && { borderColor: alpha(tone, 0.5) }) }}>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ px: { xs: 2, sm: 2.5 }, pt: 2.25, pb: 1.25 }}>
        <Box
          sx={{
            width: 40, height: 40, borderRadius: '12px', flexShrink: 0,
            display: 'grid', placeItems: 'center',
            bgcolor: tone ? alpha(tone, 0.14) : 'm3.secondaryContainer',
            color: tone || 'm3.onSecondaryContainer',
          }}
        >
          <Icon sx={{ fontSize: 22 }} />
        </Box>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography variant="subtitle1" fontWeight={650} noWrap>{title}</Typography>
          {subtitle && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }} noWrap>
              {subtitle}
            </Typography>
          )}
        </Box>
        {action}
      </Stack>
      <Box sx={{ px: { xs: 2, sm: 2.5 }, pb: dense ? 1.5 : 2.5, flex: 1, minWidth: 0 }}>{children}</Box>
    </Card>
  )
}

/** Doiraviy ko'rsatkich (MD3 circular indicator, ichida qiymat). */
export interface RingProps {
  value: number | null | undefined
  level: Level
  size?: number
  thickness?: number
  label: ReactNode
  caption?: ReactNode
}

export const Ring = memo(function Ring({ value, level, size = 132, thickness = 12, label, caption }: RingProps) {
  const theme = useTheme()
  const radius = (size - thickness) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = value == null ? 0 : Math.max(0, Math.min(100, value))
  const color = level === 'unknown' ? theme.palette.primary.main : levelColor(theme, level)
  return (
    <Box sx={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={String(label)}>
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none"
          stroke={theme.palette.m3.surfaceContainerHighest} strokeWidth={thickness}
        />
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none"
          stroke={color} strokeWidth={thickness} strokeLinecap="round"
          strokeDasharray={`${(clamped / 100) * circumference} ${circumference}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: `stroke-dasharray ${theme.motion.slow}ms ${theme.motion.easing}, stroke 200ms` }}
        />
      </svg>
      <Stack
        alignItems="center" justifyContent="center"
        sx={{ position: 'absolute', inset: 0, textAlign: 'center', px: 1 }}
      >
        <Typography sx={{ fontSize: size * 0.2, fontWeight: 700, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>
          {label}
        </Typography>
        {caption && (
          <Typography variant="caption" color="text.secondary" noWrap sx={{ lineHeight: 1.2, mt: 0.25, maxWidth: '100%' }}>
            {caption}
          </Typography>
        )}
      </Stack>
    </Box>
  )
})

/** Chiziqli o'lchagich: 0..100, rang darajadan. */
export function Meter({ value, level, height = 8 }: { value: number | null | undefined; level: Level; height?: number }) {
  const theme = useTheme()
  return (
    <LinearProgress
      variant="determinate"
      value={value == null ? 0 : Math.max(0, Math.min(100, value))}
      sx={{
        height, bgcolor: 'm3.surfaceContainerHighest',
        '& .MuiLinearProgress-bar': { bgcolor: level === 'unknown' ? 'primary.main' : levelColor(theme, level) },
      }}
    />
  )
}

export function LevelChip({ level, label }: { level: Level; label?: ReactNode }) {
  const theme = useTheme()
  const color = levelColor(theme, level)
  return (
    <Chip
      size="small"
      label={label ?? LEVEL_LABEL[level]}
      sx={{ bgcolor: alpha(color, 0.14), color, fontWeight: 650, height: 24 }}
    />
  )
}

/** Holat nuqtasi (jadval qatorlarida). */
export function Dot({ level, pulse }: { level: Level; pulse?: boolean }) {
  const theme = useTheme()
  const color = levelColor(theme, level)
  return (
    <Box
      component="span"
      sx={{
        width: 10, height: 10, borderRadius: '50%', bgcolor: color, flexShrink: 0, display: 'inline-block',
        boxShadow: `0 0 0 3px ${alpha(color, 0.2)}`,
        ...(pulse && {
          '@keyframes sysPulse': { '0%': { boxShadow: `0 0 0 0 ${alpha(color, 0.5)}` }, '100%': { boxShadow: `0 0 0 8px ${alpha(color, 0)}` } },
          animation: 'sysPulse 1.6s ease-out infinite',
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }),
      }}
    />
  )
}

/** Kichik ko'rsatkich: yorliq, qiymat, ixtiyoriy izoh va daraja. */
export interface MetricProps {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  level?: Level
  tooltip?: ReactNode
}

export function Metric({ label, value, hint, level, tooltip }: MetricProps) {
  const theme = useTheme()
  const tone = level && level !== 'ok' && level !== 'unknown' ? levelColor(theme, level) : undefined
  const body = (
    <Box
      sx={{
        p: 1.5, borderRadius: '12px', bgcolor: tone ? alpha(tone, 0.1) : 'm3.surfaceContainerLow',
        minWidth: 0, height: '100%',
      }}
    >
      <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block', fontWeight: 600 }}>
        {label}
      </Typography>
      <Typography
        variant="subtitle1"
        noWrap
        sx={{ fontWeight: 700, color: tone, fontVariantNumeric: 'tabular-nums', lineHeight: 1.35 }}
      >
        {value}
      </Typography>
      {hint && (
        <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
          {hint}
        </Typography>
      )}
    </Box>
  )
  return tooltip ? <Tooltip title={tooltip}>{body}</Tooltip> : body
}

export function MetricGrid({ children, min = 140 }: { children: ReactNode; min?: number }) {
  return (
    <Box sx={{ display: 'grid', gap: 1, gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))` }}>
      {children}
    </Box>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return (
    <Box component="span" sx={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: '0.82em' }}>
      {children}
    </Box>
  )
}

/** Bo'lim mavjud emas (dev'da systemd yo'q, nginx sozlanmagan va h.k.). */
export function Unavailable({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ p: 2, borderRadius: '12px', bgcolor: 'm3.surfaceContainerLow' }}>
      <Typography variant="body2" color="text.secondary">{children}</Typography>
    </Box>
  )
}
