import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, IconButton, Stack, Typography,
  useMediaQuery, useTheme,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'

import { HeaderIcon } from './DetailFields'

/**
 * MD3 tafsilot oynasi qobig'i — ma'lumotnoma sahifalarida qator bosilganda.
 *
 * Kompyuter va xodim kartalari (`ComputerDetailDialog`, `UserDetailDialog`)
 * bilan bir xil tuzilma: tonal belgi + sarlavha + holat chiplari, ostida
 * MUAMMOLAR (nima uchun bu yozuv ishlamayapti), keyin `Section`/`Field`
 * kartalari va pastda amallar. Har sahifa faqat mazmunni beradi — oyna
 * shakli bitta joyda, besh nusxada emas.
 *
 * `onEdit` berilmasa (ruxsat yo'q yoki yozuv o'chirilgan) «Tahrirlash»
 * tugmasi chizilmaydi: bosilganda server rad etadigan tugma qolmasin.
 */
export default function DetailDialog({
  icon,
  tone = 'primary',
  title,
  subtitle,
  chips,
  problems = [],
  children,
  actions,
  onEdit,
  onClose,
  maxWidth = 'md',
}) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth={maxWidth}
      fullWidth
      fullScreen={fullScreen}
      slotProps={{ paper: { sx: { bgcolor: 'm3.surfaceContainerLow', borderRadius: fullScreen ? 0 : '28px' } } }}
    >
      <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ px: { xs: 2, sm: 3 }, pt: 3, pb: 2 }}>
        <HeaderIcon tone={tone}>{icon}</HeaderIcon>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h6" sx={{ lineHeight: 1.3, wordBreak: 'break-word' }}>{title}</Typography>
          {subtitle && (
            <Typography component="div" variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
              {subtitle}
            </Typography>
          )}
          {chips && (
            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
              {chips}
            </Stack>
          )}
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
        {children}
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2, gap: 1, bgcolor: 'm3.surfaceContainer', flexWrap: 'wrap' }}>
        {actions}
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose}>Yopish</Button>
        {onEdit && (
          <Button variant="contained" disableElevation startIcon={<EditIcon />} onClick={onEdit}>
            Tahrirlash
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}

/**
 * Raqamli ko'rsatkichlar qatori (MD3 tonal plitkalar): "12 bino",
 * "340 kompyuter". `value` bo'sh bo'lsa — chiziqcha (yuklanmoqda / yo'q).
 */
export function StatTiles({ items }) {
  return (
    <Box
      sx={{
        display: 'grid', gap: 1, mb: 1.5,
        gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: `repeat(${items.length}, minmax(0, 1fr))` },
      }}
    >
      {items.map((item) => (
        <Box
          key={item.label}
          sx={{
            p: 1.75, borderRadius: '16px', minWidth: 0,
            // Ogohlantirish plitkasida matn ham to'q ton — tungi rejimda
            // och fon ustida och matn o'qilmasdi (`HeaderIcon` dagi juftlik).
            ...(item.tone === 'warning'
              ? { bgcolor: 'warning.light', color: 'warning.dark', '& .MuiTypography-caption': { color: 'inherit' } }
              : { bgcolor: 'background.paper' }),
          }}
        >
          <Typography variant="h5" sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>
            {item.value ?? '—'}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" noWrap>
            {item.label}
          </Typography>
          {item.hint && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ opacity: 0.8 }} noWrap>
              {item.hint}
            </Typography>
          )}
        </Box>
      ))}
    </Box>
  )
}

/**
 * Izoh bloki ("bu yozuv nima qiladi") — tonal fon, belgi bilan.
 * Ma'lumot jadvali emas, tushuntirish: administrator qaror qabul
 * qilishidan oldin oqibatni o'qishi kerak.
 */
export function InfoNote({ icon, children, tone = 'primary' }) {
  const palette = tone === 'warning'
    ? { bgcolor: 'warning.light', color: 'warning.dark' }
    : { bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer' }
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ p: 2, mb: 1.5, borderRadius: '16px', ...palette }}>
      {icon && <Box sx={{ display: 'flex', mt: '1px' }}>{icon}</Box>}
      <Typography component="div" variant="body2" sx={{ color: 'inherit' }}>{children}</Typography>
    </Stack>
  )
}
