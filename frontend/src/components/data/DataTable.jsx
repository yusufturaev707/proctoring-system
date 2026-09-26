import { useMemo, useState } from 'react'
import {
  Box, Card, IconButton, LinearProgress, MenuItem, Pagination, Stack, TextField,
  Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import { DataGrid } from '@mui/x-data-grid'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import { EmptyState, ErrorState } from '../feedback/States'

const LOCALE = {
  noRowsLabel: 'Ma’lumot yo‘q',
  noResultsOverlayLabel: 'Natija topilmadi',
  footerRowSelected: (count) => `${count} ta tanlandi`,
  columnHeaderSortIconLabel: 'Saralash',
}

const PAGE_SIZES = [25, 50, 100]

/**
 * Tartib raqami ustuni.
 *
 * Nima uchun ID emas: adminlar bir-biriga «12-qatorga qara» deb aytadi,
 * «id 8471 ga qara» demaydi. Shuning uchun asosiy qiymat — ro'yxatdagi
 * o'rin. Yozuvning haqiqiy ID'si esa tooltipda: u havola yasash va
 * qo'llab-quvvatlash uchun kerak bo'ladi.
 *
 * `offset` — joriy sahifagacha bo'lgan qatorlar soni. Kursorli
 * sahifalashda uni bilib bo'lmaydi (umumiy son so'ralmaydi), shuning
 * uchun u yerda raqam har sahifada 1 dan boshlanadi.
 */
function buildRowNumberColumn(offset, rowIds) {
  return {
    field: '__rownum',
    headerName: '№',
    width: 62,
    sortable: false,
    filterable: false,
    disableColumnMenu: true,
    align: 'right',
    headerAlign: 'right',
    renderCell: (params) => {
      const index = rowIds.indexOf(params.id)
      return (
        <Tooltip title={`ID: ${params.id}`} placement="right">
          <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
            {index < 0 ? '—' : offset + index + 1}
          </Typography>
        </Tooltip>
      )
    },
  }
}

/**
 * Jadval — serverga tayangan sahifalash/saralash bilan.
 *
 * Muhim: sahifalash, saralash va filtrlash SERVERDA bajariladi. Sessiyalar
 * va hodisalar jadvalida millionlab qator bo'ladi; ularni brauzerga
 * yuklab keyin filtrlash imkonsiz.
 *
 * `keepPreviousData` bilan birga ishlaganda jadval yangi sahifani
 * kutayotganda BO'SHAMAYDI — eski qatorlar xiralashadi va tepada ingichka
 * progress chizig'i chiqadi. Bu "sakrash"ni yo'q qiladi.
 */
export default function DataTable({
  rows = [],
  columns,
  loading = false,
  fetching = false,
  error = null,
  onRetry,
  rowCount,
  paginationModel,
  onPaginationModelChange,
  sortModel,
  onSortModelChange,
  onRowClick,
  getRowId,
  height = 620,
  emptyTitle = 'Ma’lumot topilmadi',
  emptyDescription,
  emptyAction,
  toolbar,
  /**
   * Kursorli sahifalash (sessiyalar, hodisalar, audit).
   * `{ hasNext, hasPrevious, onNext, onPrevious, pageSize, onPageSizeChange }`
   */
  cursorNav,
  /** `№` ustunini chizish (standart — ha). */
  showRowNumber = true,
  /**
   * Qo'shimcha grid uslublari (masalan `getRowClassName` bilan
   * belgilangan qatorlar uchun).
   *
   * ALOHIDA prop, `sx` EMAS: `sx` `...rest` orqali ichki uslublarni
   * BUTUNLAY almashtirardi va chaqiruvchi bitta qator rangini
   * o'zgartirmoqchi bo'lganda ustun sarlavhalari, hover va `№`
   * ustunining butun uslubi yo'qolardi.
   */
  gridSx,
  ...rest
}) {
  const serverSide = typeof rowCount === 'number'
  const resolveId = getRowId || ((row) => row.id)

  // TOR EKRANDA JADVAL QAT'IY BALANDLIKDA EMAS (`autoHeight`): qatorlar
  // sahifa bilan birga suriladi. Qat'iy balandlik telefonda ikki xil
  // xato berardi — bitta qatorli jadval ostida ~550 px bo'sh maydon, va
  // sahifa ichida ikkinchi vertikal skroll (barmoq bilan surganda
  // jadval yoki sahifa suriladimi — oldindan bilib bo'lmaydi).
  // Gorizontal skroll qoladi: ustunlar telefonga sig'maydi va ularni
  // yashirish ma'lumotni yo'qotish bo'lardi.
  const theme = useTheme()
  const compact = useMediaQuery(theme.breakpoints.down('md'))

  // Sahifalash boshqarilmagan bo'lsa (jonli kuzatuv kabi mijoz tomonda
  // ishlaydigan jadvallar) — uni shu yerda o'zimiz yuritamiz. Aks holda
  // DataGrid'ning standart futerini yashirganimizdan keyin bunday
  // jadval umuman sahifalanmay qolardi.
  const [ownPagination, setOwnPagination] = useState({ page: 0, pageSize: 25 })
  const isControlled = Boolean(paginationModel)
  const effectivePagination = isControlled ? paginationModel : ownPagination
  const setPagination = isControlled ? onPaginationModelChange : setOwnPagination

  // Raqam siljishi FAQAT server rejimida qo'shiladi: u yerda `rows` —
  // bitta sahifa, ya'ni indeks har sahifada 0 dan boshlanadi. Mijoz
  // rejimida esa `rows` to'liq ro'yxat va indeksning o'zi global —
  // unga siljish qo'shilsa raqamlar ikki marta sanaladi.
  const offset = cursorNav
    ? (cursorNav.pageIndex || 0) * (cursorNav.pageSize || 0)
    : serverSide
      ? (effectivePagination?.page || 0) * (effectivePagination?.pageSize || 0)
      : 0

  const gridColumns = useMemo(() => {
    if (!showRowNumber) return columns
    const ids = rows.map(resolveId)
    return [buildRowNumberColumn(offset, ids), ...columns]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, showRowNumber, offset, rows])

  const slots = useMemo(
    () => ({
      noRowsOverlay: () => (
        <EmptyState
          title={emptyTitle}
          description={emptyDescription}
          actionLabel={emptyAction?.label}
          onAction={emptyAction?.onClick}
          dense
        />
      ),
      noResultsOverlay: () => (
        <EmptyState title="Natija topilmadi" description="Filtr shartlarini o‘zgartirib ko‘ring" dense />
      ),
    }),
    [emptyTitle, emptyDescription, emptyAction],
  )

  if (error && !rows.length) {
    return (
      <Card>
        <ErrorState error={error} onRetry={onRetry} />
      </Card>
    )
  }

  // Sahifalash o'zimizniki: DataGrid'ning standart futeri offset rejimida
  // `TablePagination`, kursorli rejimda esa umuman yo'q edi — natijada
  // bitta paneldagi ikki jadval boshqacha boshqariladigan ko'rinardi.
  // Bo'sh jadvalda futer chizilmaydi — u yerda boshqariladigan narsa yo'q.
  // Istisno: birinchi sahifada emasmiz. Unda futer QOLISHI shart, aks
  // holda bo'shab qolgan oxirgi sahifaga tushgan odam uchun orqaga
  // qaytish yo'li yo'qoladi.
  const showFooter =
    Boolean(cursorNav) || rows.length > 0 || (effectivePagination?.page || 0) > 0

  return (
    <Card sx={{ overflow: 'hidden' }}>
      {toolbar}

      {/* Fon yangilanishi: qatorlar joyida qoladi, faqat nozik indikator. */}
      <Box sx={{ height: 3 }}>
        {fetching && !loading && <LinearProgress sx={{ height: 3 }} />}
      </Box>

      <Box sx={{ height: compact ? 'auto' : height, width: '100%' }}>
        <DataGrid
          autoHeight={compact}
          rows={rows}
          columns={gridColumns}
          loading={loading}
          getRowId={resolveId}
          // Belgilash katakchasini bosish qatorni OCHMASLIGI kerak.
          onRowClick={onRowClick && ((params, event) => {
            if (event?.target?.closest?.('.MuiDataGrid-cellCheckbox')) return
            onRowClick(params, event)
          })}
          rowCount={serverSide ? rowCount : undefined}
          paginationMode={serverSide ? 'server' : 'client'}
          sortingMode={serverSide ? 'server' : 'client'}
          paginationModel={effectivePagination}
          onPaginationModelChange={setPagination}
          sortModel={sortModel}
          onSortModelChange={onSortModelChange}
          pageSizeOptions={PAGE_SIZES}
          disableRowSelectionOnClick
          disableColumnMenu
          density="compact"
          localeText={LOCALE}
          slots={slots}
          hideFooter
          sx={{
            border: 0,
            // Yangi sahifa kelayotganda eski qatorlar xiralashadi —
            // "bo'sh ekran" o'rniga uzluksizlik hissi.
            opacity: fetching && !loading ? 0.55 : 1,
            transition: (theme) => theme.transitions.create('opacity', { duration: 140 }),
            '& .MuiDataGrid-columnHeaders': { bgcolor: 'm3.surfaceContainerLow' },
            // Sarlavhalar ODDIY registrda: katta harfli qisqa sarlavhalar
            // o'zbekcha uzun so'zlarda ("OXIRGI FAOLLIK") ustunni kengaytirib,
            // o'qishni sekinlashtirardi.
            '& .MuiDataGrid-columnHeaderTitle': {
              fontWeight: 650, fontSize: '0.8rem', color: 'text.secondary',
            },
            '& .MuiDataGrid-cell:focus, & .MuiDataGrid-cell:focus-within': { outline: 'none' },
            // `№` ustuni ma'lumot emas, yo'naltirgich — u past kontrastda
            // turishi kerak, aks holda ko'z birinchi navbatda unga tushadi.
            '& .MuiDataGrid-cell[data-field="__rownum"]': { bgcolor: 'm3.surfaceContainerLow' },
            '& .MuiDataGrid-row': {
              cursor: onRowClick ? 'pointer' : 'default',
              transition: (theme) => theme.transitions.create('background-color', { duration: 120 }),
            },
            '& .MuiDataGrid-row:hover': { bgcolor: 'action.hover' },
            '& .MuiDataGrid-overlayWrapper': { height: 'auto !important', minHeight: 260 },
            ...(gridSx || {}),
          }}
          {...rest}
        />
      </Box>

      {showFooter && (
        <TableFooter
          cursorNav={cursorNav}
          // Mijoz tomonda umumiy son — yuklangan qatorlar soni.
          rowCount={serverSide ? rowCount : rows.length}
          rowsOnPage={
            serverSide || cursorNav
              ? rows.length
              : Math.min(
                  effectivePagination.pageSize,
                  Math.max(0, rows.length - effectivePagination.page * effectivePagination.pageSize),
                )
          }
          paginationModel={effectivePagination}
          onPaginationModelChange={setPagination}
          fetching={fetching}
        />
      )}
    </Card>
  )
}

/**
 * Yagona futer — offset va kursor rejimlari uchun bir xil ko'rinish.
 *
 * Offset rejimida raqamli sahifalar chiziladi: admin 7-sahifaga bir
 * bosishda o'tadi. Kursor rejimida bu MUMKIN EMAS — o'sha sahifaga
 * olib boradigan kursor faqat ketma-ket o'tish orqali topiladi, shuning
 * uchun u yerda faqat oldinga/orqaga bor. Ikkalasi bir xil joyda va bir
 * xil uslubda turadi, ya'ni farq faqat imkoniyatda, ko'rinishda emas.
 *
 * `TablePager` nomi bilan eksport qilinadi: DataGrid'siz ro'yxatlar
 * (sessiya tab'lari, dashboard jadvali) ham AYNAN shu futerni ishlatadi.
 */
function TableFooter({
  cursorNav, rowCount, rowsOnPage, paginationModel, onPaginationModelChange, fetching,
}) {
  const pageSize = cursorNav ? cursorNav.pageSize : paginationModel?.pageSize || 25
  const page = paginationModel?.page || 0

  const handlePageSize = (value) => {
    if (cursorNav) cursorNav.onPageSizeChange?.(value)
    else onPaginationModelChange?.({ page: 0, pageSize: value })
  }

  const pageCount = cursorNav ? 0 : Math.max(1, Math.ceil((rowCount || 0) / pageSize))
  const from = rowsOnPage === 0 ? 0 : page * pageSize + 1
  const to = page * pageSize + rowsOnPage
  const cursorFrom = (cursorNav?.pageIndex || 0) * pageSize + 1

  return (
    // Telefonda ham BITTA qatorda (o'raladi): ustunga yig'ilganda futer
    // ~150 px bo'lib, "Sahifada" maydoni butun kenglikka cho'zilardi.
    <Stack
      direction="row"
      flexWrap="wrap"
      useFlexGap
      columnGap={1.5}
      rowGap={1}
      alignItems="center"
      sx={{ px: { xs: 1.5, sm: 2 }, py: 1.25, borderTop: 1, borderColor: 'divider', bgcolor: 'm3.surfaceContainerLow' }}
    >
      <TextField
        select
        size="small"
        label="Sahifada"
        value={pageSize}
        onChange={(event) => handlePageSize(Number(event.target.value))}
        sx={{ width: 110, flexShrink: 0 }}
      >
        {PAGE_SIZES.map((size) => (
          <MenuItem key={size} value={size}>{size}</MenuItem>
        ))}
      </TextField>

      <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
        {cursorNav
          ? // Umumiy son ataylab so'ralmaydi (milliardlab qatorda
            // `COUNT(*)` qimmat), shuning uchun "N dan" o'rniga oraliq.
            `${cursorFrom}–${cursorFrom + rowsOnPage - 1}`
          : `${from}–${to} / ${rowCount ?? 0} ta`}
      </Typography>

      <Box sx={{ flex: 1 }} />

      {cursorNav ? (
        <Stack direction="row" spacing={0.5} alignItems="center">
          <Tooltip title="Oldingi sahifa">
            <span>
              <IconButton
                size="small"
                disabled={!cursorNav.hasPrevious || fetching}
                onClick={cursorNav.onPrevious}
                aria-label="Oldingi sahifa"
              >
                <ChevronLeftIcon />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Keyingi sahifa">
            <span>
              <IconButton
                size="small"
                disabled={!cursorNav.hasNext || fetching}
                onClick={cursorNav.onNext}
                aria-label="Keyingi sahifa"
              >
                <ChevronRightIcon />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      ) : (
        <Pagination
          count={pageCount}
          page={page + 1}
          onChange={(_, value) => onPaginationModelChange?.({ page: value - 1, pageSize })}
          size="small"
          shape="rounded"
          color="primary"
          siblingCount={1}
          boundaryCount={1}
          disabled={fetching}
          // Bitta sahifa bo'lsa boshqaruv keraksiz shovqin — lekin
          // futer o'zi qoladi, chunki "Sahifada" va yozuvlar soni
          // baribir kerak.
          sx={{ display: pageCount <= 1 ? 'none' : 'block' }}
        />
      )}
    </Stack>
  )
}

export { TableFooter as TablePager }
