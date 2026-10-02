import {
  Box, Button, Chip, Drawer, IconButton, Stack, Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import CheckIcon from '@mui/icons-material/CheckCircleOutline'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import LockOpenIcon from '@mui/icons-material/LockOpenOutlined'
import LinkIcon from '@mui/icons-material/LinkOutlined'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'

import { dateText, Field, HeaderIcon, Section, useCopy } from '../data/DetailFields'
import { AI_PROFILE_LABEL, computerLabel, DEVICE_STATUS_LABEL } from '../../utils/labels'

const STATUS_COLOR = { active: 'success', revoked: 'error', pending: 'warning' }

/**
 * Qurilmaning TO'LIQ kartasi — MD3 yon varaq (side sheet).
 *
 * Jadvalda faqat qaror uchun kerak ustunlar qoladi (holat, kompyuter,
 * viloyat, faollik); qurilma ID, versiya, GPU, blok sababi va uchala
 * manzil shu yerda. Ilgari ular ustun edi va jadval ekranga sig'masdan
 * gorizontal surilardi — kerakli amal tugmalari o'ng chetda ko'rinmay
 * qolardi. Amallar ham shu yerda: qurilmani ko'rib turib qaror qilinadi.
 */
export default function DeviceDetailSheet({
  device, canManage, onClose, onApprove, onRevoke, onUnblock, onRebind,
}) {
  const open = Boolean(device)
  const copy = useCopy()

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      slotProps={{
        paper: {
          sx: {
            width: { xs: '100%', sm: 440 },
            bgcolor: 'm3.surfaceContainerLow',
            borderTopLeftRadius: { sm: 28 },
            borderBottomLeftRadius: { sm: 28 },
          },
        },
      }}
    >
      {device && (
        <Stack sx={{ height: '100%' }}>
          {/* Sarlavha: kompyuter nomi — operator mashinani shu bilan taniydi. */}
          <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ px: 3, pt: 3, pb: 2 }}>
            <HeaderIcon><ComputerIcon /></HeaderIcon>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h6" noWrap sx={{ lineHeight: 1.3 }}>
                {computerLabel(device.computer_number, device.computer_code) || 'Kompyuter biriktirilmagan'}
              </Typography>
              <Typography variant="body2" color="text.secondary" noWrap>
                {[device.region_name, device.zone_name].filter(Boolean).join(' · ') || '—'}
              </Typography>
              <Stack direction="row" spacing={0.75} sx={{ mt: 1 }}>
                <Chip
                  size="small"
                  color={STATUS_COLOR[device.status] || 'default'}
                  variant={device.status === 'pending' ? 'filled' : 'outlined'}
                  label={DEVICE_STATUS_LABEL[device.status] || device.status}
                />
                <Chip
                  size="small"
                  variant={device.is_online ? 'filled' : 'outlined'}
                  color={device.is_online ? (device.online_state === 'exam' ? 'info' : 'success') : 'default'}
                  label={device.is_online ? (device.online_state === 'exam' ? 'Imtihonda' : 'Online') : 'Offline'}
                />
              </Stack>
            </Box>
            <IconButton onClick={onClose} aria-label="Yopish" sx={{ mt: -0.5, mr: -1 }}>
              <CloseIcon />
            </IconButton>
          </Stack>

          <Box sx={{ flex: 1, overflowY: 'auto', px: 2, pb: 2 }}>
            {device.status === 'revoked' && (
              <Section title="Blok">
                <Field label="Sabab" value={device.revoke_reason} wrap />
                <Field label="Bloklangan" value={dateText(device.revoked_at)} />
              </Section>
            )}

            <Section title="Client">
              <Field label="Qurilma ID" value={device.device_id} mono onCopy={copy} />
              <Field label="Versiya" value={device.app_version} />
              <Field label="Kirgan xodim" value={device.online_staff} />
              <Field label="Oxirgi faollik" value={dateText(device.last_used_at)} />
              <Field label="Ro‘yxatdan o‘tgan" value={dateText(device.created_at)} />
              <Field label="Dastur xeshi" value={device.app_hash} mono onCopy={copy} />
            </Section>

            {/* MASHINA: client aytgan UUID va kompyuter yozuvidagisi yonma-yon -
                nomuvofiqlikda administrator to'g'ri qiymatni shu yerdan oladi. */}
            <Section title="Mashina">
              <Field
                label="Machine UUID (client o‘lchagan)"
                value={device.reported_machine_uuid}
                hint="Client hali yubormagan (eski nusxa)"
                mono
                onCopy={copy}
              />
              <Field
                label="Kompyuter yozuvidagi UUID"
                value={device.computer_machine_uuid}
                hint="Yozilmagan — birinchi ulanishda MAC orqali bog‘lanadi"
                mono
                onCopy={copy}
                warn={Boolean(
                  device.reported_machine_uuid && device.computer_machine_uuid &&
                  device.reported_machine_uuid !== device.computer_machine_uuid,
                )}
              />
              {/* MAC - juftlikning ikkinchi yarmi: farq bo'lsa handshake `not_found`
                  beradi. Administrator sababni shu yerda (va `audit_machine_identity`
                  da) ko'radi. */}
              <Field
                label="Mashina aytgan MAC"
                value={device.reported_mac}
                hint="Client hali yubormagan"
                mono
                onCopy={copy}
              />
              <Field
                label="Kompyuter yozuvidagi MAC"
                value={device.computer_mac_address}
                hint="Yozilmagan — administrator MAC kiritishi kerak"
                mono
                onCopy={copy}
                warn={Boolean(
                  device.reported_mac && device.computer_mac_address &&
                  normalizeMac(device.reported_mac) !== normalizeMac(device.computer_mac_address),
                )}
              />
            </Section>

            <Section title="Apparat">
              <Field
                label="Apparat profili"
                value={AI_PROFILE_LABEL[device.performance_profile] || device.performance_profile}
              />
              <Field label="GPU" value={device.gpu_name} hint="Bo‘sh — karta yoki drayver yo‘q" />
              <Field label="Fingerprint" value={device.hardware_fingerprint} mono onCopy={copy} />
            </Section>

            {/* UCHTA MANZIL, UCHTA MA'NO (`CLAUDE.md`). */}
            <Section title="Tarmoq">
              <Field label="Mashina IP" value={device.reported_lan_ip} hint="Client aytgan LAN manzil" />
              <Field label="Manba IP" value={device.last_ip} hint="Server ko‘rgan manzil" />
              <Field label="Tashqi IP" value={device.reported_public_ip} hint="Client aniqlagan, ma’lumot uchun" />
            </Section>
          </Box>

          {canManage && (
            <Stack
              direction="row"
              spacing={1}
              sx={{ px: 3, py: 2, borderTop: 1, borderColor: 'divider', bgcolor: 'm3.surfaceContainer' }}
            >
              {device.status === 'pending' && (
                <Button variant="contained" disableElevation startIcon={<CheckIcon />} onClick={() => onApprove(device)} sx={{ borderRadius: 999, flex: 1 }}>
                  Tasdiqlash
                </Button>
              )}
              {device.status === 'active' && (
                <Button variant="outlined" color="error" startIcon={<BlockIcon />} onClick={() => onRevoke(device)} sx={{ borderRadius: 999, flex: 1 }}>
                  Bloklash
                </Button>
              )}
              {device.status === 'revoked' && (
                <Button variant="contained" disableElevation startIcon={<LockOpenIcon />} onClick={() => onUnblock(device)} sx={{ borderRadius: 999, flex: 1 }}>
                  Blokdan chiqarish
                </Button>
              )}
              <Button variant="outlined" startIcon={<LinkIcon />} onClick={() => onRebind(device)} sx={{ borderRadius: 999, flex: 1 }}>
                Biriktirish
              </Button>
            </Stack>
          )}
        </Stack>
      )}
    </Drawer>
  )
}

// Server `normalize_mac` bilan bir xil: `2C-F0-...` va `2c:f0:...` farq emas.
const normalizeMac = (value) => String(value || '').trim().replace(/-/g, ':').toUpperCase()
