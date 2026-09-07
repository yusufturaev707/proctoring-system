import { Chip, LinearProgress, Stack, Tooltip, Typography } from '@mui/material'
import CircleIcon from '@mui/icons-material/Circle'
import {
  SEVERITY_COLOR, SEVERITY_LABEL, STATUS_COLOR, STATUS_LABEL, riskColor,
} from '../theme'

export function StatusChip({ status, label }) {
  return (
    <Chip
      size="small"
      color={STATUS_COLOR[status] || 'default'}
      variant={status === 'in_progress' ? 'filled' : 'outlined'}
      label={label || STATUS_LABEL[status] || status}
    />
  )
}

export function SeverityChip({ severity, label }) {
  return (
    <Chip
      size="small"
      color={SEVERITY_COLOR[severity] || 'default'}
      variant={severity >= 3 ? 'filled' : 'outlined'}
      label={label || SEVERITY_LABEL[severity] || severity}
    />
  )
}

/** Xavf ballini rangli progress sifatida ko'rsatadi (0–100). */
export function RiskBar({ value = 0, width = 90 }) {
  const color = riskColor(value)
  return (
    <Tooltip title={`Xavf ballari: ${value}/100`}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ width }}>
        <LinearProgress
          variant="determinate"
          value={Math.min(100, value)}
          color={color}
          sx={{ flex: 1, height: 6, borderRadius: 3 }}
        />
        <Typography variant="caption" sx={{ fontWeight: 700, minWidth: 22 }} color={`${color}.main`}>
          {value}
        </Typography>
      </Stack>
    </Tooltip>
  )
}

export function OnlineDot({ online, labelOnline = 'Onlayn', labelOffline = 'Aloqa yo‘q' }) {
  return (
    <Tooltip title={online ? labelOnline : labelOffline}>
      <CircleIcon
        sx={{ fontSize: 11 }}
        color={online ? 'success' : 'disabled'}
      />
    </Tooltip>
  )
}
