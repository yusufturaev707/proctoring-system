import { useMemo, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, Chip, Grid, InputAdornment, Skeleton, Stack, Switch,
  TextField, Tooltip, Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import ShieldIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import WebIcon from '@mui/icons-material/WebOutlined'
import DesktopIcon from '@mui/icons-material/DesktopMacOutlined'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'

import {
  CLIENT_OPERATE, FULL_ACCESS, PANEL_ACCESS, groupPermissions,
} from './permissionMeta'

/**
 * Rol ruxsatlari — MD3 matritsa (`Roles.jsx` formasining maxsus maydoni).
 *
 * Uch qavat, chunki ruxsatlar bir xil "og'irlikda" emas:
 *
 *   1. TO'LIQ HUQUQ (`*`) — bitta kalit hammasini, keyingi relizdagi
 *      ruxsatlarni ham beradi. Yoqilganda qolgan kataklar "kiritilgan"
 *      bo'lib qulflanadi: alohida belgilash ma'nosiz.
 *   2. KIRISH YUZALARI — admin panel (`panel.access`) va desktop client
 *      (`client.operate`). Bular "QAYERDA ishlaydi" degan savol: Operator
 *      faqat client, Proktor faqat panel. Panel o'chiq bo'lsa bo'lim
 *      ruxsatlari ishlamaydi — buni ochiq aytamiz, jimgina emas.
 *   3. BO'LIM RUXSATLARI — guruh kartalari, guruh bo'yicha belgilash.
 *
 * Tahrirlovchida yo'q ruxsatni QO'SHIB bo'lmaydi (server ham rad etadi —
 * `RoleSerializer.validate`); olib tashlash erkin.
 */
export default function PermissionMatrix({ permissions, selected, onChange, disabled, canGrant }) {
  const [query, setQuery] = useState('')
  const [onlySelected, setOnlySelected] = useState(false)

  const byCode = useMemo(
    () => Object.fromEntries((permissions || []).map((item) => [item.code, item])),
    [permissions],
  )
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const isOn = (code) => Boolean(byCode[code]) && selectedSet.has(byCode[code].id)

  const full = isOn(FULL_ACCESS)
  const panelOn = full || isOn(PANEL_ACCESS)
  const clientOn = full || isOn(CLIENT_OPERATE)

  const groups = useMemo(() => groupPermissions(permissions), [permissions])
  const clientItems = groups.find((group) => group.group === 'client')?.items || []
  const sectionGroups = groups.filter((group) => group.group !== 'client')

  // Panel bo'limlarida belgilangan, lekin panelga kirish o'chiq — rol
  // panelda ishlamaydi. Eski bazalardagi Operator aynan shunday.
  const orphanPanelCount = !panelOn
    ? sectionGroups.flatMap((group) => group.items).filter((item) => selectedSet.has(item.id)).length
    : 0

  const grantable = (item) => !canGrant || selectedSet.has(item.id) || canGrant(item.code)

  const setMany = (items, on) => {
    const ids = items.filter((item) => !on || grantable(item)).map((item) => item.id)
    onChange(
      on
        ? [...new Set([...selected, ...ids])]
        : selected.filter((id) => !ids.includes(id)),
    )
  }
  const toggle = (item) => setMany([item], !selectedSet.has(item.id))

  const needle = query.trim().toLowerCase()
  const matches = (item) =>
    (!needle || item.name.toLowerCase().includes(needle) || item.code.toLowerCase().includes(needle)) &&
    (!onlySelected || full || selectedSet.has(item.id))

  if (!permissions?.length) {
    return (
      <Stack spacing={1.5}>
        <Skeleton variant="rounded" height={88} sx={{ borderRadius: '16px' }} />
        <Skeleton variant="rounded" height={200} sx={{ borderRadius: '16px' }} />
      </Stack>
    )
  }

  const sectionTotal = sectionGroups.reduce((sum, group) => sum + group.items.length, 0)
  const sectionChosen = full
    ? sectionTotal
    : sectionGroups.reduce((sum, group) => sum + group.items.filter((item) => selectedSet.has(item.id)).length, 0)

  return (
    <Stack spacing={1.5}>
      {/* 1. To'liq huquq */}
      {byCode[FULL_ACCESS] && (
        <SurfaceTile
          icon={ShieldIcon}
          title="To‘liq huquq"
          description="Barcha amallar — keyingi yangilanishlarda qo‘shiladigan ruxsatlar ham. Administrator roli uchun."
          on={full}
          tone="primary"
          disabled={disabled || !grantable(byCode[FULL_ACCESS])}
          lockedReason={!grantable(byCode[FULL_ACCESS]) ? 'To‘liq huquqni faqat o‘zida to‘liq huquq bor xodim beradi' : ''}
          onToggle={() => toggle(byCode[FULL_ACCESS])}
        />
      )}

      {/* 2. Kirish yuzalari. Grid `Box` ichida: Stack bolalarining
          chetini nolga tushiradi va Grid'ning manfiy chetlari yo'qolib,
          plitkalar o'ngga siljiydi. */}
      <Box>
        <Grid container spacing={1.5}>
          {byCode[PANEL_ACCESS] && (
            <Grid item xs={12} md={6}>
              <SurfaceTile
                icon={WebIcon}
                title="Admin panel"
                description="Panelga login va uning API’si. Usiz bo‘lim ruxsatlari ishlamaydi."
                on={panelOn}
                disabled={disabled || full || !grantable(byCode[PANEL_ACCESS])}
                onToggle={() => toggle(byCode[PANEL_ACCESS])}
                footer={
                  panelOn
                    ? <Typography variant="caption" color="text.secondary">{sectionChosen} / {sectionTotal} bo‘lim ruxsati</Typography>
                    : null
                }
              />
            </Grid>
          )}
          {byCode[CLIENT_OPERATE] && (
            <Grid item xs={12} md={byCode[PANEL_ACCESS] ? 6 : 12}>
              <SurfaceTile
                icon={DesktopIcon}
                title="Desktop client"
                description="Imtihon markazidagi ish o‘rni: talabgorni qabul qilish va imtihonni boshlash."
                on={clientOn}
                disabled={disabled || full || !grantable(byCode[CLIENT_OPERATE])}
                // O'chirilganda butun client guruhi olinadi: `client.operate`
                // siz qolgan client ruxsatlari ishlamaydi (`ClientBaseView`).
                onToggle={() => setMany(clientItems, !clientOn)}
                footer={
                  clientOn && clientItems.length > 1 ? (
                    <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                      {clientItems
                        .filter((item) => item.code !== CLIENT_OPERATE)
                        .map((item) => (
                          <PermissionRow
                            key={item.id}
                            item={item}
                            checked={full || selectedSet.has(item.id)}
                            disabled={disabled || full || !grantable(item)}
                            onToggle={() => toggle(item)}
                            dense
                          />
                        ))}
                    </Stack>
                  ) : null
                }
              />
            </Grid>
          )}
        </Grid>
      </Box>

      {orphanPanelCount > 0 && (
        <Alert severity="warning" icon={<WarningIcon />} sx={{ borderRadius: '12px' }}>
          {orphanPanelCount} ta bo‘lim ruxsati belgilangan, lekin «Admin panel» o‘chiq — bu rol
          panelga kira olmaydi va ular ishlamaydi. Rol faqat client uchun bo‘lsa, ularni olib tashlang.
        </Alert>
      )}

      {/* 3. Bo'lim ruxsatlari */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        alignItems={{ sm: 'center' }}
        sx={{ pt: 1 }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2">Bo‘lim ruxsatlari</Typography>
          <Typography variant="caption" color="text.secondary">
            {full ? 'To‘liq huquq — hammasi kiritilgan' : `${sectionChosen} / ${sectionTotal} tanlangan`}
          </Typography>
        </Box>
        <TextField
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ruxsatni qidirish…"
          sx={{ maxWidth: { sm: 260 } }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start"><SearchIcon fontSize="small" color="disabled" /></InputAdornment>
            ),
          }}
        />
        <Chip
          label="Faqat tanlanganlar"
          variant={onlySelected ? 'filled' : 'outlined'}
          color={onlySelected ? 'primary' : 'default'}
          onClick={() => setOnlySelected((prev) => !prev)}
          sx={{ borderRadius: '8px', height: 32 }}
        />
      </Stack>

      <Box>
        <Grid container spacing={1.5}>
          {sectionGroups.map(({ group, meta, items }) => {
            const visible = items.filter(matches)
            if (!visible.length) return null
            const chosen = full ? items.length : items.filter((item) => selectedSet.has(item.id)).length
            const all = chosen === items.length
            const Icon = meta.icon
            return (
              <Grid item xs={12} sm={6} lg={4} key={group}>
                <Box
                  sx={{
                    height: '100%', borderRadius: '16px', p: 1.5,
                    border: 1, borderColor: chosen ? 'primary.main' : 'm3.outlineVariant',
                    bgcolor: chosen ? 'm3.surfaceContainerLow' : 'transparent',
                    opacity: panelOn ? 1 : 0.7,
                    transition: 'border-color 150ms, background-color 150ms',
                  }}
                >
                  <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 0.75 }}>
                    <Box
                      sx={{
                        width: 36, height: 36, borderRadius: '12px', flexShrink: 0,
                        display: 'grid', placeItems: 'center',
                        bgcolor: chosen ? 'm3.primaryContainer' : 'm3.surfaceContainerHighest',
                        color: chosen ? 'm3.onPrimaryContainer' : 'text.secondary',
                      }}
                    >
                      <Icon fontSize="small" />
                    </Box>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="subtitle2" noWrap>{meta.label}</Typography>
                      <Typography variant="caption" color="text.secondary" noWrap display="block">
                        {meta.description || `${items.length} ta ruxsat`}
                      </Typography>
                    </Box>
                    <Tooltip title={all ? 'Guruhni olib tashlash' : 'Guruhni to‘liq berish'}>
                      <span>
                        <Checkbox
                          checked={all}
                          indeterminate={chosen > 0 && !all}
                          disabled={disabled || full}
                          onChange={() => setMany(items, !all)}
                          inputProps={{ 'aria-label': `${meta.label} — barchasi` }}
                        />
                      </span>
                    </Tooltip>
                  </Stack>
                  <Stack spacing={0.25}>
                    {visible.map((item) => (
                      <PermissionRow
                        key={item.id}
                        item={item}
                        checked={full || selectedSet.has(item.id)}
                        disabled={disabled || full || !grantable(item)}
                        lockedReason={!grantable(item) ? 'Sizda bu ruxsat yo‘q — uni bera olmaysiz' : ''}
                        onToggle={() => toggle(item)}
                      />
                    ))}
                  </Stack>
                </Box>
              </Grid>
            )
          })}
        </Grid>
      </Box>

      {!full && (
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button size="small" disabled={disabled} onClick={() => setMany(sectionGroups.flatMap((group) => group.items), true)}>
            Barcha bo‘limlar
          </Button>
          <Button size="small" color="inherit" disabled={disabled || !selected.length} onClick={() => onChange([])}>
            Hammasini tozalash
          </Button>
        </Stack>
      )}
    </Stack>
  )
}

/** Kirish yuzasi / to'liq huquq — MD3 tonal karta + kalit. */
function SurfaceTile({ icon: Icon, title, description, on, onToggle, disabled, footer, tone = 'secondary', lockedReason }) {
  const container = tone === 'primary' ? 'm3.primaryContainer' : 'm3.secondaryContainer'
  const onContainer = tone === 'primary' ? 'm3.onPrimaryContainer' : 'm3.onSecondaryContainer'
  return (
    <Tooltip title={lockedReason || ''} placement="top">
      <Box
        sx={{
          height: '100%', borderRadius: '16px', p: 2,
          border: 1, borderColor: on ? 'transparent' : 'm3.outlineVariant',
          bgcolor: on ? container : 'transparent',
          transition: 'background-color 150ms, border-color 150ms',
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Box
            sx={{
              width: 40, height: 40, borderRadius: '12px', flexShrink: 0,
              display: 'grid', placeItems: 'center',
              bgcolor: on ? 'background.paper' : 'm3.surfaceContainerHighest',
              color: on ? onContainer : 'text.secondary',
            }}
          >
            <Icon fontSize="small" />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle2" sx={{ color: on ? onContainer : 'text.primary' }}>{title}</Typography>
            <Typography variant="caption" color="text.secondary" display="block">{description}</Typography>
          </Box>
          <Switch
            checked={on}
            disabled={disabled}
            onChange={onToggle}
            inputProps={{ 'aria-label': title }}
          />
        </Stack>
        {footer && <Box sx={{ pl: { sm: 6.5 }, mt: 0.75 }}>{footer}</Box>}
      </Box>
    </Tooltip>
  )
}

/** Bitta ruxsat: katak + nom + kod. Butun qator bosiladi. */
function PermissionRow({ item, checked, disabled, onToggle, lockedReason, dense }) {
  return (
    <Tooltip title={lockedReason || ''} placement="left">
      <Box
        component="label"
        sx={{
          display: 'flex', alignItems: 'center', gap: 0.5, pr: 1,
          borderRadius: '10px', cursor: disabled ? 'default' : 'pointer',
          bgcolor: checked && !dense ? 'm3.secondaryContainer' : 'transparent',
          opacity: disabled && !checked ? 0.55 : 1,
          '&:hover': disabled ? undefined : { bgcolor: checked && !dense ? 'm3.secondaryContainer' : 'action.hover' },
        }}
      >
        <Checkbox size="small" checked={checked} disabled={disabled} onChange={onToggle} />
        <Box sx={{ minWidth: 0, py: 0.5 }}>
          <Typography variant="body2" sx={{ lineHeight: 1.3 }}>{item.name}</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace', fontSize: 11 }}>
            {item.code}
          </Typography>
        </Box>
      </Box>
    </Tooltip>
  )
}
