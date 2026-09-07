import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, Stack, TextField, Typography,
} from '@mui/material'

/**
 * Tasdiqlash oynasi.
 *
 * Uch darajali qat'iylik:
 *   1. Oddiy tasdiq — qaytarib bo'ladigan amallar;
 *   2. `requireReason` — sabab audit yozuviga tushadi (chetlashtirish);
 *   3. `confirmPhrase` — foydalanuvchi obyekt nomini QO'LDA yozadi.
 *      Bu ommaviy/qaytarib bo'lmaydigan o'chirish uchun: tasodifiy
 *      "Enter" bosish yoki muscle memory bilan tasdiqlashning oldini
 *      oladi. Yozish harakati e'tiborni majburan qaratadi.
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  details,
  confirmLabel = 'Tasdiqlash',
  cancelLabel = 'Bekor qilish',
  color = 'primary',
  requireReason = false,
  reasonLabel = 'Sabab',
  reasonMinLength = 3,
  confirmPhrase = null,
  loading = false,
  onConfirm,
  onClose,
}) {
  const [reason, setReason] = useState('')
  const [phrase, setPhrase] = useState('')

  useEffect(() => {
    if (open) {
      setReason('')
      setPhrase('')
    }
  }, [open])

  const reasonInvalid = requireReason && reason.trim().length < reasonMinLength
  const phraseInvalid = confirmPhrase && phrase.trim() !== confirmPhrase
  const disabled = loading || reasonInvalid || phraseInvalid

  const handleConfirm = () => {
    if (disabled) return
    onConfirm?.(reason.trim())
  }

  return (
    <Dialog open={open} onClose={loading ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          {description && (
            <Alert severity={color === 'error' ? 'warning' : 'info'} sx={{ '& .MuiAlert-message': { width: '100%' } }}>
              {description}
            </Alert>
          )}

          {details && (
            <Box sx={{ bgcolor: 'surface.subtle', borderRadius: 2, p: 1.5 }}>
              {details}
            </Box>
          )}

          {requireReason && (
            <TextField
              label={reasonLabel}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              multiline
              minRows={2}
              autoFocus
              required
              disabled={loading}
              error={reason.length > 0 && reasonInvalid}
              helperText={
                reason.length > 0 && reasonInvalid
                  ? `Kamida ${reasonMinLength} ta belgi`
                  : 'Bu matn audit yozuviga saqlanadi'
              }
            />
          )}

          {confirmPhrase && (
            <Box>
              <Typography variant="body2" sx={{ mb: 1 }}>
                Tasdiqlash uchun <strong>{confirmPhrase}</strong> deb yozing:
              </Typography>
              <TextField
                value={phrase}
                onChange={(event) => setPhrase(event.target.value)}
                autoFocus={!requireReason}
                disabled={loading}
                error={phrase.length > 0 && phraseInvalid}
                placeholder={confirmPhrase}
                autoComplete="off"
              />
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit" disabled={loading}>
          {cancelLabel}
        </Button>
        <Button
          onClick={handleConfirm}
          variant="contained"
          color={color}
          disabled={disabled}
          startIcon={loading ? <CircularProgress size={16} color="inherit" /> : null}
        >
          {loading ? 'Bajarilmoqda…' : confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
