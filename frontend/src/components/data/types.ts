import type { ComponentType, ReactNode } from 'react'
import type { ButtonProps, SvgIconProps } from '@mui/material'
import type { GridColDef, GridRenderCellParams, GridRowParams } from '@mui/x-data-grid'

import type { ApiRecord, Id, QueryParams } from '../../types/api'

/**
 * CRUD dvigateli turlari (`ResourcePage`, `ResourceForm`, `DataTable`).
 *
 * Sahifalar (`pages/crud/*.tsx`) faqat `columns` va `fields` ni
 * deklarativ yozadi — shu yerdagi turlar ularning shartnomasi.
 */

/** Tanlov varianti (`select`, `multiselect`, filtr). */
export interface Option {
  value: string | number
  label: string
  // Sahifa variantga qo'shimcha ma'lumot qo'shadi (`region`, `zone`) —
  // bog'liq ro'yxatlarni filtrlash uchun.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [extra: string]: any
}

/**
 * Forma holati: maydon qiymatlari + `_meta` (`isEdit`, `row`, `context`).
 * Maydonlar sahifaga xos, shuning uchun lug'at.
 */
export type FormValues = ApiRecord

export type FieldType =
  | 'text' | 'textarea' | 'number' | 'password' | 'email' | 'url' | 'boolean'
  | 'select' | 'autocomplete' | 'multiselect' | 'date' | 'datetime' | 'time'
  | 'json' | 'custom'

/** `type: 'custom'` maydonining chizuvchisi oladigan argumentlar. */
export interface CustomFieldProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  value: any
  onChange: (value: unknown) => void
  disabled: boolean
  error?: string
  form: FormValues
  isEdit: boolean
}

export interface PatternRule {
  re: RegExp
  message: string
}

/** Forma maydoni (`ResourceForm`). */
export interface FieldDef {
  name: string
  label?: string
  type?: FieldType
  required?: boolean
  /** 12 ustunli to'rda kenglik (`sm` va kattaroq). */
  colSpan?: number
  section?: string
  helperText?: ReactNode | ((isEdit: boolean, form: FormValues) => ReactNode)
  /** Tanlov variantlari — formaga bog'liq bo'lishi mumkin (viloyat -> binolar). */
  options?: Option[] | ((form: FormValues) => Option[])
  /** Shu maydon to'ldirilmaguncha bu maydon to'siladi. */
  dependsOn?: string
  blockedText?: string
  emptyOptionsText?: string
  /** O'zgarganda tozalanadigan quyi maydonlar (viloyat -> bino). */
  resets?: string[]
  hidden?: (form: FormValues) => boolean
  disabled?: (form: FormValues, isEdit: boolean) => boolean
  // Qiymat maydon turiga bog'liq (satr, son, massiv) — validator o'zi biladi.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  validate?: (value: any, form: FormValues) => string | null | undefined | false
  pattern?: string | PatternRule
  min?: number
  max?: number
  step?: number | string
  integer?: boolean
  minLength?: number
  maxLength?: number
  minItems?: number
  maxItems?: number
  /** Yuborishdan oldin qiymatni o'zgartiradi. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  transform?: (value: any) => unknown
  /** Serializer M2M ni obyekt ro'yxati bilan qaytarsa — ID'larga keltiradi. */
  readFrom?: (row: ApiRecord) => unknown
  /** Forma ichidagi yordamchi maydon — serverga yuborilmaydi. */
  transient?: boolean
  readOnly?: boolean
  password?: boolean
  /** `false` — tozalanganda `null` emas, bo'sh satr. */
  nullable?: boolean
  /** `false` — tahrirda bo'sh qoldirilsa umuman yuborilmaydi. */
  clearable?: boolean
  emptyValue?: unknown
  autoComplete?: string
  render?: (props: CustomFieldProps) => ReactNode
}

/** Jadval ustidagi filtr (`ResourcePage filters`). */
export interface FilterDef {
  name: string
  label: string
  type?: 'select' | 'text' | 'date' | 'number'
  options?: Option[] | ((filters: Record<string, string>) => Option[])
  allLabel?: string
  /** Bog'liq quyi filtrlar (viloyat -> bino). */
  resets?: string[]
  /** Viloyat xodimiga ko'rsatilmaydi (server baribir o'z viloyatini beradi). */
  regionScope?: boolean
}

/**
 * Jadval ustuni: DataGrid ustuni + CSV uchun o'qiladigan qiymat.
 * `exportValue` — ustun faqat `renderCell` bilan chizilsa (chip, switch).
 */
export type AppColumn = GridColDef<ApiRecord> & {
  // Qiymat ustun maydoniga bog'liq (satr, son, ro'yxat) — `renderCell` kabi.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  exportValue?: (value: any, row: ApiRecord) => unknown
}

/** Ommaviy amal (`ResourcePage bulkActions`). */
export interface BulkAction {
  key: string
  label: string
  icon?: ReactNode
  color?: ButtonProps['color']
  confirmTitle?: string
  confirmLabel?: string
  description?: (count: number) => ReactNode
  confirmPhrase?: (count: number) => string | null
  run: (selection: { ids?: readonly Id[]; all: boolean; params: QueryParams }) => Promise<ApiRecord>
  success?: (result: ApiRecord) => string
}

/** Forma bo'limi sarlavhasi (MD3). */
export interface SectionMeta {
  icon?: ComponentType<SvgIconProps>
  description?: ReactNode
}

/** Qator bosilganda sahifaga beriladigan amallar. */
export interface RowClickHelpers {
  event: unknown
  openEdit: (row: ApiRecord) => void
}

export type RowClickHandler = (params: GridRowParams<ApiRecord>, helpers: RowClickHelpers) => void

/** `renderCell` argumenti. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type CellParams<V = any> = GridRenderCellParams<ApiRecord, V>

/** Qator bosilganda ochilgan tafsilot kartasi holati. */
export interface RowDetail {
  row: ApiRecord
  openEdit: (row: ApiRecord) => void
}

/** Ma'lumotnoma sahifalaridagi tafsilot kartalari uchun umumiy props. */
export interface DetailDialogBaseProps {
  row: ApiRecord
  onEdit?: () => void
  onClose: () => void
}
