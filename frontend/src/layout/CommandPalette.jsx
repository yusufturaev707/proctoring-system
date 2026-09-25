import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Dialog, InputAdornment, InputBase, List, ListItemButton, ListItemIcon,
  ListItemText, ListSubheader, Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/SearchRounded'
import PersonIcon from '@mui/icons-material/PersonOutline'
import KeyboardReturnIcon from '@mui/icons-material/KeyboardReturnRounded'

import { NAVIGATION, PROFILE_ITEM, prefetchRoute } from './navigation'

/**
 * Tezkor o'tish oynasi (Ctrl+K).
 *
 * Menyuda 26 ta sahifa va ular 6 bo'limga bo'lingan — "chiqish paroli
 * qayerda edi?" degan savolga bo'limlarni birma-bir ochib javob
 * izlash kerak bo'lmasligi uchun. Qidiruv NOMDA ham, TAVSIFDA ham
 * ishlaydi: administrator ko'pincha sahifa nomini emas, vazifasini
 * eslaydi ("MAC", "parol", "telefon").
 *
 * Harflar registri va o'zbekcha tutuq belgilari (‘ ’ ') farqlanmaydi:
 * "og'irlik" va "og‘irlik" bir xil topilishi kerak.
 */
const normalize = (value) =>
  value.toLowerCase().replace(/[‘’`ʻʼ']/g, "'").normalize('NFKD')

export default function CommandPalette({ open, onClose, can }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listRef = useRef(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
    }
  }, [open])

  const entries = useMemo(() => {
    const all = [
      ...NAVIGATION.flatMap((group) =>
        group.items.map((item) => ({ ...item, section: group.section })),
      ),
      { ...PROFILE_ITEM, icon: PersonIcon, section: 'Hisob' },
    ].filter((item) => !item.permission || can(item.permission))

    const needle = normalize(query.trim())
    if (!needle) return all
    return all.filter((item) =>
      normalize(`${item.label} ${item.description} ${item.section}`).includes(needle),
    )
  }, [query, can])

  // Faol band ko'rinish chegarasida qolishi kerak — klaviatura bilan
  // pastga yurganda tanlov ro'yxatdan "chiqib ketmasin".
  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const go = (item) => {
    if (!item) return
    onClose()
    navigate(item.path)
  }

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((prev) => Math.min(prev + 1, entries.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((prev) => Math.max(prev - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      go(entries[active])
    }
  }

  // Bo'lim sarlavhasi faqat bo'lim o'zgarganda chiziladi.
  let lastSection = null

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      // Oyna ekranning YUQORI qismida: markazda tursa, natijalar
      // qisqarganda u "sakraydi" va ko'z ro'yxatni qaytadan izlaydi.
      sx={{ '& .MuiDialog-container': { alignItems: 'flex-start' } }}
      PaperProps={{ sx: { mt: { xs: 2, sm: '12vh' }, borderRadius: '24px', overflow: 'hidden' } }}
    >
      <InputBase
        autoFocus
        fullWidth
        value={query}
        placeholder="Sahifa yoki vazifa nomini yozing…"
        onChange={(event) => { setQuery(event.target.value); setActive(0) }}
        onKeyDown={handleKeyDown}
        startAdornment={
          <InputAdornment position="start">
            <SearchIcon color="action" />
          </InputAdornment>
        }
        inputProps={{ 'aria-label': 'Menyu bo‘yicha qidirish' }}
        sx={{
          px: 2.5, py: 1.75, fontSize: '1.05rem',
          borderBottom: 1, borderColor: 'divider',
        }}
      />

      <List ref={listRef} dense sx={{ maxHeight: '55vh', overflowY: 'auto', py: 1, px: 1 }}>
        {entries.length === 0 && (
          <Box sx={{ py: 5, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              «{query}» bo‘yicha sahifa topilmadi
            </Typography>
          </Box>
        )}

        {entries.map((item, index) => {
          const Icon = item.icon
          const header = item.section !== lastSection
          lastSection = item.section
          return (
            <Box key={item.path}>
              {header && (
                <ListSubheader
                  disableSticky
                  sx={{
                    bgcolor: 'transparent', lineHeight: 2.4, fontSize: 12,
                    fontWeight: 650, color: 'text.secondary', px: 1.5,
                  }}
                >
                  {item.section}
                </ListSubheader>
              )}
              <ListItemButton
                data-index={index}
                selected={index === active}
                onMouseEnter={() => { setActive(index); prefetchRoute(item.path) }}
                onClick={() => go(item)}
                sx={{
                  borderRadius: '12px', py: 0.9, px: 1.5, mb: 0.25,
                  '&.Mui-selected, &.Mui-selected:hover': { bgcolor: 'm3.secondaryContainer' },
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>
                  <Box
                    sx={{
                      width: 30, height: 30, borderRadius: '8px', display: 'grid', placeItems: 'center',
                      bgcolor: index === active ? 'background.paper' : 'm3.surfaceContainer',
                      color: 'm3.onSecondaryContainer',
                    }}
                  >
                    <Icon sx={{ fontSize: 18 }} />
                  </Box>
                </ListItemIcon>
                <ListItemText
                  primary={item.label}
                  secondary={item.description}
                  primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }}
                  secondaryTypographyProps={{ noWrap: true, fontSize: 12.5 }}
                />
                {index === active && (
                  <KeyboardReturnIcon sx={{ fontSize: 18, color: 'text.secondary', ml: 1 }} />
                )}
              </ListItemButton>
            </Box>
          )
        })}
      </List>

      <Box
        sx={{
          px: 2.5, py: 1, borderTop: 1, borderColor: 'divider',
          display: 'flex', gap: 2, color: 'text.secondary', bgcolor: 'm3.surfaceContainerLow',
        }}
      >
        <Hint keys="↑ ↓" label="tanlash" />
        <Hint keys="Enter" label="ochish" />
        <Hint keys="Esc" label="yopish" />
      </Box>
    </Dialog>
  )
}

export function Kbd({ children }) {
  return (
    <Box
      component="kbd"
      sx={{
        fontFamily: 'inherit', fontSize: 11, fontWeight: 600, lineHeight: 1,
        px: 0.75, py: 0.4, borderRadius: '6px', border: 1, borderColor: 'divider',
        bgcolor: 'background.paper', color: 'text.secondary',
      }}
    >
      {children}
    </Box>
  )
}

function Hint({ keys, label }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
      <Kbd>{keys}</Kbd>
      <Typography variant="caption">{label}</Typography>
    </Box>
  )
}
