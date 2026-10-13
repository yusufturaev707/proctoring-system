/**
 * MUI temasini kengaytirish — `theme/index.ts` qo'shadigan tokenlar.
 *
 * `palette.m3` (Material 3 rollari) `sx` da `bgcolor: 'm3.surfaceContainerLow'`
 * kabi satr bilan ham ishlatiladi; bu yerda e'lon qilinmasa
 * `theme.palette.m3.*` ga to'g'ridan-to'g'ri murojaat kompilyatsiya
 * xatosi bo'lardi. DataGrid ham tema orqali sozlanadi
 * (`components.MuiDataGrid`) — uning kengaytmasi alohida import.
 */
import '@mui/material/styles'
import type {} from '@mui/x-data-grid/themeAugmentation'
// Kengaytma YANGI nom e'lon qila olmaydi (faqat mavjud interfeysni
// to'ldiradi) — token turlari oddiy modulda.
import type {
  ChartTokens, DensityTokens, M3Roles, MotionTokens, SidebarTokens, SurfaceColors,
} from './tokens'

declare module '@mui/material/styles' {
  interface Palette {
    m3: M3Roles
    surface: SurfaceColors
  }

  interface PaletteOptions {
    m3?: M3Roles
    surface?: SurfaceColors
  }

  interface Theme {
    chart: ChartTokens
    density: DensityTokens
    motion: MotionTokens
    sidebar: SidebarTokens
  }
}
