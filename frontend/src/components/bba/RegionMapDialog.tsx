import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography,
} from '@mui/material'

import { bba } from '../../api/endpoints'
import { useUi } from '../../context/UiContext'
import { useRegionOptions } from '../../pages/crud/shared'
import type { ApiRecord, Id } from '../../types/api'

/**
 * Console hududi -> bizning viloyat. Viloyat xodimi BBA kompyuterlarini
 * faqat shu bog'lanish orqali ko'radi; bog'lanmagan hudud — faqat
 * respublika darajasida. Nom bo'yicha avtomatik bog'lanmaydi (ikki tizimda
 * nomlar har xil yozilgan va xato bog'lash begona viloyatni ochardi).
 */
export default function RegionMapDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { options: regionOptions } = useRegionOptions()
  const { data: regions = [], isLoading } = useQuery({
    queryKey: ['bba-regions'],
    queryFn: () => bba.regions.list(),
  })

  const mutation = useMutation({
    mutationFn: ({ id, region }: { id: Id; region: Id | null }) => bba.regions.update({ id, region }),
    retry: false,
    onSuccess: () => {
      notify('Saqlandi')
      queryClient.invalidateQueries({ queryKey: ['bba-regions'] })
      queryClient.invalidateQueries({ queryKey: ['bba-overview'] })
      queryClient.invalidateQueries({ queryKey: ['bba-devices'] })
    },
    onError: notifyError,
  })

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Console hududlarini viloyatlarga bog‘lash</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <Alert severity="info">
            Viloyat xodimlari faqat o‘z viloyatiga bog‘langan hududning kompyuterlarini ko‘radi.
          </Alert>
          {!isLoading && regions.length === 0 && (
            <Typography color="text.secondary">Console hududlari hali sinxronlanmagan.</Typography>
          )}
          {regions.map((item: ApiRecord) => (
            <Stack key={item.id} direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
              <Stack sx={{ flex: 1, minWidth: 0 }}>
                <Typography fontWeight={600} noWrap>
                  {item.name}{item.is_visible ? '' : ' (ko‘rinmayapti)'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {[item.code, item.subnet, `${item.device_count} ta kompyuter`].filter(Boolean).join(' · ')}
                </Typography>
              </Stack>
              <TextField
                select
                size="small"
                label="Viloyat"
                value={item.region ?? ''}
                disabled={mutation.isPending}
                onChange={(event) => mutation.mutate({
                  id: item.id, region: event.target.value === '' ? null : Number(event.target.value),
                })}
                sx={{ width: { xs: '100%', sm: 240 } }}
              >
                <MenuItem value="">Bog‘lanmagan</MenuItem>
                {regionOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
                ))}
              </TextField>
            </Stack>
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Yopish</Button>
      </DialogActions>
    </Dialog>
  )
}
