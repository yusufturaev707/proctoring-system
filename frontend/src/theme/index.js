import { alpha, createTheme } from '@mui/material/styles'
import { CHART_COLORS, DEFAULT_PALETTE, PALETTES, RISK_SCALE } from './palettes'

export { PALETTES, PALETTE_KEYS, DEFAULT_PALETTE, CHART_COLORS, RISK_SCALE } from './palettes'

/**
 * Harakat (motion) tokenlari.
 *
 * Qisqa davomiylik ataylab: admin paneli — ish quroli, animatsiya
 * "chiroyli" emas, "sezilmaydigan" bo'lishi kerak. 150–220 ms oralig'i
 * silliqlik hissini beradi, lekin kutish hosil qilmaydi.
 */
export const MOTION = {
  fast: 140,
  base: 190,
  slow: 260,
  easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
}

/** Zichlik rejimlari — foydalanuvchi profilda tanlaydi. */
export const DENSITY = {
  comfortable: { spacing: 8, rowHeight: 46, fontScale: 1 },
  compact: { spacing: 7, rowHeight: 38, fontScale: 0.94 },
}

export function createAppTheme({
  palette: paletteKey = DEFAULT_PALETTE,
  mode = 'light',
  density = 'comfortable',
} = {}) {
  const variant = PALETTES[paletteKey] || PALETTES[DEFAULT_PALETTE]
  const colors = variant[mode] || variant.light
  const densityConfig = DENSITY[density] || DENSITY.comfortable
  const isLight = mode === 'light'

  const theme = createTheme({
    palette: {
      mode,
      primary: colors.primary,
      secondary: colors.secondary,
      error: colors.error,
      warning: colors.warning,
      info: colors.info,
      success: colors.success,
      background: colors.background,
      divider: colors.divider,
      text: colors.text,
      // MUI standartida yo'q, lekin bizga kerak — `theme.palette.surface`
      surface: colors.surface,
      action: {
        hover: alpha(colors.primary.main, isLight ? 0.06 : 0.1),
        selected: alpha(colors.primary.main, isLight ? 0.1 : 0.16),
        focus: alpha(colors.primary.main, 0.2),
      },
    },

    shape: { borderRadius: 12 },
    spacing: densityConfig.spacing,

    typography: {
      fontFamily: '"Inter", "Roboto", "Segoe UI", system-ui, -apple-system, sans-serif',
      // `-0.01em` — katta sarlavhalarda harflar orasidagi bo'shliqni
      // qisqartiradi, matn "yig'ilgan" va o'qishga qulay ko'rinadi.
      h4: { fontWeight: 700, letterSpacing: '-0.02em', fontSize: `${1.9 * densityConfig.fontScale}rem` },
      h5: { fontWeight: 700, letterSpacing: '-0.015em', fontSize: `${1.45 * densityConfig.fontScale}rem` },
      h6: { fontWeight: 650, letterSpacing: '-0.01em', fontSize: `${1.15 * densityConfig.fontScale}rem` },
      subtitle1: { fontWeight: 600 },
      subtitle2: { fontWeight: 600, fontSize: `${0.86 * densityConfig.fontScale}rem` },
      body1: { fontSize: `${0.94 * densityConfig.fontScale}rem` },
      body2: { fontSize: `${0.86 * densityConfig.fontScale}rem` },
      caption: { fontSize: `${0.76 * densityConfig.fontScale}rem`, letterSpacing: '0.01em' },
      button: { textTransform: 'none', fontWeight: 600, letterSpacing: 0 },
      overline: { fontWeight: 700, letterSpacing: '0.09em', fontSize: '0.68rem' },
    },

    // Soyalar yumshoq va past kontrastli — Material 3 ruhida "elevation"
    // asosan rang va chegara bilan beriladi, soya bilan emas.
    shadows: buildShadows(isLight),

    transitions: {
      duration: {
        shortest: 100, shorter: MOTION.fast, short: MOTION.base,
        standard: MOTION.base, complex: MOTION.slow,
        enteringScreen: MOTION.base, leavingScreen: MOTION.fast,
      },
      easing: { easeInOut: MOTION.easing, easeOut: MOTION.easing, easeIn: MOTION.easing },
    },

    components: {
      MuiCssBaseline: {
        styleOverrides: {
          html: { WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale' },
          body: { backgroundColor: colors.background.default },
          '*::-webkit-scrollbar': { width: 11, height: 11 },
          '*::-webkit-scrollbar-track': { background: 'transparent' },
          '*::-webkit-scrollbar-thumb': {
            borderRadius: 8,
            border: '3px solid transparent',
            backgroundClip: 'content-box',
            backgroundColor: alpha(colors.text.secondary, 0.3),
          },
          '*::-webkit-scrollbar-thumb:hover': {
            backgroundColor: alpha(colors.text.secondary, 0.5),
          },
          // Klaviatura bilan yuruvchi foydalanuvchi uchun aniq fokus halqasi.
          ':focus-visible': {
            outline: `2px solid ${colors.primary.main}`,
            outlineOffset: 2,
          },
          // Harakatni kamaytirish so'ralgan bo'lsa — hurmat qilamiz.
          '@media (prefers-reduced-motion: reduce)': {
            '*': { animationDuration: '0.01ms !important', transitionDuration: '0.01ms !important' },
          },
        },
      },

      MuiPaper: {
        styleOverrides: { root: { backgroundImage: 'none' } },
      },

      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            border: `1px solid ${colors.divider}`,
            backgroundColor: colors.surface.raised,
            transition: `border-color ${MOTION.fast}ms ${MOTION.easing}, box-shadow ${MOTION.fast}ms ${MOTION.easing}`,
          },
        },
      },

      MuiCardHeader: {
        styleOverrides: {
          root: { paddingBottom: 8 },
          title: { fontSize: '1.05rem', fontWeight: 650 },
          subheader: { fontSize: '0.82rem' },
        },
      },

      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            borderRadius: 10,
            paddingInline: 16,
            transition: `background-color ${MOTION.fast}ms ${MOTION.easing}, transform ${MOTION.fast}ms ${MOTION.easing}`,
            '&:active': { transform: 'scale(0.985)' },
          },
          containedPrimary: {
            '&:hover': { backgroundColor: colors.primary.dark },
          },
        },
      },

      MuiIconButton: {
        styleOverrides: {
          root: { transition: `background-color ${MOTION.fast}ms ${MOTION.easing}` },
        },
      },

      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 600, borderRadius: 8 },
          sizeSmall: { height: 23, fontSize: '0.74rem' },
          outlined: { borderWidth: 1.5 },
        },
      },

      MuiTextField: { defaultProps: { size: 'small', fullWidth: true } },
      MuiSelect: { defaultProps: { size: 'small' } },

      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            backgroundColor: colors.surface.raised,
            '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: colors.primary.light },
          },
        },
      },

      MuiTableCell: {
        styleOverrides: {
          root: { borderColor: colors.divider },
          head: {
            fontWeight: 700,
            whiteSpace: 'nowrap',
            backgroundColor: colors.surface.subtle,
            color: colors.text.secondary,
            fontSize: '0.78rem',
            letterSpacing: '0.02em',
            textTransform: 'uppercase',
          },
        },
      },

      MuiTooltip: {
        defaultProps: { arrow: true, enterDelay: 400, enterNextDelay: 200 },
        styleOverrides: {
          tooltip: { fontSize: '0.78rem', paddingBlock: 6, paddingInline: 10, borderRadius: 8 },
        },
      },

      MuiTabs: {
        styleOverrides: {
          root: { minHeight: 46 },
          indicator: { height: 3, borderRadius: '3px 3px 0 0' },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: { minHeight: 46, fontWeight: 600, textTransform: 'none' },
        },
      },

      MuiLinearProgress: {
        styleOverrides: {
          root: { borderRadius: 999, backgroundColor: alpha(colors.text.secondary, 0.14) },
          bar: { borderRadius: 999 },
        },
      },

      MuiSkeleton: {
        defaultProps: { animation: 'wave' },
        styleOverrides: {
          root: { backgroundColor: alpha(colors.text.secondary, isLight ? 0.1 : 0.14) },
        },
      },

      MuiAlert: {
        styleOverrides: {
          root: { borderRadius: 10, alignItems: 'center' },
          standardInfo: { backgroundColor: alpha(colors.info.main, 0.1) },
          standardWarning: { backgroundColor: alpha(colors.warning.main, 0.12) },
          standardError: { backgroundColor: alpha(colors.error.main, 0.1) },
          standardSuccess: { backgroundColor: alpha(colors.success.main, 0.1) },
        },
      },

      MuiDialog: {
        styleOverrides: {
          paper: { borderRadius: 16, backgroundImage: 'none' },
        },
      },

      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            transition: `background-color ${MOTION.fast}ms ${MOTION.easing}, color ${MOTION.fast}ms ${MOTION.easing}`,
          },
        },
      },

      // --- Segmentli boshqaruv (holat bo'yicha ko'rinishni almashtirish) ---
      //
      // Material 3 da bu element "segmented button": yaxlit kapsula,
      // tanlangan segment past to'yinganlikdagi primary bilan bo'yaladi.
      // MUI standarti to'rtburchak va deyarli ko'rinmaydigan tanlov beradi
      // — sahifa sarlavhasida u tugma emas, matn bo'lib qoladi.
      MuiToggleButtonGroup: {
        styleOverrides: {
          root: { borderRadius: 999, overflow: 'hidden' },
          grouped: {
            border: `1px solid ${colors.divider}`,
            '&:not(:first-of-type)': { borderLeft: `1px solid ${colors.divider}`, marginLeft: 0 },
          },
        },
      },

      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 600,
            paddingInline: 14,
            color: colors.text.secondary,
            transition: `background-color ${MOTION.fast}ms ${MOTION.easing}, color ${MOTION.fast}ms ${MOTION.easing}`,
            '&.Mui-selected': {
              backgroundColor: alpha(colors.primary.main, isLight ? 0.14 : 0.22),
              color: colors.primary.main,
              '&:hover': {
                backgroundColor: alpha(colors.primary.main, isLight ? 0.2 : 0.28),
              },
            },
          },
          sizeSmall: { paddingBlock: 5, fontSize: '0.8rem' },
        },
      },

      MuiAutocomplete: {
        defaultProps: { size: 'small' },
        styleOverrides: {
          paper: {
            borderRadius: 12,
            border: `1px solid ${colors.divider}`,
            backgroundImage: 'none',
          },
          listbox: { padding: 4 },
          option: {
            borderRadius: 8,
            minHeight: 38,
            '&[aria-selected="true"]': {
              backgroundColor: alpha(colors.primary.main, isLight ? 0.1 : 0.18),
            },
          },
          tag: { margin: 2 },
        },
      },

      MuiSwitch: {
        styleOverrides: {
          // Ajratilgan "off" holati: rangsiz fonda kalit o'chiqligi
          // aniq ko'rinishi kerak, aks holda jadvalda uni holat
          // indikatori sifatida o'qib bo'lmaydi.
          track: {
            opacity: isLight ? 0.32 : 0.4,
            backgroundColor: colors.text.secondary,
          },
        },
      },

      MuiMenu: {
        styleOverrides: {
          paper: {
            borderRadius: 12,
            border: `1px solid ${colors.divider}`,
            backgroundImage: 'none',
          },
          list: { padding: 4 },
        },
      },

      MuiMenuItem: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            minHeight: 38,
            '&.Mui-selected': {
              backgroundColor: alpha(colors.primary.main, isLight ? 0.1 : 0.18),
            },
          },
        },
      },

      MuiDrawer: {
        styleOverrides: { paper: { backgroundImage: 'none' } },
      },

      MuiDialogTitle: {
        styleOverrides: { root: { fontSize: '1.1rem', fontWeight: 650, paddingBlock: 18 } },
      },

      MuiFormHelperText: {
        styleOverrides: { root: { marginLeft: 2, marginRight: 0 } },
      },

      MuiDivider: {
        styleOverrides: { root: { borderColor: colors.divider } },
      },
    },
  })

  // Grafiklar va jadval uchun qo'shimcha tokenlar.
  theme.chart = {
    colors: CHART_COLORS[mode],
    risk: RISK_SCALE[mode],
    grid: alpha(theme.palette.text.secondary, 0.16),
    axis: theme.palette.text.secondary,
  }
  theme.density = { ...densityConfig, key: density }
  theme.motion = MOTION

  return theme
}

function buildShadows(isLight) {
  const tint = isLight ? '20, 45, 35' : '0, 0, 0'
  const soft = (y, blur, opacity) => `0px ${y}px ${blur}px rgba(${tint}, ${opacity})`
  const shadows = ['none']
  for (let level = 1; level <= 24; level += 1) {
    const y = Math.round(level * 0.7)
    const blur = Math.round(level * 2.2 + 4)
    const opacity = (isLight ? 0.05 : 0.28) + level * (isLight ? 0.004 : 0.006)
    shadows.push(`${soft(y, blur, Math.min(opacity, isLight ? 0.16 : 0.5))}`)
  }
  return shadows
}

// --------------------------------------------------------------------------
// Domen yorliqlari va rang xaritalari
// --------------------------------------------------------------------------
export const STATUS_COLOR = {
  pending: 'default',
  face_check: 'info',
  ready: 'info',
  in_progress: 'success',
  finished: 'default',
  terminated: 'error',
  technical_problem: 'warning',
  expired: 'default',
}

export const STATUS_LABEL = {
  pending: 'Kutilmoqda',
  face_check: 'Yuz tekshiruvi',
  ready: 'Tayyor',
  in_progress: 'Jarayonda',
  finished: 'Tugatilgan',
  terminated: 'Chetlashtirilgan',
  technical_problem: 'Texnik muammo',
  expired: 'Muddati tugagan',
}

export const SEVERITY_LABEL = {
  0: 'Ma’lumot', 1: 'Past', 2: 'O‘rta', 3: 'Yuqori', 4: 'Kritik',
}

export const SEVERITY_COLOR = {
  0: 'default', 1: 'info', 2: 'warning', 3: 'error', 4: 'error',
}

/** Xavf balli (0–100) -> MUI rang nomi. */
export const riskColor = (score) => {
  if (score >= 70) return 'error'
  if (score >= 40) return 'warning'
  if (score >= 15) return 'info'
  return 'success'
}

/** Xavf balli -> aniq HEX (grafiklar uchun). */
export const riskHex = (theme, score) => {
  const scale = theme.chart.risk
  if (score >= 80) return scale[4]
  if (score >= 60) return scale[3]
  if (score >= 40) return scale[2]
  if (score >= 20) return scale[1]
  return scale[0]
}
