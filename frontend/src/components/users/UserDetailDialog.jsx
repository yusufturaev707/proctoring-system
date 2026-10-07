import { useQuery } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, Grid, IconButton, Skeleton,
  Stack, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'
import PersonIcon from '@mui/icons-material/PersonOutline'
import PhoneIcon from '@mui/icons-material/PhoneOutlined'
import TelegramIcon from '@mui/icons-material/Telegram'
import BadgeIcon from '@mui/icons-material/BadgeOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'
import WebIcon from '@mui/icons-material/WebOutlined'
import DesktopIcon from '@mui/icons-material/DesktopMacOutlined'
import LoginIcon from '@mui/icons-material/LoginOutlined'
import ShieldIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import CheckIcon from '@mui/icons-material/CheckCircleOutline'
import BlockIcon from '@mui/icons-material/RemoveCircleOutline'

import { auditLogs as auditApi, users as usersApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { AUDIT_ACTION_LABEL } from '../../utils/labels'
import { dateText, Field, Section, useCopy } from '../data/DetailFields'
import { FULL_ACCESS, groupPermissions } from './permissionMeta'
import { UserAvatar } from './UserBits'

/**
 * Xodimning TO'LIQ kartasi — jadval qatori bosilganda (MD3 dialog).
 *
 * Savollar tartibida: KIM (shaxsiy), NIMA QILA OLADI (rol, qamrov,
 * ruxsatlar), QAYERDA ISHLAYDI (panel / client, oxirgi kirish), NIMA
 * QILDI (audit — ruxsat bo'lsa). Ma'lumot `detail` bilan YANGIDAN
 * olinadi: ro'yxat qatorida ruxsatlar nomi va rol izohi yo'q.
 *
 * Muammolar karta TEPASIDA aytiladi (viloyat yo'q, rol yo'q/nofaol) —
 * "nega bu xodim hech narsa ko'rmayapti?" degan savolning javobi.
 */
export default function UserDetailDialog({ row, canManage, onEdit, onResetPassword, onClose }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const { can, user: me } = useAuth()
  const copy = useCopy()

  const { data: fresh, isLoading } = useQuery({
    queryKey: ['users', 'detail', row?.id],
    queryFn: () => usersApi.detail(row.id),
    enabled: Boolean(row?.id),
  })
  const canAudit = can('audit.view')
  const { data: auditPage, isLoading: auditLoading } = useQuery({
    queryKey: ['audit-logs', 'by-actor', row?.id],
    queryFn: () => auditApi.list({ actor: row.id, page_size: 6 }),
    enabled: Boolean(row?.id) && canAudit,
  })

  if (!row) return null
  const user = { ...row, ...(fresh || {}) }
  const role = user.role_detail
  const details = user.permission_details || []
  const codes = details.map((item) => item.code)
  const full = user.is_superuser || codes.includes(FULL_ACCESS)
  // Server hisoblaydi (`UserListSerializer.surfaces`) — superuser, nofaol
  // rol va `*` holatlari bitta qoida bilan; bu yerda takrorlanmaydi.
  const surfaces = {
    panel: (user.surfaces || []).includes('panel'),
    client: (user.surfaces || []).includes('client'),
  }
  const groups = groupPermissions(details)
  const audit = auditPage?.results || []
  const isSelf = me?.id === user.id

  const problems = []
  if (!user.is_superuser && !user.role) {
    problems.push({ severity: 'error', text: 'Rol biriktirilmagan — xodim tizimga (panel ham, client ham) kira olmaydi.' })
  } else if (role && !role.is_active) {
    problems.push({ severity: 'error', text: `«${role.name}» roli nofaol — xodim hech qanday huquqqa ega emas.` })
  }
  if (user.lacks_region) {
    problems.push({ severity: 'warning', text: 'Rol viloyat darajasida, lekin viloyat biriktirilmagan — panelda hech narsa ko‘rinmaydi.' })
  }
  if (!user.is_active) {
    problems.push({ severity: 'warning', text: 'Hisob bloklangan — kirish yopiq.' })
  }

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth="md"
      fullWidth
      fullScreen={fullScreen}
      slotProps={{ paper: { sx: { bgcolor: 'm3.surfaceContainerLow', borderRadius: fullScreen ? 0 : '28px' } } }}
    >
      {/* Sarlavha: avatar, F.I.Sh., login va asosiy holatlar. */}
      <Stack direction="row" spacing={2} alignItems="flex-start" sx={{ px: 3, pt: 3, pb: 2 }}>
        <UserAvatar user={user} size={56} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h6" noWrap sx={{ lineHeight: 1.3 }}>
            {user.full_name || user.username}
            {isSelf && (
              <Typography component="span" variant="body2" color="text.secondary"> · siz</Typography>
            )}
          </Typography>
          <Typography variant="body2" color="text.secondary" noWrap sx={{ fontFamily: 'monospace' }}>
            @{user.username}
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            <Chip
              size="small"
              color={user.is_active ? 'success' : 'error'}
              variant={user.is_active ? 'filled' : 'outlined'}
              label={user.is_active ? 'Faol' : 'Bloklangan'}
            />
            {user.is_superuser && <Chip size="small" color="warning" icon={<ShieldIcon />} label="Superuser" />}
            {user.role_name && <Chip size="small" variant="outlined" icon={<BadgeIcon />} label={user.role_name} />}
            {surfaces.panel && <Chip size="small" variant="outlined" color="primary" icon={<WebIcon />} label="Admin panel" />}
            {surfaces.client && <Chip size="small" variant="outlined" color="secondary" icon={<DesktopIcon />} label="Desktop client" />}
          </Stack>
        </Box>
        <IconButton onClick={onClose} aria-label="Yopish" sx={{ mt: -0.5, mr: -1 }}>
          <CloseIcon />
        </IconButton>
      </Stack>

      <DialogContent sx={{ pt: 0, px: { xs: 2, sm: 3 } }}>
        {problems.map((problem) => (
          <Alert key={problem.text} severity={problem.severity} sx={{ mb: 1.5, borderRadius: '16px' }}>
            {problem.text}
          </Alert>
        ))}

        <Grid container columnSpacing={2}>
          <Grid item xs={12} md={6}>
            <Section title="Shaxsiy ma’lumotlar">
              <Field icon={<PersonIcon fontSize="small" />} label="Familiya" value={user.last_name} hint="Kiritilmagan" />
              <Field label="Ism" value={user.first_name} hint="Kiritilmagan" />
              <Field label="Otasining ismi" value={user.middle_name} hint="Kiritilmagan" />
              <Field icon={<PhoneIcon fontSize="small" />} label="Telefon" value={user.phone} hint="Kiritilmagan" onCopy={copy} />
              <Field icon={<TelegramIcon fontSize="small" />} label="Telegram ID" value={user.telegram_id} hint="Bog‘lanmagan" mono onCopy={copy} />
            </Section>

            <Section title="Rol va hudud">
              <Field
                icon={<BadgeIcon fontSize="small" />}
                label="Rol"
                value={user.is_superuser ? 'Superuser — rol tekshirilmaydi' : role?.name}
                hint="Biriktirilmagan"
              />
              {role?.description && <Field label="Rol izohi" value={role.description} wrap />}
              <Field
                label="Ko‘rish doirasi"
                value={
                  user.is_superuser || role?.is_global
                    ? 'Butun respublika — barcha viloyatlar'
                    : 'Faqat o‘z viloyati'
                }
              />
              <Field
                icon={<PlaceIcon fontSize="small" />}
                label="Viloyat"
                value={user.region_name}
                hint={user.is_region_scoped || user.lacks_region ? 'Biriktirilmagan' : 'Barcha viloyatlar'}
                warn={Boolean(user.lacks_region)}
              />
              <Field label="Bino" value={user.zone_name} hint="Biriktirilmagan" />
            </Section>
          </Grid>

          <Grid item xs={12} md={6}>
            <Section title="Kirish">
              <AccessRow icon={<WebIcon fontSize="small" />} label="Admin panel" on={surfaces.panel}
                hint={surfaces.panel ? 'Panelga login qila oladi' : 'Panel yopiq — rolda «Admin panelga kirish» yo‘q'} />
              <AccessRow icon={<DesktopIcon fontSize="small" />} label="Desktop client" on={surfaces.client}
                hint={surfaces.client ? 'Imtihon markazida ishlay oladi' : 'Client’da ishlash ruxsati yo‘q'} />
              <Field icon={<LoginIcon fontSize="small" />} label="Oxirgi kirish" value={dateText(user.last_login_at)} hint="Hali kirmagan" />
              <Field label="Oxirgi kirish IP" value={user.last_login_ip} mono onCopy={copy} hint="—" />
              <Field label="Django admin (/admin/)" value={user.is_staff ? 'Ruxsat bor' : 'Yo‘q'} />
            </Section>

            <Section title="Hisob">
              <Field label="Yaratilgan" value={dateText(user.created_at)} />
              <Field label="Oxirgi o‘zgarish" value={dateText(user.updated_at)} hint={isLoading ? 'Yuklanmoqda…' : '—'} />
              <Field label="ID" value={user.id} mono />
            </Section>
          </Grid>
        </Grid>

        {/* Ruxsatlar — nom bilan, bo'lim bo'yicha (kodlar faqat tooltip'da). */}
        <Section title={full ? 'Ruxsatlar · to‘liq' : `Ruxsatlar · ${details.length}`}>
          <Box sx={{ p: 2 }}>
            {isLoading ? (
              <Skeleton height={64} />
            ) : full ? (
              <Stack direction="row" spacing={1.5} alignItems="center"
                sx={{ p: 1.5, borderRadius: '12px', bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer' }}>
                <ShieldIcon />
                <Typography variant="body2">
                  To‘liq huquq — barcha amallar, barcha bo‘limlar
                  {user.is_superuser ? ' (superuser hisobi)' : ''}.
                </Typography>
              </Stack>
            ) : groups.length ? (
              <Stack spacing={1.5}>
                {groups.map(({ group, meta, items }) => {
                  const Icon = meta.icon
                  return (
                    <Stack key={group} direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.75, sm: 1.5 }}>
                      <Stack direction="row" spacing={1} alignItems="center" sx={{ width: { sm: 170 }, flexShrink: 0 }}>
                        <Icon fontSize="small" sx={{ color: 'text.secondary' }} />
                        <Typography variant="body2" fontWeight={650}>{meta.label}</Typography>
                      </Stack>
                      <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ flex: 1 }}>
                        {items.map((item) => (
                          <Tooltip key={item.code} title={item.code}>
                            <Chip size="small" label={item.name} sx={{ bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer' }} />
                          </Tooltip>
                        ))}
                      </Stack>
                    </Stack>
                  )
                })}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.disabled">Ruxsat yo‘q</Typography>
            )}
          </Box>
        </Section>

        {canAudit && (
          <Section title="Oxirgi amallar">
            {auditLoading ? (
              <Box sx={{ p: 2 }}><Skeleton height={32} /></Box>
            ) : audit.length ? audit.map((entry) => (
              <Field
                key={entry.id}
                icon={<HistoryIcon fontSize="small" />}
                label={dateText(entry.created_at)}
                value={[
                  AUDIT_ACTION_LABEL[entry.action] || entry.action_display || entry.action,
                  entry.object_type && `${entry.object_type}${entry.object_id ? ` #${entry.object_id}` : ''}`,
                  entry.ip_address,
                ].filter(Boolean).join(' · ')}
              />
            )) : (
              <Field icon={<HistoryIcon fontSize="small" />} label="Audit jurnali" value="" hint="Bu xodim hali hech qanday amal bajarmagan" />
            )}
          </Section>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2, gap: 1, bgcolor: 'm3.surfaceContainer', flexWrap: 'wrap' }}>
        <Box sx={{ flex: 1 }} />
        {canManage && (
          <Button startIcon={<KeyIcon />} onClick={() => onResetPassword(user)}>
            Parolni tiklash
          </Button>
        )}
        <Button onClick={onClose}>Yopish</Button>
        {canManage && (
          <Button variant="contained" disableElevation startIcon={<EditIcon />} onClick={() => onEdit(user)}>
            Tahrirlash
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}

/** Kirish yuzasi qatori: bor/yo'q belgisi + sabab. */
function AccessRow({ icon, label, on, hint }) {
  return (
    <Field
      icon={icon}
      label={label}
      value={
        <Stack direction="row" spacing={0.75} alignItems="center">
          {on
            ? <CheckIcon fontSize="small" color="success" />
            : <BlockIcon fontSize="small" sx={{ color: 'text.disabled' }} />}
          <span>{hint}</span>
        </Stack>
      }
    />
  )
}
