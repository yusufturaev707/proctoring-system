import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, List, ListItem, ListItemText,
  MenuItem, Stack, TextField, Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/AddToQueueOutlined'

import { bba } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { useUi } from '../../context/UiContext'
import { useRegionOptions, useZoneOptions, zonesOfRegion } from '../../pages/crud/shared'
import type { BulkSelection } from '../../api/endpoints'
import type { ApiError, ApiRecord } from '../../types/api'

export interface ImportTarget {
  device?: ApiRecord
  selection?: BulkSelection
  count: number
}

/**
 * BBA kompyuterini bizning «Kompyuterlar» ro'yxatiga qo'shish.
 *
 * UUID va MAC — Console inventory'sidan (qo'lda yozilmaydi: xato yozilgan
 * MAC bilan mashina keyin handshake'da `not_found` olardi). Bitta
 * kompyuterda MAC tanlanadi (standart — client yuboradigani: shlyuzli faol
 * adapter), raqam va inventar kodi kiritiladi. Ko'pida — faqat bino:
 * raqamsiz, inventar kodi Console nomidan yoki `AUTO-...`.
 */
export default function ImportDialog({
  target, onClose, onDone,
}: { target: ImportTarget; onClose: () => void; onDone?: () => void }) {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { user } = useAuth()
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()
  const device = target.device

  const [region, setRegion] = useState<string>(user?.is_region_scoped ? String(user.region ?? '') : '')
  const [zone, setZone] = useState('')
  const [number, setNumber] = useState('')
  const [code, setCode] = useState<string>(device?.suggested_inventory_code || '')
  const [mac, setMac] = useState<string>(device?.primary_mac || device?.macs?.[0] || '')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [results, setResults] = useState<ApiRecord | null>(null)

  const zones = useMemo(() => (region ? zonesOfRegion(zoneOptions, region) : zoneOptions), [zoneOptions, region])

  const mutation = useMutation({
    mutationFn: () => {
      if (device) {
        return bba.devices.importComputer(device.id, {
          zone, number: number ? Number(number) : null, inventory_code: code.trim(), mac_address: mac,
        })
      }
      return bba.devices.bulkImport(target.selection!, { zone })
    },
    retry: false,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['bba-devices'] })
      queryClient.invalidateQueries({ queryKey: ['bba-device'] })
      queryClient.invalidateQueries({ queryKey: ['bba-overview'] })
      queryClient.invalidateQueries({ queryKey: ['computers'] })
      onDone?.()
      if (device) {
        notify(`Kompyuter ro‘yxatga qo‘shildi: ${result.label}`)
        onClose()
        return
      }
      setResults(result)
      notify(
        `${result.created} ta qo‘shildi` +
        (result.skipped ? ` · ${result.skipped} tasi allaqachon bor` : '') +
        (result.failed ? ` · ${result.failed} tasida xato` : ''),
        result.failed ? 'warning' : 'success',
      )
    },
    onError: (error) => {
      const fields = (error as ApiError).fieldErrors || {}
      setFieldErrors(Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, String(value)])))
      notifyError(error)
    },
  })

  const failed: ApiRecord[] = (results?.results || []).filter((row: ApiRecord) => row.status === 'error')
  const missingUuid = device && !device.system_uuid

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <AddIcon color="primary" />
        {device ? `«${device.name}» ni ro‘yxatga qo‘shish` : `${target.count} ta kompyuterni ro‘yxatga qo‘shish`}
      </DialogTitle>
      <DialogContent dividers>
        {results ? (
          <Stack spacing={1.5}>
            <Alert severity={failed.length ? 'warning' : 'success'}>
              Qo‘shildi: {results.created} · allaqachon bor: {results.skipped} · xato: {results.failed}
            </Alert>
            {failed.length > 0 && (
              <List dense disablePadding sx={{ maxHeight: 280, overflow: 'auto' }}>
                {failed.map((row) => (
                  <ListItem key={row.id} disableGutters>
                    <ListItemText primary={row.name} secondary={row.message} />
                  </ListItem>
                ))}
              </List>
            )}
          </Stack>
        ) : (
          <Stack spacing={2}>
            {missingUuid && (
              <Alert severity="warning">
                Inventory’da haqiqiy System UUID yo‘q — avval «Inventory’ni yangilash» ni bosing
                (agent 0.1.96 va yangisi kerak).
              </Alert>
            )}
            {!device && (
              <Alert severity="info">
                Har kompyuter Console inventory’sidagi UUID va MAC bilan qo‘shiladi; raqam
                qo‘yilmaydi, inventar kodi — Console nomi (band bo‘lsa avtomatik kod).
                UUID’si yo‘q yoki allaqachon ro‘yxatdagilar o‘tkazib yuboriladi.
              </Alert>
            )}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              {!user?.is_region_scoped && (
                <TextField
                  select
                  label="Viloyat"
                  value={region}
                  onChange={(event) => {
                    setRegion(event.target.value)
                    setZone('')
                  }}
                  fullWidth
                >
                  <MenuItem value="">Barchasi</MenuItem>
                  {regionOptions.map((option) => (
                    <MenuItem key={option.value} value={String(option.value)}>{option.label}</MenuItem>
                  ))}
                </TextField>
              )}
              <TextField
                select
                required
                label="Bino"
                value={zone}
                onChange={(event) => setZone(event.target.value)}
                error={Boolean(fieldErrors.zone)}
                helperText={fieldErrors.zone}
                fullWidth
              >
                {zones.map((option) => (
                  <MenuItem key={option.value} value={String(option.value)}>
                    {region ? option.shortLabel || option.label : option.label}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            {device && (
              <>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                  <TextField
                    label="Raqami (stoldagi)"
                    type="number"
                    value={number}
                    onChange={(event) => setNumber(event.target.value)}
                    error={Boolean(fieldErrors.number)}
                    helperText={fieldErrors.number || 'Ixtiyoriy'}
                    slotProps={{ htmlInput: { min: 1, max: 32767 } }}
                    sx={{ width: { sm: 180 } }}
                  />
                  <TextField
                    label="Inventar kodi"
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    error={Boolean(fieldErrors.inventory_code)}
                    helperText={fieldErrors.inventory_code || 'Bo‘sh — avtomatik'}
                    fullWidth
                  />
                </Stack>
                <TextField
                  select
                  label="MAC manzil"
                  value={mac}
                  onChange={(event) => setMac(event.target.value)}
                  error={Boolean(fieldErrors.mac_address)}
                  helperText={
                    fieldErrors.mac_address ||
                    'Client yuboradigan adapter — imtihon tarmog‘iga ulangani. Wi-Fi emas.'
                  }
                  fullWidth
                  slotProps={{ select: { sx: { fontFamily: 'monospace' } } }}
                >
                  {(device.macs || []).map((value: string) => (
                    <MenuItem key={value} value={value} sx={{ fontFamily: 'monospace' }}>
                      {value}{value === device.primary_mac ? '  · faol adapter' : ''}
                    </MenuItem>
                  ))}
                </TextField>
                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                  System UUID: {device.system_uuid || '—'}
                </Typography>
              </>
            )}
            {fieldErrors.machine_uuid && <Alert severity="error">{fieldErrors.machine_uuid}</Alert>}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{results ? 'Yopish' : 'Bekor qilish'}</Button>
        {!results && (
          <Button
            variant="contained"
            disableElevation
            disabled={!zone || mutation.isPending || Boolean(missingUuid)}
            onClick={() => {
              setFieldErrors({})
              mutation.mutate()
            }}
            sx={{ borderRadius: 999 }}
          >
            Qo‘shish
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
