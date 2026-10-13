/** Tema tokenlari turlari (`theme/index.ts` hisoblaydi, `mui.d.ts` e'lon qiladi). */

/** Material 3 rang rollari — `theme.palette.m3`. */
export interface M3Roles {
  primaryContainer: string
  onPrimaryContainer: string
  secondaryContainer: string
  onSecondaryContainer: string
  surfaceContainerLowest: string
  surfaceContainerLow: string
  surfaceContainer: string
  surfaceContainerHigh: string
  surfaceContainerHighest: string
  outline: string
  outlineVariant: string
}

export interface SurfaceColors {
  subtle: string
  raised: string
  sunken: string
}

export interface ChartTokens {
  colors: string[]
  risk: string[]
  grid: string
  axis: string
}

export interface DensityTokens {
  spacing: number
  rowHeight: number
  fontScale: number
  key: 'comfortable' | 'compact'
}

export interface MotionTokens {
  fast: number
  base: number
  slow: number
  easing: string
}

export interface SidebarTokens {
  expanded: number
  rail: number
}
