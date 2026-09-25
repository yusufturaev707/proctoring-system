import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  AppBar, Avatar, Box, ButtonBase, Divider, Drawer, IconButton, ListItemIcon, Menu,
  MenuItem, Stack, Switch, Toolbar, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import MenuIcon from '@mui/icons-material/MenuRounded'
import MenuOpenIcon from '@mui/icons-material/MenuOpenRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import DarkModeIcon from '@mui/icons-material/DarkModeOutlined'
import LogoutIcon from '@mui/icons-material/LogoutRounded'
import PersonIcon from '@mui/icons-material/ManageAccountsOutlined'
import UnfoldIcon from '@mui/icons-material/UnfoldMoreRounded'
import ShieldIcon from '@mui/icons-material/GppGoodOutlined'

import { NAVIGATION, findNavEntry, prefetchRoute } from './navigation'
import CommandPalette, { Kbd } from './CommandPalette'
import { PageTransition } from '../components/motion/Transitions'
import { PageSkeleton } from '../components/feedback/Skeletons'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'

/**
 * Ilova qobig'i: yon panel + kontent. YUQORI SARLAVHA (AppBar) YO'Q.
 *
 * Ilgari 64 px li sarlavha butun kenglik bo'ylab turardi va unda faqat
 * uch narsa bor edi: viloyat nomi, tema tugmasi va avatar. Ya'ni har bir
 * sahifada ~7% balandlik (1366x768 ekranda) deyarli bo'sh chiziqqa
 * ketardi — aynan jonli kuzatuv va jadvallar, ya'ni vertikal joy eng
 * qimmat bo'lgan sahifalarda. Uchalasi ham yon panelning pastidagi
 * foydalanuvchi kartasiga ko'chdi (Material 3 navigation drawer
 * naqshi): ular kamdan-kam ishlatiladi va doim ko'rinib turishi shart
 * emas.
 *
 * UCH REJIM, ekran kengligiga qarab:
 *
 *   >= lg (1200)  to'liq panel yoki yig'ilgan (rail) — foydalanuvchi
 *                 tanlaydi, tanlov saqlanadi;
 *   md..lg        doim rail: 900–1200 px da 272 px li panel jadvalni
 *                 siqib qo'yardi;
 *   < md          panel yashirin, tepada ixcham satr (56 px) — telefon
 *                 yoki planshetda menyuni ochishning boshqa yo'li yo'q.
 */
export default function AppLayout() {
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('lg'))
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const { can } = useAuth()
  const { sidebarCollapsed, setPreference } = useUi()

  const [mobileOpen, setMobileOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)

  const rail = !isMobile && (!isDesktop || sidebarCollapsed)
  const width = rail ? theme.sidebar.rail : theme.sidebar.expanded

  // Ctrl+K / Cmd+K — tezkor o'tish. Matn maydonida ham ishlaydi: bu
  // kombinatsiya brauzerda matn tahririga bog'lanmagan.
  useEffect(() => {
    const handler = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const visibleGroups = useMemo(
    () =>
      NAVIGATION.map((group) => ({
        ...group,
        items: group.items.filter((item) => can(item.permission)),
      })).filter((group) => group.items.length > 0),
    [can],
  )

  const sidebar = (
    <SidebarContent
      groups={visibleGroups}
      rail={rail}
      canToggle={isDesktop}
      onToggleRail={() => setPreference('sidebarCollapsed', !sidebarCollapsed)}
      onNavigate={() => isMobile && setMobileOpen(false)}
      onOpenSearch={() => { setMobileOpen(false); setPaletteOpen(true) }}
    />
  )

  const paperSx = {
    width,
    boxSizing: 'border-box',
    border: 0,
    bgcolor: 'm3.surfaceContainerLow',
    overflowX: 'hidden',
    transition: theme.transitions.create('width', { duration: theme.motion.base }),
  }

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      {isMobile && (
        <MobileBar onMenu={() => setMobileOpen(true)} onSearch={() => setPaletteOpen(true)} />
      )}

      {isMobile ? (
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          PaperProps={{ sx: { ...paperSx, width: theme.sidebar.expanded, borderRadius: '0 16px 16px 0' } }}
        >
          {sidebar}
        </Drawer>
      ) : (
        <Box
          component="nav"
          sx={{
            width, flexShrink: 0,
            transition: theme.transitions.create('width', { duration: theme.motion.base }),
          }}
        >
          <Drawer variant="permanent" open PaperProps={{ sx: paperSx }}>
            {sidebar}
          </Drawer>
        </Box>
      )}

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          // `minWidth: 0` — flex bolasi sifatida DataGrid kengligini
          // o'zi hisoblashi uchun; usiz keng jadval butun sahifani
          // gorizontal suradi.
          minWidth: 0,
          minHeight: '100vh',
          pt: { xs: 9, md: 3.5 },
          pb: { xs: 3, md: 4 },
          px: { xs: 2, sm: 3, lg: 4 },
        }}
      >
        <Box sx={{ maxWidth: 1680, mx: 'auto' }}>
          <Suspense fallback={<PageSkeleton />}>
            <PageTransition>
              <Outlet />
            </PageTransition>
          </Suspense>
        </Box>
      </Box>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} can={can} />
    </Box>
  )
}

// --------------------------------------------------------------------------
// Yon panel
// --------------------------------------------------------------------------
function SidebarContent({ groups, rail, canToggle, onToggleRail, onNavigate, onOpenSearch }) {
  const location = useLocation()
  const scrollRef = useRef(null)
  const activePath = findNavEntry(location.pathname)?.item.path

  // Faol band ko'rinishda bo'lishi kerak: "Audit jurnali" menyuning eng
  // pastida va sahifa yangilanganda panel tepadan boshlanardi —
  // foydalanuvchi o'zi qayerdaligini ko'rmasdi.
  useEffect(() => {
    scrollRef.current
      ?.querySelector('[aria-current="page"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [activePath, rail])

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Brand rail={rail} canToggle={canToggle} onToggleRail={onToggleRail} />

      <Box sx={{ px: rail ? 1.5 : 2, pb: 1 }}>
        <SearchTrigger rail={rail} onClick={onOpenSearch} />
      </Box>

      <Box
        ref={scrollRef}
        sx={{
          flex: 1, overflowY: 'auto', overflowX: 'hidden', px: rail ? 1.5 : 1.5, pb: 2,
          // Ingichka skroll — panel tor, 11 px li standart skroll
          // uning ~5% ini egallardi.
          '&::-webkit-scrollbar': { width: 6 },
        }}
      >
        {groups.map((group, index) => (
          <Box key={group.section} component="section" aria-label={group.section}>
            {rail ? (
              index > 0 && <Divider sx={{ mx: 1.5, my: 1 }} />
            ) : (
              <Typography
                component="h2"
                sx={{
                  px: 2, pt: index === 0 ? 0.75 : 1.75, pb: 0.5,
                  fontSize: 12, fontWeight: 650, color: 'text.secondary', letterSpacing: '0.01em',
                }}
              >
                {group.section}
              </Typography>
            )}
            {group.items.map((item) => (
              <NavItem
                key={item.path}
                item={item}
                rail={rail}
                active={activePath === item.path}
                onNavigate={onNavigate}
              />
            ))}
          </Box>
        ))}
      </Box>

      <Box sx={{ p: rail ? 1.5 : 1.5, pt: 1 }}>
        <UserCard rail={rail} onNavigate={onNavigate} />
      </Box>
    </Box>
  )
}

/**
 * Logotip va yig'ish tugmasi. Tema tugmasi bu yerda YO'Q — u
 * foydalanuvchi menyusida: brend qatorida ikkita tugma nomni
 * "Imtihon nazor…" gacha qisqartirardi.
 */
function Brand({ rail, canToggle, onToggleRail }) {
  const logo = (
    <Box
      sx={{
        width: 40, height: 40, borderRadius: '12px', display: 'grid', placeItems: 'center', flexShrink: 0,
        bgcolor: 'primary.main', color: 'primary.contrastText',
      }}
    >
      <ShieldIcon sx={{ fontSize: 22 }} />
    </Box>
  )

  const toggle = canToggle && (
    <Tooltip title={rail ? 'Menyuni yoyish' : 'Menyuni yig‘ish'} placement="right">
      <IconButton onClick={onToggleRail} size="small" aria-label={rail ? 'Menyuni yoyish' : 'Menyuni yig‘ish'}>
        {rail ? <MenuIcon fontSize="small" /> : <MenuOpenIcon fontSize="small" />}
      </IconButton>
    </Tooltip>
  )

  if (rail) {
    return (
      <Stack alignItems="center" spacing={1} sx={{ pt: 2, pb: 1.5 }}>
        {logo}
        {toggle}
      </Stack>
    )
  }

  return (
    <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 2.5, pt: 2.25, pb: 1.75 }}>
      {logo}
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography sx={{ fontWeight: 700, fontSize: 15.5, lineHeight: 1.2, letterSpacing: '-0.01em' }} noWrap>
          Proctoring
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap display="block">
          Imtihon nazorati tizimi
        </Typography>
      </Box>
      {toggle}
    </Stack>
  )
}

function SearchTrigger({ rail, onClick }) {
  if (rail) {
    return (
      <Tooltip title="Sahifa qidirish (Ctrl+K)" placement="right">
        <IconButton
          onClick={onClick}
          aria-label="Sahifa qidirish"
          sx={{ width: '100%', height: 40, borderRadius: 999, bgcolor: 'm3.surfaceContainerHigh' }}
        >
          <SearchIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    )
  }
  return (
    <ButtonBase
      onClick={onClick}
      aria-label="Sahifa qidirish"
      sx={{
        width: '100%', height: 42, px: 1.75, borderRadius: 999, justifyContent: 'flex-start', gap: 1.25,
        bgcolor: 'm3.surfaceContainerHigh', color: 'text.secondary',
        transition: (t) => t.transitions.create('background-color', { duration: t.motion.fast }),
        '&:hover': { bgcolor: 'm3.surfaceContainerHighest' },
      }}
    >
      <SearchIcon fontSize="small" />
      <Typography variant="body2" sx={{ flex: 1, textAlign: 'left' }}>Sahifa qidirish</Typography>
      <Kbd>Ctrl K</Kbd>
    </ButtonBase>
  )
}

/**
 * Menyu bandi — Material 3 navigation drawer / rail.
 *
 * Faol band — to'liq kapsula `secondaryContainer` rangida (M3 "active
 * indicator"). Ilgari chap chetdagi 3 px chiziq edi: u keng panelda
 * ko'rinardi, lekin rail'da ikonka ustida ma'nosiz bo'lib qolardi.
 *
 * Rail'da nom YO'Q, shuning uchun tooltip nomni ham, VAZIFANI ham
 * aytadi: ikonka o'zi "kalit" nima ekanini tushuntirmaydi.
 */
function NavItem({ item, rail, active, onNavigate }) {
  const Icon = item.icon

  const common = {
    component: Link,
    to: item.path,
    'aria-current': active ? 'page' : undefined,
    onMouseEnter: () => prefetchRoute(item.path),
    onFocus: () => prefetchRoute(item.path),
    onClick: onNavigate,
  }

  if (rail) {
    return (
      <Tooltip
        placement="right"
        title={
          <Box>
            <Typography sx={{ fontSize: 13, fontWeight: 650 }}>{item.label}</Typography>
            <Typography sx={{ fontSize: 12, opacity: 0.85 }}>{item.description}</Typography>
          </Box>
        }
      >
        <ButtonBase
          {...common}
          aria-label={item.label}
          sx={{
            width: '100%', height: 40, mb: 0.5, borderRadius: 999,
            color: active ? 'm3.onSecondaryContainer' : 'text.secondary',
            bgcolor: active ? 'm3.secondaryContainer' : 'transparent',
            transition: (t) => t.transitions.create(['background-color', 'color'], { duration: t.motion.fast }),
            '&:hover': { bgcolor: active ? 'm3.secondaryContainer' : 'action.hover', color: 'text.primary' },
          }}
        >
          <Icon sx={{ fontSize: 22 }} />
        </ButtonBase>
      </Tooltip>
    )
  }

  return (
    <ButtonBase
      {...common}
      sx={{
        // 38 px — M3 dagi 56 px emas: menyuda 26 ta band bor va 56 px
        // bilan ularning yarmi 900 px li ekranga sig'masdi.
        width: '100%', minHeight: 38, px: 2, mb: 0.25, borderRadius: 999,
        justifyContent: 'flex-start', gap: 1.5, textAlign: 'left',
        color: active ? 'm3.onSecondaryContainer' : 'text.secondary',
        bgcolor: active ? 'm3.secondaryContainer' : 'transparent',
        transition: (t) => t.transitions.create(['background-color', 'color'], { duration: t.motion.fast }),
        '&:hover': { bgcolor: active ? 'm3.secondaryContainer' : 'action.hover', color: 'text.primary' },
      }}
    >
      <Icon sx={{ fontSize: 20, flexShrink: 0 }} />
      <Typography
        noWrap
        sx={{ fontSize: 13.5, fontWeight: active ? 650 : 500, color: active ? 'inherit' : 'text.primary' }}
      >
        {item.label}
      </Typography>
    </ButtonBase>
  )
}

/**
 * Foydalanuvchi kartasi — yon panel PASTIDA.
 *
 * Karta kim ekanini doim ko'rsatib turadi (ism, rol, viloyat) — ilgari
 * viloyat sarlavhadagi alohida chip edi, rol esa faqat menyu ochilganda
 * ko'rinardi. Viloyat doirasi har bir ro'yxatni cheklaydi, ya'ni
 * "nega bu binoni ko'rmayapman?" degan savolning javobi shu yerda.
 */
function UserCard({ rail, onNavigate }) {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { resolvedMode, toggleMode } = useUi()
  const [anchor, setAnchor] = useState(null)

  const name = user?.full_name || user?.username || '—'
  const initial = name.charAt(0).toUpperCase()
  const scope = user?.region_name || 'Barcha viloyatlar'
  const role = user?.is_superuser ? 'Superadmin' : user?.role_name || 'Rol biriktirilmagan'

  const handleLogout = useCallback(async () => {
    setAnchor(null)
    await logout()
    navigate('/login', { replace: true })
  }, [logout, navigate])

  const avatar = (
    <Avatar sx={{ width: 36, height: 36, fontSize: 15, bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer' }}>
      {initial}
    </Avatar>
  )

  return (
    <>
      {rail ? (
        <Tooltip title={`${name} · ${role}`} placement="right">
          <IconButton onClick={(event) => setAnchor(event.currentTarget)} sx={{ mx: 'auto', display: 'flex' }} aria-label="Hisob menyusi">
            {avatar}
          </IconButton>
        </Tooltip>
      ) : (
        <ButtonBase
          onClick={(event) => setAnchor(event.currentTarget)}
          aria-label="Hisob menyusi"
          sx={{
            width: '100%', p: 1, pr: 1.25, gap: 1.25, borderRadius: '16px', justifyContent: 'flex-start',
            textAlign: 'left', bgcolor: 'm3.surfaceContainer',
            transition: (t) => t.transitions.create('background-color', { duration: t.motion.fast }),
            '&:hover': { bgcolor: 'm3.surfaceContainerHigh' },
          }}
        >
          {avatar}
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography noWrap sx={{ fontSize: 13.5, fontWeight: 650, lineHeight: 1.3 }}>{name}</Typography>
            <Typography noWrap variant="caption" color="text.secondary" display="block">
              {role} · {scope}
            </Typography>
          </Box>
          <UnfoldIcon sx={{ fontSize: 18, color: 'text.secondary' }} />
        </ButtonBase>
      )}

      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: rail ? 'right' : 'left' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        slotProps={{ paper: { sx: { width: 256, mt: -1, ml: rail ? 1 : 0 } } }}
      >
        <Box sx={{ px: 1.5, pt: 1, pb: 1.25 }}>
          <Typography variant="subtitle2" noWrap>{name}</Typography>
          <Typography variant="caption" color="text.secondary" noWrap display="block">
            @{user?.username} · {role}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap display="block">
            Ko‘rish doirasi: {scope}
          </Typography>
        </Box>
        <Divider sx={{ my: 0.5 }} />
        <MenuItem
          onClick={() => { setAnchor(null); onNavigate?.(); navigate('/profile') }}
          onMouseEnter={() => prefetchRoute('/profile')}
        >
          <ListItemIcon><PersonIcon fontSize="small" /></ListItemIcon>
          Profil va sozlamalar
        </MenuItem>
        <MenuItem onClick={toggleMode}>
          <ListItemIcon><DarkModeIcon fontSize="small" /></ListItemIcon>
          <Box sx={{ flex: 1 }}>Tungi rejim</Box>
          <Switch size="small" edge="end" checked={resolvedMode === 'dark'} tabIndex={-1} />
        </MenuItem>
        <Divider sx={{ my: 0.5 }} />
        <MenuItem onClick={handleLogout} sx={{ color: 'error.main' }}>
          <ListItemIcon sx={{ color: 'inherit' }}><LogoutIcon fontSize="small" /></ListItemIcon>
          Tizimdan chiqish
        </MenuItem>
      </Menu>
    </>
  )
}

/** Faqat tor ekran (< md): menyu tugmasi va qidiruv. */
function MobileBar({ onMenu, onSearch }) {
  return (
    <AppBar
      position="fixed"
      elevation={0}
      color="inherit"
      sx={{ bgcolor: 'm3.surfaceContainerLow', borderBottom: 1, borderColor: 'divider' }}
    >
      <Toolbar sx={{ minHeight: '56px !important', gap: 1 }}>
        <IconButton edge="start" onClick={onMenu} aria-label="Menyuni ochish">
          <MenuIcon />
        </IconButton>
        <Typography sx={{ fontWeight: 700, flex: 1 }} noWrap>Proctoring</Typography>
        <IconButton onClick={onSearch} aria-label="Sahifa qidirish">
          <SearchIcon />
        </IconButton>
      </Toolbar>
    </AppBar>
  )
}
