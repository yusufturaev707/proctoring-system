import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge, Box, Button, Collapse, Divider, IconButton, InputAdornment, ListItemIcon,
  MenuItem, Menu, Stack, Switch, TextField, Tooltip, Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/EditOutlined'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import RestoreIcon from '@mui/icons-material/RestoreFromTrashOutlined'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import ClearIcon from '@mui/icons-material/ClearOutlined'
import FilterIcon from '@mui/icons-material/FilterListOutlined'
import RefreshIcon from '@mui/icons-material/RefreshOutlined'
import MoreIcon from '@mui/icons-material/MoreVertOutlined'
import DownloadIcon from '@mui/icons-material/FileDownloadOutlined'
import LinkIcon from '@mui/icons-material/LinkOutlined'

import PageHeader from '../PageHeader'
import DataTable from './DataTable'
import ResourceForm from './ResourceForm'
import ConfirmDialog from '../ConfirmDialog'
import { TableSkeleton } from '../feedback/Skeletons'
import { useDeferredLoading } from '../motion/Transitions'
import { useResource } from './useResource'
import { useAuth } from '../../context/AuthContext'
import { exportCsv } from '../../utils/exportCsv'
import { useUi } from '../../context/UiContext'
import { FILTER_FIELD_SX } from './responsive'

/**
 * Model uchun to'liq CRUD sahifasi.
 *
 * Bir joyda: qidiruv, filtrlar, server sahifalash/saralash, forma,
 * o'chirish tasdig'i, ruxsat tekshiruvi, eksport va klaviatura. Har bir
 * model uchun bularni qayta yozish 300+ qator takrorlangan kod va har
 * birida boshqacha xato demak.
 */
export default function ResourcePage({
  title,
  subtitle,
  queryKey,
  api,
  columns,
  fields,
  permission,
  defaults = {},
  /**
   * Model `SoftDeleteModel` bo'lsa `true`. Shunda:
   *   - "O'chirilganlar" filtri paydo bo'ladi (`?deleted=only|all`);
   *   - o'chirilgan qatorda tahrirlash/o'chirish o'rniga "Tiklash".
   * Backendda `SoftDeleteRestoreMixin` ulangan bo'lishi shart.
   */
  restorable = false,
  filters: filterDefs = [],
  defaultFilters,
  searchPlaceholder = 'Qidirish…',
  searchable = true,
  defaultSort,
  staticParams,
  /** Ro'yxatni o'zi yangilash oralig'i (ms) — `useResource` ga uzatiladi. */
  refetchInterval = false,
  height = 620,
  rowActions,
  // Amallar ustuni kengligi: bir nechta tugmali sahifalar uchun.
  actionsWidth = 170,
  deleteConfirmPhrase,
  deleteDescription = 'Bu amalni qaytarib bo‘lmaydi.',
  getRowLabel = (row) => row?.name || `#${row?.id}`,
  emptyDescription,
  formMaxWidth = 'sm',
  formDescription,
  formContext = {},
  canCreate = true,
  canDelete = true,
  /**
   * Tahrirlash tugmasi. Audit kabi o'zgartirib bo'lmaydigan resurslarda
   * `false` — aks holda ekranda hech qachon ishlamaydigan tugma qoladi.
   */
  canEdit = true,
  onRowClick,
  /**
   * Ro'yxatdan turib bitta mantiqiy maydonni almashtirish
   * (masalan `is_active`). Optimistik: UI darhol o'zgaradi, server
   * rad etsa avvalgi holat qaytariladi.
   */
  toggleField,
  toggleLabel = 'Faol',
  /** Eksport fayl nomi. Berilmasa `queryKey` ishlatiladi. */
  exportName,
  headerActions,
  /**
   * Sarlavha bilan jadval orasidagi izoh (odatda `Alert`).
   *
   * Jadvaldan KEYIN qo'yilganda u 600 px balandlikdagi gridning ostida
   * qolib ketadi va hech kim o'qimaydi — kontekst esa aynan jadvalni
   * ko'rishdan oldin kerak.
   */
  banner,
  /**
   * Yozuv BARCHA viloyatlar uchun bitta (rol, sozlama, imtihon). Shunda
   * o'zgartirish faqat respublika darajasida — backend `RepublicLevelWrite`
   * bilan bir xil qoida (`AuthContext.canShared`).
   */
  shared = false,
}) {
  const { can, canShared, user } = useAuth()
  const { notify } = useUi()
  const canManage = shared ? canShared(permission) : can(permission)

  const resource = useResource({
    key: queryKey,
    api,
    defaultSort,
    defaultFilters,
    staticParams,
    searchable,
    refetchInterval,
    urlNamespace: '',
  })
  const showSkeleton = useDeferredLoading(resource.isLoading)

  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [filtersOpen, setFiltersOpen] = useState(false)

  // "Savat" filtri. Server `?deleted=` parametrini kutadi
  // (`SoftDeleteRestoreMixin`): standart holat — faqat tiriklar,
  // shuning uchun bo'sh qiymat ham to'g'ri ishlaydi.
  const allFilterDefs = useMemo(
    () =>
      restorable
        ? [
            ...filterDefs,
            {
              name: 'deleted',
              label: 'Savat',
              type: 'select',
              options: [
                { value: 'only', label: 'Faqat o‘chirilganlar' },
                { value: 'all', label: 'Hammasi' },
              ],
            },
          ]
        : filterDefs,
    [filterDefs, restorable],
  )
  // Viloyat foydalanuvchisiga viloyat filtri KO'RSATILMAYDI (`regionScope`):
  // server unga faqat o'z viloyatini beradi va bitta variantli tanlov
  // ekranda joy egallab, "boshqa viloyatni ham ko'ra olamanmi?" degan
  // noto'g'ri savol tug'dirardi. Bog'liq bino filtri o'shanda barcha
  // binolarni ko'rsatadi — ular baribir shu viloyatniki.
  const visibleFilterDefs = useMemo(
    () => allFilterDefs.filter((filter) => !(filter.regionScope && user?.is_region_scoped)),
    [allFilterDefs, user],
  )

  /**
   * Filtr qiymati + unga BOG'LIQ filtrlarni tozalash (`resets`).
   *
   * Viloyat almashganda eski bino qoldirilsa, so'rov "Andijon viloyati +
   * Toshkentdagi bino" bo'lib ketardi va jadval sababsiz bo'sh chiqardi.
   */
  const changeFilter = useCallback(
    (filter, value) => {
      resource.setFilters((prev) => {
        const next = { ...prev, [filter.name]: value }
        for (const child of filter.resets || []) next[child] = ''
        return next
      })
    },
    [resource],
  )
  const [menuAnchor, setMenuAnchor] = useState(null)
  const searchRef = useRef(null)

  const activeFilterCount = useMemo(
    () => Object.values(resource.filters).filter((value) => value !== '' && value != null).length,
    [resource.filters],
  )

  const openCreate = useCallback(() => {
    resource.clearServerError()
    setEditing({})
  }, [resource])

  const openEdit = useCallback((row) => {
    resource.clearServerError()
    setEditing(row)
  }, [resource])

  // Filtrlar to'plami bo'sh bo'lmasa panelni ochiq holda ko'rsatamiz —
  // havola orqali kelgan odam qaysi filtr qo'llanganini darrov ko'rsin,
  // "nega ro'yxat qisqa" degan savol tug'ilmasin.
  const hadInitialFilters = useRef(activeFilterCount > 0)
  useEffect(() => {
    if (hadInitialFilters.current) setFiltersOpen(true)
  }, [])

  /**
   * Klaviatura: `/` qidiruvga o'tadi, `n` yangi yozuv ochadi.
   *
   * Kun bo'yi shu ekranda ishlaydigan odam uchun sichqonchaga uzatilgan
   * har bir harakat qimmat. Maydon ichida yozayotganda yorliqlar
   * ishlamaydi — aks holda "n" harfini yozib bo'lmaydi.
   */
  useEffect(() => {
    const handler = (event) => {
      const target = event.target
      const typing =
        target?.isContentEditable ||
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName)
      if (typing || event.ctrlKey || event.metaKey || event.altKey) return
      if (editing || deleting) return

      if (event.key === '/' && searchable) {
        event.preventDefault()
        searchRef.current?.focus()
      } else if (event.key === 'n' && canManage && canCreate) {
        event.preventDefault()
        openCreate()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [editing, deleting, searchable, canManage, canCreate, openCreate])

  const handleSubmit = useCallback(
    (payload) => {
      const onDone = { onSuccess: () => setEditing(null) }
      if (payload.id) resource.update(payload, onDone)
      else resource.create(payload, onDone)
    },
    [resource],
  )

  const baseColumns = useMemo(
    () => (typeof columns === 'function' ? columns({ resource, canManage }) : columns),
    [columns, resource, canManage],
  )

  const gridColumns = useMemo(() => {
    const result = [...baseColumns]

    if (toggleField) {
      result.push({
        field: toggleField,
        headerName: toggleLabel,
        width: 105,
        sortable: false,
        filterable: false,
        // Ruxsati yo'q foydalanuvchiga ustunni butunlay yashirmaymiz —
        // holatni KO'RISH huquqi bor, faqat o'zgartirish yo'q. Yashirilsa
        // "nega bu yozuv ishlamayapti" degan savol javobsiz qoladi.
        renderCell: (params) => (
          <Tooltip title={canManage ? '' : 'O‘zgartirish uchun ruxsat yo‘q'}>
            <span>
              <Switch
                size="small"
                checked={Boolean(params.value)}
                disabled={!canManage}
                onClick={(event) => event.stopPropagation()}
                onChange={(event) =>
                  resource.patch({ id: params.row.id, [toggleField]: event.target.checked })
                }
                inputProps={{ 'aria-label': `${toggleLabel}: ${getRowLabel(params.row)}` }}
              />
            </span>
          </Tooltip>
        ),
      })
    }

    const hasActions = canManage && (canEdit || canDelete || Boolean(rowActions))
    if (!hasActions) return result

    return [
      ...result,
      {
        field: '__actions',
        headerName: '',
        width: rowActions ? actionsWidth : 96,
        sortable: false,
        filterable: false,
        align: 'right',
        headerAlign: 'right',
        renderCell: (params) => {
          // O'chirilgan qatorda tahrirlash ham, qayta o'chirish ham
          // ma'nosiz — yagona mumkin bo'lgan amal tiklash.
          if (restorable && params.row.deleted_at) {
            return (
              <Stack direction="row" onClick={(event) => event.stopPropagation()}>
                <Tooltip title="Tiklash">
                  <IconButton
                    size="small"
                    color="success"
                    onClick={() => resource.restore(params.row.id)}
                  >
                    <RestoreIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
            )
          }
          return (
            <Stack direction="row" spacing={0.25} onClick={(event) => event.stopPropagation()}>
              {rowActions?.(params.row, resource)}
              {canEdit && (
                <Tooltip title="Tahrirlash">
                  <IconButton size="small" onClick={() => openEdit(params.row)}>
                    <EditIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              {canDelete && (
                <Tooltip title="O‘chirish">
                  <IconButton size="small" color="error" onClick={() => setDeleting(params.row)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            </Stack>
          )
        },
      },
    ]
  }, [
    baseColumns, canManage, rowActions, actionsWidth, resource, openEdit, canDelete, canEdit,
    toggleField, toggleLabel, getRowLabel, restorable,
  ])

  const handleExport = useCallback(() => {
    // Ataylab FAQAT joriy sahifa eksport qilinadi. "Hammasini yuklab
    // olish" tugmasi milliondan ortiq qatorli jadvalda brauzerni ham,
    // serverni ham yiqitadi — to'liq eksport backend vazifasi bo'lishi
    // kerak (fon jarayoni + fayl havolasi).
    exportCsv(baseColumns, resource.rows, exportName || queryKey)
    notify(`${resource.rows.length} ta qator CSV ga saqlandi`)
    setMenuAnchor(null)
  }, [baseColumns, resource.rows, exportName, queryKey, notify])

  const handleCopyLink = useCallback(async () => {
    setMenuAnchor(null)
    try {
      await navigator.clipboard.writeText(window.location.href)
      notify('Havola nusxalandi — filtrlar bilan birga ochiladi')
    } catch {
      notify('Havolani nusxalab bo‘lmadi', 'warning')
    }
  }, [notify])

  const toolbar = (
    <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
      {/* Telefonda qidiruv BUTUN qatorni oladi, tugmalar keyingi qatorga
          o'tadi. Ilgari hammasi bitta qatorda edi va 390 px ekranda
          qidiruv maydoniga ~110 px qolardi — placeholder "Raq…" bo'lib,
          nima bo'yicha qidirish mumkinligi ko'rinmasdi. */}
      <Stack
        direction="row"
        alignItems="center"
        flexWrap="wrap"
        useFlexGap
        columnGap={1.5}
        rowGap={1.25}
        sx={{ p: { xs: 1.5, sm: 2 } }}
      >
        {searchable && (
          <TextField
            inputRef={searchRef}
            value={resource.search}
            onChange={(event) => resource.setSearch(event.target.value)}
            placeholder={searchPlaceholder}
            sx={{ flex: { xs: '1 1 100%', sm: '0 1 320px' }, maxWidth: { sm: 320 } }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" color="disabled" />
                </InputAdornment>
              ),
              endAdornment: resource.search ? (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => resource.setSearch('')} tabIndex={-1}>
                    <ClearIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : (
                // Telefonda klaviatura yorlig'i ma'nosiz — `/` tugmasi yo'q.
                <InputAdornment position="end" sx={{ display: { xs: 'none', md: 'flex' } }}>
                  <Box
                    component="kbd"
                    sx={{
                      px: 0.75, py: 0.1, borderRadius: '6px', fontSize: 11,
                      border: 1, borderColor: 'divider', color: 'text.disabled',
                      fontFamily: 'monospace', lineHeight: 1.6,
                    }}
                  >
                    /
                  </Box>
                </InputAdornment>
              ),
            }}
          />
        )}

        {visibleFilterDefs.length > 0 && (
          <Badge badgeContent={activeFilterCount} color="primary">
            <Button
              variant={filtersOpen ? 'contained' : 'outlined'}
              startIcon={<FilterIcon />}
              onClick={() => setFiltersOpen((prev) => !prev)}
              size="medium"
            >
              Filtr
            </Button>
          </Badge>
        )}

        <Box sx={{ flex: 1 }} />

        {/* Yozuvlar soni futerda ko'rsatiladi — jadval balandligi qat'iy
            bo'lgani uchun futer doim ko'rinib turadi, ya'ni uni bu yerda
            takrorlash ortiqcha shovqin. */}

        {/* O'chirilgan tugma hodisa yubormaydi — Tooltip uni `span`
            o'ramisiz "ushlay" olmaydi va MUI ogohlantirish beradi. */}
        <Tooltip title="Yangilash">
          <span>
            <IconButton onClick={() => resource.refetch()} disabled={resource.isFetching}>
              <RefreshIcon />
            </IconButton>
          </span>
        </Tooltip>

        <Tooltip title="Boshqa amallar">
          <IconButton onClick={(event) => setMenuAnchor(event.currentTarget)}>
            <MoreIcon />
          </IconButton>
        </Tooltip>

        <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)}>
          <MenuItem onClick={handleExport} disabled={!resource.rows.length}>
            <ListItemIcon><DownloadIcon fontSize="small" /></ListItemIcon>
            Joriy sahifani CSV ga
          </MenuItem>
          <MenuItem onClick={handleCopyLink}>
            <ListItemIcon><LinkIcon fontSize="small" /></ListItemIcon>
            Filtrli havolani nusxalash
          </MenuItem>
        </Menu>
      </Stack>

      <Collapse in={filtersOpen}>
        <Divider />
        <Stack
          direction="row"
          spacing={2}
          flexWrap="wrap"
          useFlexGap
          sx={{ px: { xs: 1.5, sm: 2 }, pb: 2, pt: 2, bgcolor: 'm3.surfaceContainerLow' }}
        >
          {visibleFilterDefs.map((filter) => {
            // `options` funksiya bo'lsa — joriy filtrlardan (viloyat ->
            // shu viloyatning binolari), `formFields` dagi naqsh bilan bir xil.
            const options = typeof filter.options === 'function'
              ? filter.options(resource.filters)
              : filter.options || []
            return (
              <TextField
                key={filter.name}
                select={filter.type === 'select'}
                type={filter.type === 'select' ? undefined : filter.type || 'text'}
                label={filter.label}
                value={resource.filters[filter.name] ?? ''}
                onChange={(event) => changeFilter(filter, event.target.value)}
                sx={FILTER_FIELD_SX}
                InputLabelProps={filter.type === 'date' ? { shrink: true } : undefined}
                SelectProps={filter.type === 'select' ? { MenuProps: { PaperProps: { sx: { maxHeight: 420 } } } } : undefined}
              >
                {filter.type === 'select' &&
                  [{ value: '', label: filter.allLabel || 'Barchasi' }, ...options].map((option) => (
                    <MenuItem key={String(option.value)} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
              </TextField>
            )
          })}
          {activeFilterCount > 0 && (
            <Button color="inherit" startIcon={<ClearIcon />} onClick={resource.resetFilters}>
              Tozalash
            </Button>
          )}
        </Stack>
      </Collapse>
    </Box>
  )

  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        actions={
          <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0, maxWidth: '100%' }}>
            {headerActions}
            {canManage && canCreate && (
              <Tooltip title="Klaviaturada: N">
                <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
                  Qo‘shish
                </Button>
              </Tooltip>
            )}
          </Stack>
        }
      />

      {banner && <Box sx={{ mb: 2.5 }}>{banner}</Box>}

      {showSkeleton ? (
        <TableSkeleton rows={8} columns={Math.min(gridColumns.length, 7)} />
      ) : (
        <DataTable
          rows={resource.rows}
          columns={gridColumns}
          loading={resource.isLoading}
          fetching={resource.isFetching}
          error={resource.error}
          onRetry={resource.refetch}
          onRowClick={onRowClick}
          rowCount={resource.total}
          paginationModel={resource.paginationModel}
          onPaginationModelChange={resource.setPaginationModel}
          sortModel={resource.sortModel}
          onSortModelChange={resource.setSortModel}
          height={height}
          toolbar={toolbar}
          cursorNav={
            resource.isCursorMode
              ? {
                  hasNext: resource.hasNext,
                  hasPrevious: resource.hasPrevious,
                  onNext: resource.goNextPage,
                  onPrevious: resource.goPreviousPage,
                  pageIndex: resource.cursorPageIndex,
                  pageSize: resource.paginationModel.pageSize,
                  onPageSizeChange: (size) =>
                    resource.setPaginationModel((prev) => ({ ...prev, pageSize: size })),
                }
              : undefined
          }
          emptyDescription={
            emptyDescription ||
            (activeFilterCount || resource.search
              ? 'Filtr shartlariga mos yozuv yo‘q'
              : 'Hozircha yozuvlar mavjud emas')
          }
          emptyAction={
            canManage && canCreate && !activeFilterCount && !resource.search
              ? { label: 'Birinchi yozuvni qo‘shish', onClick: openCreate }
              : activeFilterCount || resource.search
                ? { label: 'Filtrni tozalash', onClick: resource.resetFilters }
                : undefined
          }
        />
      )}

      <ResourceForm
        open={Boolean(editing)}
        row={editing?.id ? editing : null}
        fields={fields}
        defaults={defaults}
        submitting={resource.isSaving}
        serverError={resource.serverError}
        onSubmit={handleSubmit}
        onClose={() => setEditing(null)}
        maxWidth={formMaxWidth}
        description={formDescription}
        context={formContext}
      />

      <ConfirmDialog
        open={Boolean(deleting)}
        title="O‘chirishni tasdiqlang"
        description={deleteDescription}
        details={
          deleting ? (
            <Stack spacing={0.5}>
              <Typography variant="caption" color="text.secondary">O‘chiriladigan yozuv</Typography>
              <Typography variant="body2" fontWeight={600}>{getRowLabel(deleting)}</Typography>
            </Stack>
          ) : null
        }
        color="error"
        confirmLabel="O‘chirish"
        confirmPhrase={deleteConfirmPhrase ? getRowLabel(deleting) : null}
        loading={resource.isDeleting}
        onConfirm={() => resource.remove(deleting.id, { onSuccess: () => setDeleting(null) })}
        onClose={() => setDeleting(null)}
      />
    </>
  )
}

export { ResourcePage }
