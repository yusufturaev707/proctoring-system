import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Badge, Box, Button, Card, CardContent, CardHeader, Chip, Divider,
  Grid, IconButton, List, ListItem, ListItemText, MenuItem, Stack, TextField,
  Tooltip, Typography,
} from '@mui/material'
import CampaignIcon from '@mui/icons-material/CampaignOutlined'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import OpenIcon from '@mui/icons-material/OpenInNewOutlined'
import ClearIcon from '@mui/icons-material/ClearAllOutlined'
import WifiIcon from '@mui/icons-material/WifiTetheringOutlined'
import WifiOffIcon from '@mui/icons-material/WifiTetheringOffOutlined'

import PageHeader from '../components/PageHeader'
import DataTable from '../components/data/DataTable'
import ConfirmDialog from '../components/ConfirmDialog'
import { OnlineDot, RiskBar, SeverityChip, StatusChip } from '../components/StatusChip'
import { useLiveMonitor } from '../hooks/useLiveMonitor'
import { useUi } from '../context/UiContext'
import { useAuth } from '../context/AuthContext'
import {
  sessions as sessionsApi, zones as zonesApi, exams as examsApi,
  examSchedules as schedulesApi, regions as regionsApi,
} from '../api/endpoints'
import { EVENT_LABEL, formatTime, fromNow } from '../utils/labels'

/** Bugungi sana `YYYY-MM-DD` ko'rinishida (mahalliy vaqt bo'yicha). */
const today = () => {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60000
  return new Date(now - offset).toISOString().slice(0, 10)
}

/**
 * Jonli kuzatuv.
 *
 * Ikki manbadan yangilanadi:
 *   - REST polling (10s) — to'liq ro'yxat, xavf bo'yicha tartiblangan;
 *   - WebSocket — hodisa oqimi va holat o'zgarishlari (darhol).
 *
 * Nima uchun ikkalasi: WebSocket faqat O'ZGARISHLARNI yuboradi, boshlang'ich
 * holat kerak. Polling esa ulanish uzilganda zaxira sifatida ishlaydi.
 */
export default function LiveMonitor() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { can, user } = useAuth()

  // Viloyatga biriktirilgan xodim faqat o'z viloyatini ko'radi — bu
  // backendda majburlanadi, bu yerda esa tanlov shunchaki qulflanadi.
  const lockedRegion = !user?.is_superuser && user?.region ? String(user.region) : ''

  const [examFilter, setExamFilter] = useState('')
  const [dateFilter, setDateFilter] = useState(today)
  const [regionFilter, setRegionFilter] = useState(lockedRegion)
  const [zoneFilter, setZoneFilter] = useState('')
  const [warnTarget, setWarnTarget] = useState(null)
  const [terminateTarget, setTerminateTarget] = useState(null)

  const { data: zonesData } = useQuery({ queryKey: ['zones-all'], queryFn: () => zonesApi.list({ page_size: 200 }) })
  const { data: regionsData } = useQuery({
    queryKey: ['regions-all'],
    queryFn: () => regionsApi.list({ page_size: 100 }),
    enabled: !lockedRegion,
  })

  /**
   * Imtihon ro'yxati JADVALDAN olinadi, imtihonlar jadvalidan emas.
   *
   * Sabab: `Exam` — arxiv, unda o'tgan yillardagi o'nlab imtihon yotadi.
   * Proktor esa faqat bugun jadvalga qo'yilgani bilan ishlaydi. Shuning
   * uchun ro'yxat faol jadval yozuvlaridan yig'iladi va kirish oynasi
   * ochiq bo'lganlar tepaga chiqadi.
   *
   * Jadval umuman tuzilmagan bo'lsa (dastlabki o'rnatish) ro'yxat bo'sh
   * qolmasligi uchun imtihonlar to'g'ridan-to'g'ri olinadi.
   */
  const { data: schedulesData } = useQuery({
    queryKey: ['schedules-active', dateFilter],
    queryFn: () => schedulesApi.list({ is_active: true, exam_date: dateFilter, page_size: 200 }),
  })

  const { data: examsData } = useQuery({
    queryKey: ['exams-all'],
    queryFn: () => examsApi.list({ is_active: true, page_size: 100 }),
    enabled: (schedulesData?.results?.length ?? 0) === 0,
  })

  const examOptions = useMemo(() => {
    const schedules = schedulesData?.results || []
    if (schedules.length === 0) {
      return (examsData?.results || []).map((exam) => ({
        id: exam.id, name: exam.name, isOpen: false, scheduled: false,
      }))
    }
    const byExam = new Map()
    schedules.forEach((item) => {
      const current = byExam.get(item.exam)
      byExam.set(item.exam, {
        id: item.exam,
        name: item.exam_name,
        isOpen: Boolean(current?.isOpen) || Boolean(item.is_open),
        scheduled: true,
      })
    })
    return [...byExam.values()].sort(
      (a, b) => Number(b.isOpen) - Number(a.isOpen) || a.name.localeCompare(b.name),
    )
  }, [schedulesData, examsData])

  // Binolar — faqat tanlangan viloyatniki.
  const zoneOptions = useMemo(() => {
    const all = zonesData?.results || []
    if (!regionFilter) return all
    return all.filter((zone) => String(zone.region) === String(regionFilter))
  }, [zonesData, regionFilter])

  // Bino tanlanmagan bo'lsa — ko'rinadigan BARCHA binolarga obuna bo'lamiz.
  // Aks holda kanal "ulangan" ko'rinadi, lekin hech qanday hodisa kelmaydi:
  // backend hodisalarni `zone.<id>` guruhiga yuboradi, global kanal yo'q.
  //
  // Consumer bir ulanish uchun 50 ta guruh bilan cheklaydi (fan-out'ni
  // tiyish uchun), shuning uchun bu yerda ham shuncha olamiz.
  const subscribedZones = useMemo(() => {
    if (zoneFilter) return [Number(zoneFilter)]
    return zoneOptions.slice(0, 50).map((zone) => zone.id)
  }, [zoneFilter, zoneOptions])

  const { connected, events, updates, clearEvents } = useLiveMonitor({ zones: subscribedZones })

  const { data, isLoading } = useQuery({
    queryKey: ['live-sessions', examFilter, dateFilter, regionFilter, zoneFilter],
    queryFn: () =>
      sessionsApi.live({
        exam: examFilter || undefined,
        date: dateFilter || undefined,
        region: regionFilter || undefined,
        zone: zoneFilter || undefined,
        limit: 200,
      }),
    refetchInterval: 10000,
  })

  const warnMutation = useMutation({
    mutationFn: ({ id, message }) => sessionsApi.warn(id, { message, severity: 2 }),
    onSuccess: () => { notify('Ogohlantirish yuborildi'); setWarnTarget(null) },
    onError: notifyError,
  })

  const terminateMutation = useMutation({
    mutationFn: ({ id, reason }) => sessionsApi.terminate(id, { reason }),
    onSuccess: () => {
      notify('Sessiya chetlashtirildi')
      setTerminateTarget(null)
      queryClient.invalidateQueries({ queryKey: ['live-sessions'] })
    },
    onError: notifyError,
  })

  // WebSocket'dan kelgan yangilanishlarni REST ma'lumotiga qo'shamiz —
  // shunda proktor keyingi polling'ni kutmaydi.
  const rows = useMemo(() => {
    const list = data?.results || []
    return list.map((row) => {
      const patch = updates[row.id]
      return patch ? { ...row, ...patch } : row
    })
  }, [data, updates])

  const columns = useMemo(
    () => [
      {
        field: 'is_online', headerName: '', width: 44, sortable: false,
        renderCell: (params) => <OnlineDot online={params.value} />,
      },
      { field: 'candidate_name', headerName: 'Talabgor', flex: 1.4, minWidth: 190 },
      { field: 'masked_pinfl', headerName: 'JSHSHIR', width: 140 },
      { field: 'exam_name', headerName: 'Imtihon', flex: 1, minWidth: 140 },
      { field: 'zone_name', headerName: 'Bino', width: 120 },
      { field: 'computer_code', headerName: 'Kompyuter', width: 120 },
      {
        field: 'status', headerName: 'Holat', width: 150,
        renderCell: (params) => <StatusChip status={params.value} label={params.row.status_display} />,
      },
      {
        field: 'risk_score', headerName: 'Xavf', width: 120,
        renderCell: (params) => <RiskBar value={params.value || 0} />,
      },
      { field: 'event_count', headerName: 'Hodisa', width: 90, align: 'right', headerAlign: 'right' },
      {
        field: 'face_fail_count', headerName: 'FaceID ✗', width: 100, align: 'right', headerAlign: 'right',
        renderCell: (params) =>
          params.value > 0 ? (
            <Typography variant="body2" color="error.main" fontWeight={700}>{params.value}</Typography>
          ) : '—',
      },
      {
        field: 'last_heartbeat_at', headerName: 'Oxirgi signal', width: 130,
        valueGetter: (value) => fromNow(value),
      },
      {
        field: '__actions', headerName: '', width: 130, sortable: false, align: 'right', headerAlign: 'right',
        renderCell: (params) => (
          <Stack direction="row" spacing={0.5}>
            {can('sessions.warn') && (
              <Tooltip title="Ogohlantirish">
                <IconButton size="small" color="warning"
                  onClick={(e) => { e.stopPropagation(); setWarnTarget(params.row) }}>
                  <CampaignIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            {can('sessions.terminate') && (
              <Tooltip title="Chetlashtirish">
                <IconButton size="small" color="error"
                  onClick={(e) => { e.stopPropagation(); setTerminateTarget(params.row) }}>
                  <BlockIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title="Batafsil">
              <IconButton size="small"
                onClick={(e) => { e.stopPropagation(); navigate(`/sessions/${params.row.id}`) }}>
                <OpenIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        ),
      },
    ],
    [can, navigate],
  )

  return (
    <>
      <PageHeader
        title="Jonli kuzatuv"
        subtitle="Faol sessiyalar xavf ballari bo‘yicha tartiblangan"
        actions={
          <Chip
            icon={connected ? <WifiIcon /> : <WifiOffIcon />}
            color={connected ? 'success' : 'default'}
            variant={connected ? 'filled' : 'outlined'}
            label={connected ? 'Real vaqt ulangan' : 'Qayta ulanmoqda…'}
          />
        }
      />

      {!connected && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Real vaqt kanali uzilgan — ro‘yxat har 10 soniyada yangilanmoqda.
        </Alert>
      )}

      {/*
        Filtrlar ataylab shu TARTIBDA: imtihon -> sana -> viloyat -> bino.
        Bu proktorning savol berish tartibi ("qaysi imtihon, qaysi kun,
        qayerda") va har bir keyingi maydon oldingisi bilan toraytiriladi.
      */}
      <Card sx={{ mb: 2.5 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
            <TextField
              select label="Imtihon" value={examFilter}
              onChange={(e) => setExamFilter(e.target.value)}
              sx={{ minWidth: 230, maxWidth: 280 }}
              helperText={
                schedulesData?.results?.length
                  ? 'Shu sanaga jadvalga qo‘yilganlar'
                  : 'Bu sanada jadval yo‘q — barcha faol imtihonlar'
              }
            >
              <MenuItem value="">Barcha imtihonlar</MenuItem>
              {examOptions.map((exam) => (
                <MenuItem key={exam.id} value={exam.id}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ width: '100%' }}>
                    <span>{exam.name}</span>
                    {exam.isOpen && (
                      <Chip size="small" color="success" label="kirish ochiq" sx={{ ml: 'auto' }} />
                    )}
                  </Stack>
                </MenuItem>
              ))}
            </TextField>

            <TextField
              type="date" label="Sana" value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ minWidth: 165, maxWidth: 180 }}
              helperText={dateFilter === today() ? 'Bugun' : 'Arxiv sanasi'}
            />

            <TextField
              select label="Viloyat"
              value={regionFilter}
              onChange={(e) => { setRegionFilter(e.target.value); setZoneFilter('') }}
              disabled={Boolean(lockedRegion)}
              sx={{ minWidth: 200, maxWidth: 240 }}
              helperText={lockedRegion ? 'Hisobingizga biriktirilgan' : ' '}
            >
              <MenuItem value="">Barcha viloyatlar</MenuItem>
              {lockedRegion ? (
                <MenuItem value={lockedRegion}>{user?.region_name}</MenuItem>
              ) : (
                (regionsData?.results || []).map((region) => (
                  <MenuItem key={region.id} value={String(region.id)}>{region.name}</MenuItem>
                ))
              )}
            </TextField>

            <TextField
              select label="Bino" value={zoneFilter}
              onChange={(e) => setZoneFilter(e.target.value)}
              sx={{ minWidth: 220, maxWidth: 280 }}
              helperText={
                regionFilter ? `${zoneOptions.length} ta bino` : 'Barcha viloyatlar bo‘yicha'
              }
            >
              <MenuItem value="">Barcha binolar</MenuItem>
              {zoneOptions.map((zone) => (
                <MenuItem key={zone.id} value={zone.id}>
                  {regionFilter ? zone.name : `${zone.name} — ${zone.region_name}`}
                </MenuItem>
              ))}
            </TextField>

            <Box sx={{ flex: 1 }} />
            <Chip label={`Faol: ${rows.length}`} color="primary" variant="outlined" />
          </Stack>
        </CardContent>
      </Card>

      <Grid container spacing={2.5}>
        <Grid item xs={12} xl={8}>
          <DataTable
            rows={rows}
            columns={columns}
            loading={isLoading}
            onRowClick={(params) => navigate(`/sessions/${params.id}`)}
            height={660}
          />
        </Grid>

        <Grid item xs={12} xl={4}>
          <Card sx={{ height: 660, display: 'flex', flexDirection: 'column' }}>
            <CardHeader
              title={
                <Badge badgeContent={events.length} color="error" max={99}>
                  <Typography variant="h6">Hodisa oqimi</Typography>
                </Badge>
              }
              subheader="Faqat o‘rta va undan yuqori darajali"
              action={
                <Tooltip title="Tozalash">
                  <IconButton onClick={clearEvents}><ClearIcon /></IconButton>
                </Tooltip>
              }
            />
            <Divider />
            <Box sx={{ flex: 1, overflowY: 'auto' }}>
              {events.length === 0 ? (
                <Box sx={{ p: 4, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    Hozircha hodisa yo‘q
                  </Typography>
                </Box>
              ) : (
                <List dense disablePadding>
                  {events.map((event, index) => (
                    <ListItem
                      key={`${event.session_id}-${event.occurred_at}-${index}`}
                      divider
                      secondaryAction={<SeverityChip severity={event.severity} />}
                      sx={{ cursor: 'pointer' }}
                      onClick={() => navigate(`/sessions/${event.session_id}`)}
                    >
                      <ListItemText
                        primary={EVENT_LABEL[event.event_type] || event.event_type}
                        secondary={`Sessiya #${event.session_id} • ${formatTime(event.occurred_at)}`}
                        primaryTypographyProps={{ fontSize: 14, fontWeight: 500 }}
                      />
                    </ListItem>
                  ))}
                </List>
              )}
            </Box>
          </Card>
        </Grid>
      </Grid>

      <ConfirmDialog
        open={Boolean(warnTarget)}
        title="Ogohlantirish yuborish"
        description={`${warnTarget?.candidate_name || ''} ekranida xabar ko‘rsatiladi.`}
        confirmLabel="Yuborish"
        color="warning"
        requireReason
        reasonLabel="Xabar matni"
        loading={warnMutation.isPending}
        onConfirm={(message) => warnMutation.mutate({ id: warnTarget.id, message })}
        onClose={() => setWarnTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(terminateTarget)}
        title="Sessiyani chetlashtirish"
        description={`${terminateTarget?.candidate_name || ''} imtihondan darhol chetlashtiriladi. Bu amalni qaytarib bo‘lmaydi.`}
        confirmLabel="Chetlashtirish"
        color="error"
        requireReason
        loading={terminateMutation.isPending}
        onConfirm={(reason) => terminateMutation.mutate({ id: terminateTarget.id, reason })}
        onClose={() => setTerminateTarget(null)}
      />
    </>
  )
}
