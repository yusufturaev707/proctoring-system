import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Card, CardContent, CircularProgress, Stack, Typography } from '@mui/material'
import DesktopIcon from '@mui/icons-material/DesktopMacOutlined'
import LogoutIcon from '@mui/icons-material/LogoutOutlined'

import { useAuth } from '../../context/AuthContext'

/**
 * Hisob bor, lekin rolida `panel.access` yo'q (Operator kabi client roli).
 *
 * Login bunday hisobga panel tokenini bermaydi; bu ekran — brauzerda
 * qolgan ESKI token uchun (masalan qoida kiritilishidan oldin kirilgan).
 * Bo'sh menyu va qizil "ruxsat yo'q" xatolari o'rniga bitta tushunarli
 * ekran va yagona amal — chiqish. Server baribir hech narsa bermaydi
 * (`HasPanelAccess`).
 */
export default function NoPanelAccess() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [leaving, setLeaving] = useState(false)

  const handleLogout = async () => {
    setLeaving(true)
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <Box
      sx={{
        minHeight: '100vh', display: 'grid', placeItems: 'center', p: 2,
        bgcolor: 'background.default',
      }}
    >
      <Card sx={{ width: '100%', maxWidth: 460, borderRadius: '28px', bgcolor: 'm3.surfaceContainerLowest' }}>
        <CardContent sx={{ p: { xs: 3, sm: 4.5 }, '&:last-child': { pb: { xs: 3, sm: 4.5 } } }}>
          <Stack spacing={1.5} alignItems="center" textAlign="center">
            <Box
              sx={{
                width: 64, height: 64, borderRadius: '20px', display: 'grid', placeItems: 'center',
                bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer', mb: 1,
              }}
            >
              <DesktopIcon sx={{ fontSize: 32 }} />
            </Box>
            <Typography variant="h5" component="h1">Bu hisob desktop client uchun</Typography>
            <Typography variant="body2" color="text.secondary">
              {user?.role_name ? `«${user.role_name}» roli` : 'Rolingiz'} imtihon markazidagi client
              dasturida ishlaydi — admin panelga kirish huquqi berilmagan.
              Panel kerak bo‘lsa, administrator rolingizga «Admin panelga kirish» ruxsatini qo‘shishi kerak.
            </Typography>
            {user?.username && (
              <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                {user.username}
              </Typography>
            )}
            <Button
              variant="contained"
              size="large"
              disableElevation
              startIcon={leaving ? <CircularProgress size={18} color="inherit" /> : <LogoutIcon />}
              disabled={leaving}
              onClick={handleLogout}
              sx={{ mt: 1.5, alignSelf: 'stretch' }}
            >
              Boshqa hisob bilan kirish
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  )
}
