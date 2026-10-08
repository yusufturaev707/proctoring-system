import { Box, Chip, Stack, TextField, Typography } from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckCircleOutline'

import { hotkeyLabel, parseHotkey } from '../../utils/hotkeys'
import { Keycaps } from './ControlBits'

/** Tez to'ldirish uchun keng tarqalgan kombinatsiyalar. */
const EXAMPLES = ['alt+tab', 'win', 'alt+f4', 'print screen', 'ctrl+shift+esc', 'ctrl+shift+i', 'f12', 'ctrl+c', 'ctrl+v']

/**
 * Tezkor tugma kodi: matn + jonli tugmacha ko'rinishi + client qoidasi.
 *
 * Kod yozilayotganda client uni qanday o'qishi ko'rsatiladi
 * (`utils/hotkeys.js` — client `lockdown.py` nusxasi). Noma'lum nom
 * (`pageup`, `leftalt`) shu zahoti qizil: client uni BLOKLAMASDI.
 */
export default function HotkeyInput({ value, onChange, error, disabled }) {
  const parsed = parseHotkey(value)
  const typed = Boolean(String(value ?? '').trim())
  const changed = typed && parsed.code !== String(value).trim()

  return (
    <Stack spacing={1.5}>
      <TextField
        id="field-code"
        label="Kod"
        required
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        error={Boolean(error) || (typed && Boolean(parsed.error))}
        inputProps={{ maxLength: 100, spellCheck: false, style: { fontFamily: 'monospace' } }}
        helperText={
          error ? undefined
            : typed && parsed.error ? parsed.error
              : 'Tugmalar «+» bilan: alt+tab, ctrl+shift+i, print screen, left alt+f4'
        }
      />

      {/* Client nima ko'radi: kanonik kod va tugmachalar. */}
      <Box
        sx={{
          p: 2, borderRadius: '12px', border: 1, minHeight: 72,
          borderColor: typed && parsed.error ? 'error.main' : 'm3.outlineVariant',
          bgcolor: 'm3.surfaceContainerLow',
        }}
      >
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          Client shunday bloklaydi
        </Typography>
        {typed ? (
          <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap flexWrap="wrap">
            <Keycaps code={parsed.code} />
            {!parsed.error && (
              <Stack direction="row" spacing={0.5} alignItems="center" sx={{ color: 'success.main' }}>
                <CheckIcon fontSize="small" />
                <Typography variant="caption" sx={{ color: 'inherit' }}>
                  Client taniydi{changed ? ` · «${parsed.code}» bo‘lib saqlanadi` : ''}
                </Typography>
              </Stack>
            )}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.disabled">Kod kiritilmagan</Typography>
        )}
      </Box>

      <Box>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
          Tez tanlash
        </Typography>
        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
          {EXAMPLES.map((example) => (
            <Chip
              key={example}
              size="small"
              variant={parsed.code === example ? 'filled' : 'outlined'}
              color={parsed.code === example ? 'primary' : 'default'}
              label={hotkeyLabel(example)}
              disabled={disabled}
              onClick={() => onChange(example)}
            />
          ))}
        </Stack>
      </Box>
    </Stack>
  )
}
