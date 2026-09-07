import { Suspense, useCallback, useMemo, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { alpha } from '@mui/material/styles'
import {
  AppBar, Avatar, Box, Chip, Divider, Drawer, IconButton, List, ListItemButton,
  ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Toolbar, Tooltip,
  Typography, useMediaQuery, useTheme,
} from '@mui/material'
import MenuIcon from '@mui/icons-material/Menu'
import LightModeIcon from '@mui/icons-material/LightModeOutlined'
import DarkModeIcon from '@mui/icons-material/DarkModeOutlined'
import LogoutIcon from '@mui/icons-material/LogoutOutlined'
import SettingsIcon from '@mui/icons-material/TuneOutlined'
import ShieldIcon from '@mui/icons-material/GppGoodOutlined'

import { NAVIGATION, prefetchRoute } from './navigation'
import { PageTransition } from '../components/motion/Transitions'
import { PageSkeleton } from '../components/feedback/Skeletons'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'

const DRAWER_WIDTH = 260

export default function AppLayout() {
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('lg'))
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout, can } = useAuth()
  const { resolvedMode, toggleMode } = useUi()

  const [mobileOpen, setMobileOpen] = useState(false)
  const [menuAnchor, setMenuAnchor] = useState(null)

  const handleLogout = async () => {
    setMenuAnchor(null)
    await logout()
    navigate('/login', { replace: true })
  }

  // Menyu ustiga sichqoncha kelganda sahifa kodini oldindan yuklaymiz.
  // Bosilganda chunk allaqachon keshda bo'ladi — o'tish deyarli darhol.
  const handlePrefetch = useCallback((path) => prefetchRoute(path), [])

  const visibleGroups = useMemo(
    () =>
      NAVIGATION.map((group) => ({
        ...group,
        items: group.items.filter((item) => can(item.permission)),
      })).filter((group) => group.items.length > 0),
    [can],
  )

  const drawerContent = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Toolbar sx={{ gap: 1.5, px: 2.5 }}>
        <Box
          sx={{
            width: 34, height: 34, borderRadius: 2, display: 'grid', placeItems: 'center',
            bgcolor: 'primary.main', color: 'primary.contrastText', flexShrink: 0,
          }}
        >
          <ShieldIcon sx={{ fontSize: 20 }} />
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" sx={{ lineHeight: 1.2 }} noWrap>Proctoring</Typography>
          <Typography variant="caption" color="text.secondary" noWrap>Boshqaruv paneli</Typography>
        </Box>
      </Toolbar>
      <Divider />

      <Box sx={{ flex: 1, overflowY: 'auto', py: 1 }}>
        {visibleGroups.map((group) => (
          <List
            key={group.section}
            dense
            subheader={
              <ListSubheader
                disableSticky
                sx={{
                  bgcolor: 'transparent', fontSize: 10.5, fontWeight: 700,
                  letterSpacing: '0.1em', lineHeight: 2.6, color: 'text.disabled',
                }}
              >
                {group.section.toUpperCase()}
              </ListSubheader>
            }
          >
            {group.items.map((item) => {
              const Icon = item.icon
              const active =
                item.path === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.path)

              return (
                <ListItemButton
                  key={item.path}
                  component={Link}
                  to={item.path}
                  selected={active}
                  onMouseEnter={() => handlePrefetch(item.path)}
                  onFocus={() => handlePrefetch(item.path)}
                  onClick={() => !isDesktop && setMobileOpen(false)}
                  sx={{
                    mx: 1.25, mb: 0.25, pl: 1.75,
                    position: 'relative',
                    '&.Mui-selected': {
                      bgcolor: (t) => alpha(t.palette.primary.main, t.palette.mode === 'light' ? 0.12 : 0.2),
                      color: 'primary.main',
                      '& .MuiListItemIcon-root': { color: 'primary.main' },
                      '&:hover': {
                        bgcolor: (t) => alpha(t.palette.primary.main, t.palette.mode === 'light' ? 0.16 : 0.26),
                      },
                      // Chap chetdagi indikator — tanlangan bo'lim
                      // periferik ko'rish bilan ham sezilib turadi.
                      '&::before': {
                        content: '""',
                        position: 'absolute',
                        left: 0, top: 8, bottom: 8,
                        width: 3, borderRadius: '0 3px 3px 0',
                        bgcolor: 'primary.main',
                      },
                    },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 36 }}>
                    <Icon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText
                    primary={item.label}
                    primaryTypographyProps={{ fontSize: 13.5, fontWeight: active ? 650 : 500 }}
                  />
                </ListItemButton>
              )
            })}
          </List>
        ))}
      </Box>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        elevation={0}
        color="inherit"
        sx={{
          zIndex: theme.zIndex.drawer + 1,
          borderBottom: `1px solid ${theme.palette.divider}`,
          bgcolor: 'background.paper',
        }}
      >
        <Toolbar sx={{ gap: 0.5 }}>
          {!isDesktop && (
            <IconButton edge="start" onClick={() => setMobileOpen((prev) => !prev)}>
              <MenuIcon />
            </IconButton>
          )}

          <Box sx={{ flex: 1 }} />

          {user?.region_name && (
            <Chip size="small" variant="outlined" label={user.region_name} sx={{ mr: 1 }} />
          )}

          <Tooltip title={resolvedMode === 'light' ? 'Tungi rejim' : 'Kunduzgi rejim'}>
            <IconButton onClick={toggleMode}>
              {resolvedMode === 'light' ? <DarkModeIcon /> : <LightModeIcon />}
            </IconButton>
          </Tooltip>

          <Tooltip title={user?.full_name || 'Profil'}>
            <IconButton onClick={(event) => setMenuAnchor(event.currentTarget)} sx={{ ml: 0.5 }}>
              <Avatar sx={{ width: 33, height: 33, bgcolor: 'primary.main', fontSize: 14 }}>
                {(user?.full_name || user?.username || '?').charAt(0).toUpperCase()}
              </Avatar>
            </IconButton>
          </Tooltip>

          <Menu
            anchorEl={menuAnchor}
            open={Boolean(menuAnchor)}
            onClose={() => setMenuAnchor(null)}
            slotProps={{ paper: { sx: { minWidth: 240, mt: 1 } } }}
          >
            <Box sx={{ px: 2, py: 1.5 }}>
              <Typography variant="subtitle2" noWrap>{user?.full_name}</Typography>
              <Typography variant="caption" color="text.secondary">
                {user?.role_name || 'Rol biriktirilmagan'}
              </Typography>
            </Box>
            <Divider />
            <MenuItem
              onClick={() => { setMenuAnchor(null); navigate('/profile') }}
              onMouseEnter={() => handlePrefetch('/profile')}
            >
              <ListItemIcon><SettingsIcon fontSize="small" /></ListItemIcon>
              Profil va tema
            </MenuItem>
            <Divider />
            <MenuItem onClick={handleLogout}>
              <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
              Chiqish
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      <Box component="nav" sx={{ width: { lg: DRAWER_WIDTH }, flexShrink: { lg: 0 } }}>
        <Drawer
          variant={isDesktop ? 'permanent' : 'temporary'}
          open={isDesktop || mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              boxSizing: 'border-box',
              borderRight: `1px solid ${theme.palette.divider}`,
              bgcolor: 'background.paper',
            },
          }}
        >
          {drawerContent}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: { lg: `calc(100% - ${DRAWER_WIDTH}px)` },
          bgcolor: 'background.default',
          minHeight: '100vh',
        }}
      >
        <Toolbar />
        <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1720, mx: 'auto' }}>
          <Suspense fallback={<PageSkeleton />}>
            <PageTransition>
              <Outlet />
            </PageTransition>
          </Suspense>
        </Box>
      </Box>
    </Box>
  )
}
