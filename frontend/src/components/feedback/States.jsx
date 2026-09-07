import { alpha } from '@mui/material/styles'
import { Box, Button, Stack, Typography } from '@mui/material'
import InboxIcon from '@mui/icons-material/Inbox'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import LockIcon from '@mui/icons-material/LockOutlined'
import RefreshIcon from '@mui/icons-material/RefreshOutlined'

/**
 * Bo'sh / xato / ruxsatsiz holatlar.
 *
 * Har birida foydalanuvchi uchun KEYINGI QADAM bo'lishi kerak.
 * "Ma'lumot yo'q" degan quruq matn — tugallanmagan interfeys belgisi.
 */

function StateShell({ icon: Icon, tone = 'default', title, description, action, dense }) {
  return (
    <Stack
      alignItems="center"
      justifyContent="center"
      spacing={1.5}
      sx={{ py: dense ? 5 : 8, px: 3, textAlign: 'center' }}
    >
      <Box
        sx={{
          width: 60,
          height: 60,
          borderRadius: '50%',
          display: 'grid',
          placeItems: 'center',
          bgcolor: (theme) =>
            tone === 'default'
              ? alpha(theme.palette.text.secondary, 0.08)
              : alpha(theme.palette[tone].main, 0.12),
          color: tone === 'default' ? 'text.disabled' : `${tone}.main`,
        }}
      >
        <Icon sx={{ fontSize: 30 }} />
      </Box>
      <Typography variant="subtitle1" fontWeight={650}>{title}</Typography>
      {description && (
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 420 }}>
          {description}
        </Typography>
      )}
      {action && <Box sx={{ pt: 1 }}>{action}</Box>}
    </Stack>
  )
}

export function EmptyState({
  title = 'Ma’lumot topilmadi',
  description,
  actionLabel,
  onAction,
  icon = InboxIcon,
  dense,
}) {
  return (
    <StateShell
      icon={icon}
      title={title}
      description={description}
      dense={dense}
      action={
        actionLabel && onAction ? (
          <Button variant="outlined" onClick={onAction}>{actionLabel}</Button>
        ) : null
      }
    />
  )
}

export function ErrorState({ error, onRetry, dense }) {
  return (
    <StateShell
      icon={ErrorOutlineIcon}
      tone="error"
      title="Ma’lumotni yuklab bo‘lmadi"
      description={error?.userMessage || error?.message || 'Server bilan aloqa uzildi.'}
      dense={dense}
      action={
        onRetry ? (
          <Button variant="contained" startIcon={<RefreshIcon />} onClick={onRetry}>
            Qayta urinish
          </Button>
        ) : null
      }
    />
  )
}

export function ForbiddenState({ permission }) {
  return (
    <StateShell
      icon={LockIcon}
      tone="warning"
      title="Ruxsat yo‘q"
      description={
        permission
          ? `Ushbu bo‘lim uchun «${permission}» huquqi talab qilinadi. Administratorga murojaat qiling.`
          : 'Ushbu bo‘limga kirish huquqingiz yetarli emas.'
      }
    />
  )
}
