import { Box, Chip, Grid, Radio, Skeleton, Stack, Tooltip, Typography } from '@mui/material'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'

import { FULL_ACCESS, surfacesOf } from './permissionMeta'
import { SurfaceChips } from './UserBits'

/**
 * Rol tanlash — MD3 radio plitkalari (foydalanuvchi formasi).
 *
 * Ochiladigan ro'yxat faqat NOMNI ko'rsatardi, holbuki tanlov uchun
 * uchta savol muhim: rol qayerda ishlaydi (panel / client), qaysi
 * viloyatlarni ko'radi va qancha huquq beradi. Plitka uchalasini
 * yonma-yon ko'rsatadi.
 *
 * Bera olmaydigan rol (`blockedReason`) o'chiriladi va sababi aytiladi —
 * server baribir rad etadi (`UserWriteSerializer.validate`).
 */
export default function RolePicker({ roles, value, onChange, disabled, blockedReason, error }) {
  if (!roles) {
    return (
      <Grid container spacing={1.5}>
        {[0, 1, 2, 3].map((index) => (
          <Grid item xs={12} sm={6} key={index}>
            <Skeleton variant="rounded" height={92} sx={{ borderRadius: '16px' }} />
          </Grid>
        ))}
      </Grid>
    )
  }

  return (
    <Grid container spacing={1.5} role="radiogroup" aria-label="Rol">
      {roles.map((role) => {
        const selected = String(value) === String(role.id)
        const codes = (role.permissions || []).map((item) => item.code)
        const full = codes.includes(FULL_ACCESS)
        const reason = selected ? '' : blockedReason?.(role) || ''
        const locked = disabled || Boolean(reason)
        return (
          <Grid item xs={12} sm={6} key={role.id}>
            <Tooltip title={reason} placement="top">
              <Box
                component="label"
                sx={{
                  display: 'flex', gap: 1, height: '100%', p: 1.5, pr: 2,
                  borderRadius: '16px', cursor: locked ? 'default' : 'pointer',
                  border: selected ? 2 : 1,
                  borderColor: selected ? 'primary.main' : error ? 'error.main' : 'm3.outlineVariant',
                  bgcolor: selected ? 'm3.primaryContainer' : 'transparent',
                  opacity: locked && !selected ? 0.5 : 1,
                  transition: 'background-color 150ms, border-color 150ms',
                  '&:hover': locked || selected ? undefined : { bgcolor: 'action.hover' },
                }}
              >
                <Radio
                  checked={selected}
                  disabled={locked}
                  onChange={() => onChange(role.id)}
                  value={role.id}
                  sx={{ alignSelf: 'flex-start', mt: -0.5 }}
                  inputProps={{ 'aria-label': role.name }}
                />
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="subtitle2" noWrap sx={{ color: selected ? 'm3.onPrimaryContainer' : 'text.primary' }}>
                      {role.name}
                    </Typography>
                    {!role.is_active && <Chip size="small" label="Nofaol" color="error" variant="outlined" />}
                  </Stack>
                  {role.description && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{
                        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                        overflow: 'hidden', mt: 0.25,
                      }}
                    >
                      {role.description}
                    </Typography>
                  )}
                  <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                    <SurfaceChips {...surfacesOf(codes)} />
                    <Chip
                      size="small"
                      variant="outlined"
                      icon={role.is_global ? <PublicIcon /> : <PlaceIcon />}
                      label={role.is_global ? 'Respublika' : 'Viloyat'}
                    />
                    <Typography variant="caption" color="text.secondary">
                      {full ? 'to‘liq huquq' : `${codes.length} ruxsat`}
                    </Typography>
                  </Stack>
                </Box>
              </Box>
            </Tooltip>
          </Grid>
        )
      })}
    </Grid>
  )
}
