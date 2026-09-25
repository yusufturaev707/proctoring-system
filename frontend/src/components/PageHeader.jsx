import { useLocation } from 'react-router-dom'
import { Box, Stack, Tooltip, Typography } from '@mui/material'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import ChevronIcon from '@mui/icons-material/ChevronRightRounded'

import { findNavEntry } from '../layout/navigation'

/**
 * Sahifa sarlavhasi.
 *
 * YUQORIDA — BO'LIM NOMI (`Infratuzilma › Kameralar`). Yuqori sarlavha
 * olib tashlangach bu yagona "men qayerdaman?" belgisi: yon panel
 * yig'ilgan bo'lsa, faol ikonka o'zi bo'limni aytmaydi. Qiymat menyu
 * tuzilishidan olinadi (`findNavEntry`) — sahifalar uni qo'lda
 * uzatmaydi va menyu qayta guruhlanganda ular ajralib ketmaydi.
 *
 * "i" BELGISI — menyudagi tavsif ("bu sahifa NIMA UCHUN"). Sahifaning
 * o'z `subtitle` i boshqa savolga javob beradi va ko'pincha texnik
 * qoidani aytadi, shuning uchun ular birlashtirilmaydi.
 */
export default function PageHeader({ title, subtitle, actions }) {
  const location = useLocation()
  const entry = findNavEntry(location.pathname)
  // Tafsilot sahifasida (`/sessions/42`) ota sahifa nomi ham ko'rinadi.
  const nested = entry && entry.item.path !== location.pathname && entry.item.label !== title

  return (
    <Stack
      direction={{ xs: 'column', md: 'row' }}
      justifyContent="space-between"
      alignItems={{ xs: 'stretch', md: 'flex-end' }}
      spacing={2}
      sx={{ mb: 3 }}
    >
      <Box sx={{ minWidth: 0 }}>
        {entry && (
          <Stack
            direction="row"
            alignItems="center"
            spacing={0.25}
            sx={{ mb: 0.5, color: 'text.secondary' }}
            aria-label="Joylashuv"
          >
            <Typography variant="caption" sx={{ fontWeight: 600 }}>{entry.section}</Typography>
            {nested && (
              <>
                <ChevronIcon sx={{ fontSize: 16 }} />
                <Typography variant="caption" sx={{ fontWeight: 600 }}>{entry.item.label}</Typography>
              </>
            )}
          </Stack>
        )}

        <Stack direction="row" alignItems="center" spacing={0.75}>
          <Typography variant="h5" component="h1">{title}</Typography>
          {entry?.item.description && !nested && (
            <Tooltip title={entry.item.description} placement="bottom-start">
              <InfoIcon
                tabIndex={0}
                aria-label={entry.item.description}
                sx={{ fontSize: 19, color: 'text.disabled', cursor: 'help', '&:hover': { color: 'text.secondary' } }}
              />
            </Tooltip>
          )}
        </Stack>

        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 820 }}>
            {subtitle}
          </Typography>
        )}
      </Box>

      {actions && (
        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          flexWrap="wrap"
          useFlexGap
          // `minWidth: 0` — telefonda segmentli guruh sarlavha kengligidan
          // oshmasin va o'z ichida surilsin (tema: `MuiToggleButtonGroup`).
          sx={{ flexShrink: 0, minWidth: 0, maxWidth: '100%' }}
        >
          {actions}
        </Stack>
      )}
    </Stack>
  )
}
