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

/** Yon panel kengliklari (Material 3: navigation drawer / rail). */
export const SIDEBAR = { expanded: 272, rail: 84 }

/**
 * Ikki HEX rangni aralashtiradi (`amount` — ikkinchisining ulushi).
 *
 * Material 3 tonal sirtlari (`surfaceContainer*`, `*Container`) — asosiy
 * rangning fon ustidagi QATTIQ rangdagi aralashmasi, shaffof qatlam
 * emas. Shaffoflik (`alpha`) ustma-ust tushganda (menyu kartada, karta
 * fonda) har safar boshqa rang berardi va sirtlar darajasi yo'qolardi.
 * Aralashma HISOBLANADI, palitrada qo'lda yozilmaydi: 5 sxema x 2 rejim
 * uchun 50 ta qo'shimcha rangni qo'lda moslab bo'lmasdi.
 */
function mix(base, tint, amount) {
  const parse = (hex) => {
    const value = hex.replace('#', '')
    return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16))
  }
  const a = parse(base)
  const b = parse(tint)
  const channel = (i) => Math.round(a[i] + (b[i] - a[i]) * amount).toString(16).padStart(2, '0')
  return `#${channel(0)}${channel(1)}${channel(2)}`
}

/**
 * Material 3 rang rollari — mavjud palitradan chiqariladi.
 *
 * Rejimga qarab ulush boshqacha: tungi rejimda past to'yinganlik
 * yetarli emas (ko'z farqni sezmaydi), kunduzgisida esa yuqori ulush
 * katta yuzalarni "bo'yab" yuborardi.
 */
function buildM3Roles(colors, isLight) {
  const bg = colors.background.default
  const primary = colors.primary.main
  const secondary = colors.secondary.main
  const ink = isLight ? '#000000' : '#FFFFFF'
  return {
    primaryContainer: mix(bg, primary, isLight ? 0.16 : 0.28),
    onPrimaryContainer: isLight ? colors.primary.dark : colors.primary.light,
    secondaryContainer: mix(bg, secondary, isLight ? 0.18 : 0.3),
    onSecondaryContainer: isLight ? mix(colors.secondary.dark, ink, 0.2) : colors.secondary.light,
    // Sirt darajalari: eng pastidan eng balandigacha. Karta — "lowest",
    // yon panel — "low", menyu va dialog — "high".
    // Tungi rejimda M3 spetsifikatsiyasidagi "lowest" (fondan TO'Q)
    // ishlatilmaydi: sinovda kartalar sahifaga "botib" ko'rindi. Karta
    // fondan biroz OCHROQ — ko'z uni ko'tarilgan sirt deb o'qiydi.
    surfaceContainerLowest: isLight ? '#FFFFFF' : colors.background.paper,
    surfaceContainerLow: mix(bg, primary, isLight ? 0.035 : 0.05),
    surfaceContainer: mix(bg, primary, isLight ? 0.06 : 0.08),
    surfaceContainerHigh: isLight ? mix('#FFFFFF', primary, 0.05) : mix(bg, primary, 0.12),
    surfaceContainerHighest: mix(bg, primary, isLight ? 0.11 : 0.16),
    outline: mix(bg, colors.text.secondary, isLight ? 0.55 : 0.5),
    outlineVariant: mix(bg, colors.text.secondary, isLight ? 0.2 : 0.25),
  }
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
  const m3 = buildM3Roles(colors, isLight)

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
      // Material 3 rollari — `sx` da `m3.primaryContainer` kabi ishlatiladi.
      m3,
      action: {
        hover: alpha(colors.primary.main, isLight ? 0.06 : 0.1),
        selected: alpha(colors.primary.main, isLight ? 0.1 : 0.16),
        focus: alpha(colors.primary.main, 0.2),
      },
    },

    shape: { borderRadius: 12 },
    spacing: densityConfig.spacing,

    typography: {
      // Inter — paket ichida (`@fontsource-variable/inter`, `main.jsx`),
      // CDN'dan emas: imtihon markazlarining tarmog'ida internet
      // bo'lmasligi mumkin va shrift jimgina Segoe UI ga tushardi.
      fontFamily: '"Inter Variable", "Inter", "Segoe UI", system-ui, -apple-system, sans-serif',
      // `-0.01em` — katta sarlavhalarda harflar orasidagi bo'shliqni
      // qisqartiradi, matn "yig'ilgan" va o'qishga qulay ko'rinadi.
      h4: { fontWeight: 700, letterSpacing: '-0.02em', fontSize: `${1.9 * densityConfig.fontScale}rem` },
      // M3 "headline small" — sahifa sarlavhasi.
      h5: { fontWeight: 650, letterSpacing: '-0.02em', fontSize: `${1.5 * densityConfig.fontScale}rem`, lineHeight: 1.3 },
      h6: { fontWeight: 650, letterSpacing: '-0.01em', fontSize: `${1.12 * densityConfig.fontScale}rem` },
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

      // M3 "outlined card": sirt eng past darajada, chegara
      // `outlineVariant` bilan. Soya YO'Q — daraja rang bilan beriladi.
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            borderRadius: 16,
            border: `1px solid ${m3.outlineVariant}`,
            backgroundColor: m3.surfaceContainerLowest,
            transition: `border-color ${MOTION.fast}ms ${MOTION.easing}, box-shadow ${MOTION.fast}ms ${MOTION.easing}`,
          },
        },
      },

      // Telefonda karta chegarasi 16 px (20 emas): sahifa chetidagi 16 px
      // bilan birga matn uchun ~300 px qoladi, ichma-ich kartada esa
      // har 4 px o'qiladigan qatorga ta'sir qiladi.
      MuiCardHeader: {
        styleOverrides: {
          root: ({ theme: t }) => ({
            paddingBottom: 8, paddingInline: 20, paddingTop: 18,
            [t.breakpoints.down('sm')]: { paddingInline: 16, paddingTop: 16 },
          }),
          title: { fontSize: '1rem', fontWeight: 650, letterSpacing: '-0.005em' },
          subheader: { fontSize: '0.82rem', marginTop: 2 },
        },
      },

      MuiCardContent: {
        styleOverrides: {
          root: ({ theme: t }) => ({
            paddingInline: 20,
            '&:last-child': { paddingBottom: 20 },
            [t.breakpoints.down('sm')]: { paddingInline: 16, '&:last-child': { paddingBottom: 16 } },
          }),
        },
      },

      // M3 tugmalari — to'liq kapsula (`full` shakl), 40 px balandlik.
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            borderRadius: 999,
            paddingInline: 18,
            minHeight: 38,
            transition: `background-color ${MOTION.fast}ms ${MOTION.easing}, transform ${MOTION.fast}ms ${MOTION.easing}, border-color ${MOTION.fast}ms ${MOTION.easing}`,
            '&:active': { transform: 'scale(0.98)' },
          },
          sizeSmall: { minHeight: 32, paddingInline: 12, fontSize: '0.8rem' },
          sizeLarge: { minHeight: 46, paddingInline: 24 },
          containedPrimary: {
            '&:hover': { backgroundColor: colors.primary.dark },
          },
          outlined: {
            borderColor: m3.outline,
            '&:hover': { borderColor: colors.primary.main },
          },
          // `color="inherit"` + text — M3 "text button" ikkilamchi amal.
          textInherit: {
            color: colors.text.secondary,
            '&:hover': { color: colors.text.primary },
          },
        },
      },

      MuiIconButton: {
        styleOverrides: {
          root: { transition: `background-color ${MOTION.fast}ms ${MOTION.easing}, color ${MOTION.fast}ms ${MOTION.easing}` },
        },
      },

      MuiFab: {
        styleOverrides: {
          root: { borderRadius: 16, boxShadow: 'none' },
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
            borderRadius: 10,
            backgroundColor: m3.surfaceContainerLowest,
            '& .MuiOutlinedInput-notchedOutline': { borderColor: m3.outlineVariant },
            '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: m3.outline },
            '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderWidth: 2 },
          },
        },
      },

      MuiInputLabel: {
        styleOverrides: { root: { fontWeight: 500 } },
      },

      MuiTableCell: {
        styleOverrides: {
          root: { borderColor: m3.outlineVariant, fontVariantNumeric: 'tabular-nums' },
          head: {
            fontWeight: 650,
            whiteSpace: 'nowrap',
            backgroundColor: m3.surfaceContainerLow,
            color: colors.text.secondary,
            fontSize: '0.78rem',
            letterSpacing: '0.01em',
          },
        },
      },

      // M3 "plain tooltip": teskari sirt (to'q fonda och matn va aksincha).
      // U menyu yig'ilganda sahifa nomini va vazifasini aytadi, ya'ni
      // o'qilishi kerak — standart kulrang shaffof fon buni qiyinlashtirardi.
      MuiTooltip: {
        defaultProps: { arrow: false, enterDelay: 350, enterNextDelay: 150 },
        styleOverrides: {
          tooltip: {
            fontSize: '0.78rem',
            lineHeight: 1.45,
            paddingBlock: 6,
            paddingInline: 10,
            borderRadius: 8,
            maxWidth: 320,
            backgroundColor: isLight ? '#2B3230' : '#E3E8E5',
            color: isLight ? '#F1F4F2' : '#1A201D',
          },
        },
      },

      // M3 "primary tabs": indikator faqat matn kengligida va yumaloq.
      // Tab'lar DOIM suriladigan (`scrollable`): telefonda to'rtta tab
      // sig'masdi va oxirgisi yarmidan kesilib, qolganlari borligi
      // sezilmasdi. Surish tugmalari mobilda ham ko'rinadi — ular
      // "o'ngda yana bor" degan yagona belgi. Butun kenglikni teng
      // bo'lishishi kerak bo'lgan joy `variant="fullWidth"` ni ochiq beradi.
      MuiTabs: {
        defaultProps: { variant: 'scrollable', scrollButtons: 'auto', allowScrollButtonsMobile: true },
        styleOverrides: {
          root: { minHeight: 48 },
          indicator: { height: 3, borderRadius: '3px 3px 0 0' },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            minHeight: 48,
            fontWeight: 600,
            textTransform: 'none',
            color: colors.text.secondary,
            '&.Mui-selected': { color: colors.primary.main },
          },
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
          root: { borderRadius: 12, alignItems: 'center' },
          standardInfo: { backgroundColor: alpha(colors.info.main, 0.1) },
          standardWarning: { backgroundColor: alpha(colors.warning.main, 0.12) },
          standardError: { backgroundColor: alpha(colors.error.main, 0.1) },
          standardSuccess: { backgroundColor: alpha(colors.success.main, 0.1) },
          outlined: { backgroundColor: m3.surfaceContainerLowest },
        },
      },

      // M3 dialog: "extra large" shakl (28 px), sirt "high" darajada.
      MuiDialog: {
        styleOverrides: {
          paper: ({ theme: t }) => ({
            borderRadius: 28,
            backgroundImage: 'none',
            backgroundColor: m3.surfaceContainerHigh,
            // Telefonda chetlar 16 px (standart 32): 390 px ekranda
            // standart bilan dialog 326 px bo'lib, ikki ustunli forma
            // maydonlari o'qib bo'lmas darajada torayardi.
            //
            // `:not(fullScreen)` SHART: media so'rovdagi qoida CSS'da
            // `paperFullScreen` dan keyin keladi va uni bosib, to'liq
            // ekranli formani yana 16 px chetli oynaga aylantirardi.
            [t.breakpoints.down('sm')]: {
              '&:not(.MuiDialog-paperFullScreen)': {
                margin: 16,
                width: 'calc(100% - 32px)',
                maxHeight: 'calc(100% - 32px)',
                borderRadius: 24,
              },
            },
          }),
          // To'liq ekranli dialog (telefonda formalar) — yumaloq burchaksiz,
          // aks holda ekran burchaklarida fon ko'rinib qolardi.
          paperFullScreen: { borderRadius: 0, margin: 0, width: '100%', maxHeight: '100%' },
        },
      },

      MuiDialogContent: {
        styleOverrides: { root: { paddingInline: 24 } },
      },

      MuiDialogActions: {
        styleOverrides: { root: { paddingInline: 24, paddingBottom: 20, gap: 4 } },
      },

      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 999,
            transition: `background-color ${MOTION.fast}ms ${MOTION.easing}, color ${MOTION.fast}ms ${MOTION.easing}`,
          },
        },
      },

      MuiPaginationItem: {
        styleOverrides: {
          root: { borderRadius: 999, fontWeight: 600 },
        },
      },

      MuiAvatar: {
        styleOverrides: { root: { fontWeight: 650 } },
      },

      // DataGrid — butun paneldagi asosiy element, shuning uchun uning
      // uslubi temada (har jadvalda alohida emas).
      MuiDataGrid: {
        styleOverrides: {
          root: {
            '--DataGrid-containerBackground': m3.surfaceContainerLow,
            '--DataGrid-rowBorderColor': m3.outlineVariant,
            fontVariantNumeric: 'tabular-nums',
          },
          columnHeaderTitle: { fontWeight: 650 },
        },
      },

      // --- Segmentli boshqaruv (holat bo'yicha ko'rinishni almashtirish) ---
      //
      // Material 3 da bu element "segmented button": yaxlit kapsula,
      // tanlangan segment past to'yinganlikdagi primary bilan bo'yaladi.
      // MUI standarti to'rtburchak va deyarli ko'rinmaydigan tanlov beradi
      // — sahifa sarlavhasida u tugma emas, matn bo'lib qoladi.
      // Tor ekranda guruh SIQILMAYDI, suriladi: siqilganda "Barchasi · 1"
      // ikki qatorga bo'linib, segmentlar har xil balandlikda chiqardi.
      MuiToggleButtonGroup: {
        styleOverrides: {
          root: {
            borderRadius: 999,
            border: `1px solid ${m3.outline}`,
            overflow: 'hidden',
            maxWidth: '100%',
            // Flex bolasi sifatida `min-width: auto` guruhni mazmunidan
            // tor bo'lishiga qo'ymaydi va u butun sahifani gorizontal surardi.
            minWidth: 0,
            overflowX: 'auto',
            scrollbarWidth: 'none',
            '&::-webkit-scrollbar': { display: 'none' },
          },
          // Chegara GURUHDA, tugmalarda emas: `overflow: hidden` kapsula
          // chetini qirqadi va tugmaning o'z o'ng chegarasi kesilib,
          // guruh "ochiq qolgan" bo'lib ko'rinardi. Tugmalar orasida
          // faqat ajratuvchi chiziq.
          grouped: {
            border: 0,
            borderRadius: 0,
            '&:not(:first-of-type)': { borderLeft: `1px solid ${m3.outlineVariant}`, marginLeft: 0 },
          },
        },
      },

      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 600,
            paddingInline: 14,
            whiteSpace: 'nowrap',
            flexShrink: 0,
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
            border: `1px solid ${m3.outlineVariant}`,
            backgroundImage: 'none',
            backgroundColor: m3.surfaceContainer,
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
            border: `1px solid ${m3.outlineVariant}`,
            backgroundImage: 'none',
            backgroundColor: m3.surfaceContainer,
          },
          list: { padding: 4 },
        },
      },

      MuiPopover: {
        styleOverrides: { paper: { backgroundImage: 'none' } },
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
        styleOverrides: {
          root: { fontSize: '1.25rem', fontWeight: 650, letterSpacing: '-0.01em', paddingTop: 22, paddingBottom: 12, paddingInline: 24 },
        },
      },

      MuiFormHelperText: {
        styleOverrides: { root: { marginLeft: 2, marginRight: 0 } },
      },

      MuiDivider: {
        styleOverrides: { root: { borderColor: m3.outlineVariant } },
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
  theme.sidebar = SIDEBAR

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
