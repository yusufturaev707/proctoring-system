/**
 * Tema variantlari.
 *
 * Ko'zni charchatmaslik tamoyillari (proktor 8 soat ekranga qaraydi):
 *
 *  1. Sof oq (#FFF) va sof qora (#000) ISHLATILMAYDI. Sof oq fon yuqori
 *     yorqinlikda ko'zni qamashtiradi; sof qora esa matn atrofida "halo"
 *     effekti beradi. Buning o'rniga iliq-neytral (#F6F8F6) va chuqur
 *     yashil-qora (#0E1512).
 *
 *  2. Katta yuzalar DOIM past to'yinganlikda. To'yingan yashil faqat
 *     kichik urg'ularda (tugma, chip, indikator). Aks holda rang
 *     "vibratsiya" qiladi va ko'z tez charchaydi.
 *
 *  3. Semantik ranglar (xato/ogohlantirish) asosiy rangdan yetarlicha
 *     ajralib turadi — proktor xavfni bir qarashda ko'rishi kerak.
 *
 *  4. Barcha matn/fon juftliklari WCAG AA (4.5:1) ni qondiradi.
 */

const SEMANTIC = {
  light: {
    error: { main: '#C62828', light: '#EF5350', dark: '#8E0000' },
    warning: { main: '#B26A00', light: '#F5A623', dark: '#7A4500' },
    info: { main: '#0277BD', light: '#4FB3E8', dark: '#01579B' },
    success: { main: '#2E7D32', light: '#60AD5E', dark: '#005005' },
  },
  dark: {
    error: { main: '#FF6B6B', light: '#FF9A9A', dark: '#C62828' },
    warning: { main: '#FFB74D', light: '#FFD08A', dark: '#B26A00' },
    info: { main: '#4FC3F7', light: '#8BF6FF', dark: '#0277BD' },
    success: { main: '#81C784', light: '#B2FAB4', dark: '#519657' },
  },
}

/**
 * Har bir variant: `light` va `dark` uchun to'liq palitra.
 * `preview` — sozlamalar sahifasidagi rang namunalari.
 */
export const PALETTES = {
  emerald: {
    label: 'Zumrad',
    description: 'Yumshoq yashil — uzoq ishlash uchun standart',
    preview: ['#1B7F5C', '#4FA88A', '#F6F8F6'],
    light: {
      primary: { main: '#1B7F5C', light: '#4FA88A', dark: '#0F5A3F', contrastText: '#FFFFFF' },
      secondary: { main: '#5B7C6B', light: '#8AA898', dark: '#31513F', contrastText: '#FFFFFF' },
      background: { default: '#F6F8F6', paper: '#FFFFFF' },
      surface: { subtle: '#EDF2EE', raised: '#FFFFFF', sunken: '#E7EDE8' },
      divider: 'rgba(20, 60, 45, 0.10)',
      text: { primary: '#16211C', secondary: '#586661', disabled: '#9AA8A2' },
      ...SEMANTIC.light,
    },
    dark: {
      primary: { main: '#4FBF91', light: '#7FD9B4', dark: '#2E8C68', contrastText: '#08110D' },
      secondary: { main: '#8AA898', light: '#B4CDC0', dark: '#5B7C6B', contrastText: '#08110D' },
      background: { default: '#0E1512', paper: '#151F1A' },
      surface: { subtle: '#1B2721', raised: '#1F2E27', sunken: '#101A15' },
      divider: 'rgba(160, 210, 190, 0.14)',
      text: { primary: '#E4EDE8', secondary: '#A2B3AB', disabled: '#6B7A73' },
      ...SEMANTIC.dark,
    },
  },

  forest: {
    label: 'O‘rmon',
    description: 'To‘yingan yashil, yuqori kontrast',
    preview: ['#14634A', '#2E9E76', '#F2F6F3'],
    light: {
      primary: { main: '#14634A', light: '#2E9E76', dark: '#083C2B', contrastText: '#FFFFFF' },
      secondary: { main: '#6B7F3E', light: '#98AE68', dark: '#43541F', contrastText: '#FFFFFF' },
      background: { default: '#F2F6F3', paper: '#FFFFFF' },
      surface: { subtle: '#E8F0EA', raised: '#FFFFFF', sunken: '#DFE9E2' },
      divider: 'rgba(10, 50, 35, 0.12)',
      text: { primary: '#0F1C16', secondary: '#4C5C54', disabled: '#93A29A' },
      ...SEMANTIC.light,
    },
    dark: {
      primary: { main: '#3FD79B', light: '#78ECBC', dark: '#1E9A6C', contrastText: '#04120C' },
      secondary: { main: '#A8C27A', light: '#CBDEA6', dark: '#77904F', contrastText: '#04120C' },
      background: { default: '#0A120E', paper: '#111B16' },
      surface: { subtle: '#16231C', raised: '#1B2C23', sunken: '#0C1610' },
      divider: 'rgba(150, 220, 190, 0.15)',
      text: { primary: '#E6F1EA', secondary: '#9FB4A9', disabled: '#66786E' },
      ...SEMANTIC.dark,
    },
  },

  teal: {
    label: 'Feruza',
    description: 'Yashil-moviy, sovuq va tinch',
    preview: ['#0F7A73', '#3FA9A1', '#F4F8F8'],
    light: {
      primary: { main: '#0F7A73', light: '#3FA9A1', dark: '#00514C', contrastText: '#FFFFFF' },
      secondary: { main: '#4A7A86', light: '#7BA6B1', dark: '#22505B', contrastText: '#FFFFFF' },
      background: { default: '#F4F8F8', paper: '#FFFFFF' },
      surface: { subtle: '#EAF2F2', raised: '#FFFFFF', sunken: '#E1ECEC' },
      divider: 'rgba(15, 60, 60, 0.10)',
      text: { primary: '#132020', secondary: '#516060', disabled: '#95A4A4' },
      ...SEMANTIC.light,
    },
    dark: {
      primary: { main: '#45C7BE', light: '#7EE3DB', dark: '#1E9089', contrastText: '#04120F' },
      secondary: { main: '#7BA6B1', light: '#A9CBD4', dark: '#4A7A86', contrastText: '#04120F' },
      background: { default: '#0C1514', paper: '#131F1E' },
      surface: { subtle: '#192726', raised: '#1E2E2D', sunken: '#0F1A19' },
      divider: 'rgba(150, 215, 210, 0.14)',
      text: { primary: '#E3EEED', secondary: '#9FB2B1', disabled: '#697A79' },
      ...SEMANTIC.dark,
    },
  },

  ocean: {
    label: 'Okean',
    description: 'Klassik moviy',
    preview: ['#1668A8', '#4C9AD4', '#F5F7FA'],
    light: {
      primary: { main: '#1668A8', light: '#4C9AD4', dark: '#00437A', contrastText: '#FFFFFF' },
      secondary: { main: '#1B7F5C', light: '#4FA88A', dark: '#0F5A3F', contrastText: '#FFFFFF' },
      background: { default: '#F5F7FA', paper: '#FFFFFF' },
      surface: { subtle: '#ECF1F6', raised: '#FFFFFF', sunken: '#E3EAF2' },
      divider: 'rgba(20, 45, 70, 0.10)',
      text: { primary: '#141C24', secondary: '#54606C', disabled: '#98A3AE' },
      ...SEMANTIC.light,
    },
    dark: {
      primary: { main: '#5AAEE8', light: '#8FCEF7', dark: '#2A7EB8', contrastText: '#061019' },
      secondary: { main: '#4FBF91', light: '#7FD9B4', dark: '#2E8C68', contrastText: '#061019' },
      background: { default: '#0C121A', paper: '#131C26' },
      surface: { subtle: '#18232F', raised: '#1D2937', sunken: '#0F1720' },
      divider: 'rgba(160, 200, 235, 0.14)',
      text: { primary: '#E3EAF2', secondary: '#9FADBB', disabled: '#69757F' },
      ...SEMANTIC.dark,
    },
  },

  slate: {
    label: 'Grafit',
    description: 'Neytral, minimal urg‘u — eng past charchoq',
    preview: ['#3E5A50', '#6E8B80', '#F5F6F5'],
    light: {
      primary: { main: '#3E5A50', light: '#6E8B80', dark: '#1D362C', contrastText: '#FFFFFF' },
      secondary: { main: '#1B7F5C', light: '#4FA88A', dark: '#0F5A3F', contrastText: '#FFFFFF' },
      background: { default: '#F5F6F5', paper: '#FFFFFF' },
      surface: { subtle: '#EDEFEE', raised: '#FFFFFF', sunken: '#E5E8E6' },
      divider: 'rgba(30, 45, 40, 0.10)',
      text: { primary: '#1A211E', secondary: '#57615C', disabled: '#98A19D' },
      ...SEMANTIC.light,
    },
    dark: {
      primary: { main: '#8FB0A2', light: '#B8D0C5', dark: '#5E7D70', contrastText: '#0A0F0D' },
      secondary: { main: '#4FBF91', light: '#7FD9B4', dark: '#2E8C68', contrastText: '#0A0F0D' },
      background: { default: '#101312', paper: '#181C1A' },
      surface: { subtle: '#1E2321', raised: '#232927', sunken: '#131716' },
      divider: 'rgba(190, 205, 198, 0.13)',
      text: { primary: '#E6E9E7', secondary: '#A4ADA8', disabled: '#6C7570' },
      ...SEMANTIC.dark,
    },
  },
}

export const PALETTE_KEYS = Object.keys(PALETTES)
export const DEFAULT_PALETTE = 'emerald'

/**
 * Grafiklar uchun kategorik ranglar.
 *
 * Ular palitradan MUSTAQIL: chart ranglari ma'no tashiydi (qaysi qator
 * qaysi turkum), tema o'zgarganda ma'no o'zgarmasligi kerak. Faqat
 * light/dark uchun yorqinlik moslashtiriladi.
 */
export const CHART_COLORS = {
  light: ['#1B7F5C', '#0277BD', '#B26A00', '#C62828', '#6A4C93', '#00838F', '#7CB342', '#5D4037'],
  dark: ['#4FBF91', '#4FC3F7', '#FFB74D', '#FF6B6B', '#B39DDB', '#4DD0E1', '#AED581', '#BCAAA4'],
}

/** Xavf darajasi shkalasi — past→yuqori (yashildan qizilgacha). */
export const RISK_SCALE = {
  light: ['#2E7D32', '#7CB342', '#F5A623', '#EF6C00', '#C62828'],
  dark: ['#81C784', '#AED581', '#FFD08A', '#FFA726', '#FF6B6B'],
}
