import { useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Badge, Box, Button, Chip, IconButton, InputAdornment, MenuItem, Stack,
  TextField, Tooltip, Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/SearchOutlined'
import ClearIcon from '@mui/icons-material/ClearOutlined'
import RefreshIcon from '@mui/icons-material/RefreshOutlined'
import DownloadIcon from '@mui/icons-material/FileDownloadOutlined'

import PageHeader from '../components/PageHeader'
import DataTable from '../components/data/DataTable'
import { TableSkeleton } from '../components/feedback/Skeletons'
import { useDeferredLoading } from '../components/motion/Transitions'
import { RiskBar, StatusChip } from '../components/StatusChip'
import { useResource } from '../components/data/useResource'
import { useAuth } from '../context/AuthContext'
import { exportCsv } from '../utils/exportCsv'
import { useExamOptions, useRegionOptions, useZoneOptions, zonesOfRegion } from './crud/shared'
import { sessions as sessionsApi } from '../api/endpoints'
import { STATUS_LABEL } from '../theme'
import { computerLabel } from '../utils/labels'
import { filterFieldSx } from '../components/data/responsive'

const URL_FILTERS = ['status', 'zone__region', 'zone', 'exam', 'exam_date']

export default function Sessions() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { can, user } = useAuth()
  const { options: zoneOptions } = useZoneOptions()
  const { options: regionOptions } = useRegionOptions()
  // Viloyat xodimi faqat o'z viloyatini ko'radi — viloyat tanlovi ma'nosiz.
  const showRegion = !user?.is_region_scoped
  const { options: examOptions } = useExamOptions()

  const resource = useResource({
    key: 'sessions',
    api: sessionsApi,
    defaultSort: { field: 'created_at', sort: 'desc' },
  })

  const { setFilters } = resource
  const showSkeleton = useDeferredLoading(resource.isLoading)

  // Dashboard'dan «Chetlashtirilgan» kartasini bosganda `?status=terminated`
  // bilan keladi — filtr avtomatik qo'llanadi. Bu drill-down zanjirini
  // uzluksiz qiladi: ko'rsatkich -> aynan o'sha yozuvlar.
  useEffect(() => {
    const fromUrl = {}
    URL_FILTERS.forEach((name) => {
      const value = searchParams.get(name)
      if (value) fromUrl[name] = value
    })
    if (Object.keys(fromUrl).length > 0) setFilters(fromUrl)
  }, [searchParams, setFilters])

  /**
   * `resets` — bog'liq filtrlar: viloyat almashsa eski bino tozalanadi,
   * aks holda so'rov "Andijon + Toshkentdagi bino" bo'lib, jadval
   * sababsiz bo'sh chiqardi.
   */
  const setFilter = (name, resets = []) => (event) => {
    const value = event.target.value
    resource.setFilters((prev) => {
      const nextFilters = { ...prev, [name]: value }
      resets.forEach((child) => { nextFilters[child] = '' })
      return nextFilters
    })
    // URL'ni ham yangilaymiz — havolani ulashsa, filtr saqlanadi.
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    resets.forEach((child) => next.delete(child))
    setSearchParams(next, { replace: true })
  }

  const regionFilter = resource.filters.zone__region
  const zoneChoices = regionFilter ? zonesOfRegion(zoneOptions, regionFilter) : zoneOptions

  const clearAll = () => {
    resource.resetFilters()
    setSearchParams({}, { replace: true })
  }

  const activeCount = useMemo(
    () => Object.values(resource.filters).filter((value) => value !== '' && value != null).length,
    [resource.filters],
  )

  const columns = useMemo(
    () => [
      { field: 'candidate_name', headerName: 'Talabgor', flex: 1.4, minWidth: 190, sortable: false },
      { field: 'pinfl', headerName: 'JSHSHIR', width: 165, sortable: false },
      { field: 'exam_name', headerName: 'Imtihon', flex: 1, minWidth: 150, sortable: false },
      // Viloyat xodimida hamma qator bir xil viloyat — ustun joy yeydi, xolos.
      ...(showRegion ? [{ field: 'region_name', headerName: 'Viloyat', width: 145, sortable: false }] : []),
      { field: 'zone_name', headerName: 'Bino', width: 125, sortable: false },
      {
        field: 'computer_code', headerName: 'Kompyuter', width: 140, sortable: false,
        valueGetter: (value, row) => computerLabel(row.computer_number, value),
      },
      {
        field: 'attempt_no', headerName: 'Urinish', width: 85,
        align: 'center', headerAlign: 'center', sortable: false,
        renderCell: (params) =>
          params.value > 1
            ? <Chip size="small" color="warning" variant="outlined" label={params.value} />
            : <Typography variant="body2" color="text.secondary">{params.value}</Typography>,
      },
      {
        field: 'status', headerName: 'Holat', width: 160, sortable: false,
        renderCell: (params) => <StatusChip status={params.value} label={params.row.status_display} />,
      },
      {
        field: 'risk_score', headerName: 'Xavf', width: 125,
        renderCell: (params) => <RiskBar value={params.value || 0} />,
      },
      {
        field: 'event_count', headerName: 'Hodisa', width: 95,
        align: 'right', headerAlign: 'right', sortable: false,
      },
      // «Boshlangan»/«Tugagan» ro'yxatda YO'Q: ikkita 170 px li ustun
      // jadvalni gorizontal skrollga majbur qilardi va proktor ro'yxatda
      // ularni izlamaydi — vaqt savoli bitta sessiyaga qaralganda
      // tug'iladi va tafsilot sahifasida bor.
    ],
    [showRegion],
  )

  const toolbar = (
    <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
      <Stack
        direction="row"
        columnGap={1.5}
        rowGap={1.25}
        alignItems="center"
        flexWrap="wrap"
        useFlexGap
        sx={{ p: { xs: 1.5, sm: 2 } }}
      >
        <TextField
          value={resource.search}
          onChange={(event) => resource.setSearch(event.target.value)}
          placeholder="IP, MAC yoki tashqi ID…"
          sx={{ flex: { xs: '1 1 100%', sm: '0 1 250px' }, maxWidth: { sm: 250 } }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start"><SearchIcon fontSize="small" color="disabled" /></InputAdornment>
            ),
          }}
        />

        <TextField
          select label="Holat" value={resource.filters.status ?? ''}
          onChange={setFilter('status')} sx={filterFieldSx(180, 200, { half: true })}
        >
          <MenuItem value="">Barchasi</MenuItem>
          {Object.entries(STATUS_LABEL).map(([value, label]) => (
            <MenuItem key={value} value={value}>{label}</MenuItem>
          ))}
        </TextField>

        {showRegion && (
          <TextField
            select label="Viloyat" value={regionFilter ?? ''}
            onChange={setFilter('zone__region', ['zone'])} sx={filterFieldSx(180, 220, { half: true })}
          >
            <MenuItem value="">Barchasi</MenuItem>
            {regionOptions.map((option) => (
              <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
            ))}
          </TextField>
        )}

        <TextField
          select label="Bino" value={resource.filters.zone ?? ''}
          onChange={setFilter('zone')} sx={filterFieldSx(190, 240, { half: true })}
          SelectProps={{ MenuProps: { PaperProps: { sx: { maxHeight: 420 } } } }}
        >
          <MenuItem value="">Barchasi</MenuItem>
          {zoneChoices.map((option) => (
            <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
          ))}
        </TextField>

        <TextField
          select label="Imtihon" value={resource.filters.exam ?? ''}
          onChange={setFilter('exam')} sx={filterFieldSx(180, 220, { half: true })}
        >
          <MenuItem value="">Barchasi</MenuItem>
          {examOptions.map((option) => (
            <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
          ))}
        </TextField>

        <TextField
          type="date" label="Sana" value={resource.filters.exam_date ?? ''}
          onChange={setFilter('exam_date')} InputLabelProps={{ shrink: true }}
          sx={filterFieldSx(165, 180, { half: true })}
        />

        {activeCount > 0 && (
          <Badge badgeContent={activeCount} color="primary">
            <Button color="inherit" startIcon={<ClearIcon />} onClick={clearAll}>Tozalash</Button>
          </Badge>
        )}

        <Box sx={{ flex: 1 }} />

        {/* Eksport ALOHIDA ruxsat talab qiladi (`sessions.export`).
            Ro'yxatda talabgorlarning F.I.Sh. si bor va uni faylga
            chiqarish — sessiyani ekranda ko'rishdan boshqacha amal:
            fayl tizimdan chiqib ketadi va nazoratdan tashqarida
            tarqalishi mumkin. Sessiyani ko'ra oladigan har bir rol
            (masalan Kuzatuvchi) buni qila olmaydi. */}
        {can('sessions.export') && (
          <Tooltip title="Joriy sahifani CSV ga saqlash">
            <span>
              <IconButton
                onClick={() => exportCsv(columns, resource.rows, 'sessiyalar')}
                disabled={!resource.rows.length}
              >
                <DownloadIcon />
              </IconButton>
            </span>
          </Tooltip>
        )}

        {/* Yozuvlar soni futerda — bu yerda takrorlanmaydi. */}
        <Tooltip title="Yangilash">
          <span>
            <IconButton onClick={() => resource.refetch()} disabled={resource.isFetching}>
              <RefreshIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
    </Box>
  )

  return (
    <>
      <PageHeader
        title="Sessiyalar"
        subtitle="Barcha imtihon sessiyalari arxivi — qatorni bosib tafsilotlarni ko‘ring"
      />

      {showSkeleton ? (
        <TableSkeleton rows={9} columns={7} />
      ) : (
        <DataTable
          rows={resource.rows}
          columns={columns}
          loading={resource.isLoading}
          fetching={resource.isFetching}
          error={resource.error}
          onRetry={resource.refetch}
          rowCount={resource.total}
          paginationModel={resource.paginationModel}
          onPaginationModelChange={resource.setPaginationModel}
          sortModel={resource.sortModel}
          onSortModelChange={resource.setSortModel}
          onRowClick={(params) => navigate(`/sessions/${params.id}`)}
          height={640}
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
            activeCount || resource.search
              ? 'Filtr shartlariga mos sessiya topilmadi'
              : 'Bugun hali sessiya boshlanmagan'
          }
          emptyAction={
            activeCount || resource.search ? { label: 'Filtrni tozalash', onClick: clearAll } : undefined
          }
        />
      )}
    </>
  )
}
