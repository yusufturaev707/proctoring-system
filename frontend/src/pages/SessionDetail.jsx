import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Avatar, Box, Button, Card, CardContent, CardHeader, Chip, CircularProgress,
  Divider, Grid, ImageList, ImageListItem, ImageListItemBar, Stack, Tab, Table,
  TableBody, TableCell, TableHead, TableRow, Tabs, Tooltip, Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBackOutlined'
import CampaignIcon from '@mui/icons-material/CampaignOutlined'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import PersonIcon from '@mui/icons-material/PersonOutline'

import PageHeader from '../components/PageHeader'
import ConfirmDialog from '../components/ConfirmDialog'
import { RiskBar, SeverityChip, StatusChip } from '../components/StatusChip'
import { useUi } from '../context/UiContext'
import { useAuth } from '../context/AuthContext'
import { sessions as sessionsApi } from '../api/endpoints'
import {
  EVENT_LABEL, formatBytes, formatDateTime, formatDuration, formatTime,
} from '../utils/labels'

export default function SessionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { can } = useAuth()

  const [tab, setTab] = useState(0)
  const [warnOpen, setWarnOpen] = useState(false)
  const [terminateOpen, setTerminateOpen] = useState(false)

  const { data: session, isLoading } = useQuery({
    queryKey: ['session', id],
    queryFn: () => sessionsApi.detail(id),
    // Faol sessiyani 10 soniyada yangilaymiz, yakunlanganini — umuman emas.
    refetchInterval: (query) =>
      ['in_progress', 'ready', 'face_check'].includes(query.state.data?.status) ? 10000 : false,
  })

  const { data: events } = useQuery({
    queryKey: ['session-events', id],
    queryFn: () => sessionsApi.events(id, { page_size: 100 }),
    enabled: tab === 0,
  })

  const { data: faceLogs } = useQuery({
    queryKey: ['session-face-logs', id],
    queryFn: () => sessionsApi.faceLogs(id, { page_size: 100 }),
    enabled: tab === 1,
  })

  const { data: screenshots } = useQuery({
    queryKey: ['session-screenshots', id],
    queryFn: () => sessionsApi.screenshots(id, { page_size: 60 }),
    enabled: tab === 2,
  })

  const warnMutation = useMutation({
    mutationFn: (message) => sessionsApi.warn(id, { message, severity: 2 }),
    onSuccess: () => { notify('Ogohlantirish yuborildi'); setWarnOpen(false) },
    onError: notifyError,
  })

  const terminateMutation = useMutation({
    mutationFn: (reason) => sessionsApi.terminate(id, { reason }),
    onSuccess: () => {
      notify('Sessiya chetlashtirildi')
      setTerminateOpen(false)
      queryClient.invalidateQueries({ queryKey: ['session', id] })
    },
    onError: notifyError,
  })

  if (isLoading) {
    return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  }
  if (!session) return <Alert severity="error">Sessiya topilmadi</Alert>

  const isActive = !['finished', 'terminated', 'expired'].includes(session.status)
  const candidate = session.candidate_detail || {}
  const identityUnverified = session.meta?.face_identity_verified === false

  return (
    <>
      <PageHeader
        title={candidate.full_name || 'Sessiya'}
        subtitle={`${session.exam_name} • ${session.zone_name || '—'} • ${session.computer_code || '—'} • ${session.attempt_no}-urinish`}
        actions={
          <>
            <Button startIcon={<ArrowBackIcon />} onClick={() => navigate(-1)} color="inherit">
              Orqaga
            </Button>
            {isActive && can('sessions.warn') && (
              <Button startIcon={<CampaignIcon />} color="warning" variant="outlined" onClick={() => setWarnOpen(true)}>
                Ogohlantirish
              </Button>
            )}
            {isActive && can('sessions.terminate') && (
              <Button startIcon={<BlockIcon />} color="error" variant="contained" onClick={() => setTerminateOpen(true)}>
                Chetlashtirish
              </Button>
            )}
          </>
        }
      />

      {identityUnverified && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Bu sessiyada <strong>shaxs tasdiqlanmagan</strong>: tashqi platformada etalon
          rasm topilmagani uchun FaceID faqat etalon olish rejimida ishlagan.
        </Alert>
      )}
      {session.status === 'terminated' && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Chetlashtirilgan — {session.termination_reason || 'sabab ko‘rsatilmagan'}
          {session.terminated_by_name && ` (${session.terminated_by_name})`}
        </Alert>
      )}

      <Grid container spacing={2.5} sx={{ mb: 2.5 }}>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardHeader title="Talabgor" titleTypographyProps={{ variant: 'h6' }} />
            <CardContent>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                <Avatar src={candidate.photo_url || undefined} sx={{ width: 64, height: 64 }}>
                  <PersonIcon />
                </Avatar>
                <Box>
                  <Typography variant="subtitle1" fontWeight={600}>{candidate.full_name}</Typography>
                  <Typography variant="body2" color="text.secondary">{candidate.masked_pinfl}</Typography>
                </Box>
              </Stack>
              <InfoRow label="Holat" value={<StatusChip status={session.status} label={session.status_display} />} />
              <InfoRow label="Xavf ballari" value={<RiskBar value={session.risk_score} width={120} />} />
              <InfoRow label="IP manzil" value={session.ip_address || '—'} />
              <InfoRow label="MAC" value={session.mac_address || '—'} />
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8}>
          <Card sx={{ height: '100%' }}>
            <CardHeader title="Sessiya ma’lumotlari" titleTypographyProps={{ variant: 'h6' }} />
            <CardContent>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <InfoRow label="Boshlangan" value={formatDateTime(session.started_at)} />
                  <InfoRow label="Tugagan" value={formatDateTime(session.finished_at)} />
                  <InfoRow label="Davomiyligi" value={formatDuration(session.duration_seconds)} />
                  <InfoRow label="Oxirgi signal" value={formatDateTime(session.last_heartbeat_at)} />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <InfoRow label="Hodisalar" value={session.event_count} />
                  <InfoRow label="Skrinshotlar" value={session.screenshot_count} />
                  <InfoRow label="FaceID tekshiruvi" value={session.face_check_count} />
                  <InfoRow
                    label="FaceID xatolari"
                    value={
                      session.face_fail_count > 0 ? (
                        <Chip size="small" color="error" label={session.face_fail_count} />
                      ) : '0'
                    }
                  />
                </Grid>
              </Grid>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card>
        <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Tab label="Hodisalar" />
          <Tab label="Yuz tekshiruvlari" />
          <Tab label="Skrinshotlar" />
        </Tabs>

        {tab === 0 && (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell align="right" width={52}>№</TableCell>
                  <TableCell>Vaqt</TableCell>
                  <TableCell>Hodisa</TableCell>
                  <TableCell>Daraja</TableCell>
                  <TableCell>Tafsilot</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <EmptyRow items={events?.results} colSpan={5} text="Hodisa qayd etilmagan" />
                {(events?.results || []).map((event, index) => (
                  <TableRow key={event.id} hover>
                    <RowNumber index={index} id={event.id} />
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatTime(event.occurred_at)}</TableCell>
                    <TableCell>{EVENT_LABEL[event.type] || event.type_display}</TableCell>
                    <TableCell><SeverityChip severity={event.severity} label={event.severity_display} /></TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                        {Object.keys(event.payload || {}).length
                          ? JSON.stringify(event.payload)
                          : '—'}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}

        {tab === 1 && (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell align="right" width={52}>№</TableCell>
                  <TableCell>Vaqt</TableCell>
                  <TableCell>Bosqich</TableCell>
                  <TableCell>Manba</TableCell>
                  <TableCell align="right">Ball</TableCell>
                  <TableCell align="right">Chegara</TableCell>
                  <TableCell align="center">Yuzlar</TableCell>
                  <TableCell>Natija</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <EmptyRow items={faceLogs?.results} colSpan={8} text="Yuz tekshiruvi yo‘q" />
                {(faceLogs?.results || []).map((log, index) => (
                  <TableRow key={log.id} hover>
                    <RowNumber index={index} id={log.id} />
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatTime(log.occurred_at)}</TableCell>
                    <TableCell>{log.stage_display}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        variant="outlined"
                        color={log.source === 'server' ? 'success' : 'default'}
                        label={log.source === 'server' ? 'Server' : 'Client'}
                      />
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>{log.score}</TableCell>
                    <TableCell align="right">{log.threshold}</TableCell>
                    <TableCell align="center">{log.faces_detected}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={log.passed ? 'success' : 'error'}
                        label={log.passed ? 'O‘tdi' : 'O‘tmadi'}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}

        {tab === 2 && (
          <CardContent>
            {(screenshots?.results || []).length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                Skrinshot yo‘q. Object storage yoqilganligini tekshiring (S3_ENABLED).
              </Typography>
            ) : (
              <ImageList cols={4} gap={12} sx={{ m: 0 }}>
                {screenshots.results.map((shot) => (
                  <ImageListItem key={shot.id} sx={{ borderRadius: 2, overflow: 'hidden' }}>
                    <img src={shot.url} alt={shot.kind} loading="lazy" style={{ borderRadius: 8 }} />
                    <ImageListItemBar
                      title={formatTime(shot.captured_at)}
                      subtitle={`${shot.width}×${shot.height} • ${formatBytes(shot.size_bytes)}`}
                    />
                  </ImageListItem>
                ))}
              </ImageList>
            )}
          </CardContent>
        )}
      </Card>

      <ConfirmDialog
        open={warnOpen}
        title="Ogohlantirish yuborish"
        description="Xabar talabgor ekranida darhol ko‘rsatiladi."
        confirmLabel="Yuborish"
        color="warning"
        requireReason
        reasonLabel="Xabar matni"
        loading={warnMutation.isPending}
        onConfirm={(message) => warnMutation.mutate(message)}
        onClose={() => setWarnOpen(false)}
      />

      <ConfirmDialog
        open={terminateOpen}
        title="Sessiyani chetlashtirish"
        description="Talabgor imtihondan darhol chetlashtiriladi va kirish tokeni bekor qilinadi."
        confirmLabel="Chetlashtirish"
        color="error"
        requireReason
        loading={terminateMutation.isPending}
        onConfirm={(reason) => terminateMutation.mutate(reason)}
        onClose={() => setTerminateOpen(false)}
      />
    </>
  )
}

function InfoRow({ label, value }) {
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Box sx={{ textAlign: 'right' }}>
        {typeof value === 'string' || typeof value === 'number' ? (
          <Typography variant="body2" fontWeight={600}>{value}</Typography>
        ) : value}
      </Box>
    </Stack>
  )
}

/**
 * Tartib raqami katakchasi.
 *
 * Raqam ro'yxatdagi o'rinni, tooltip esa yozuvning haqiqiy ID'sini
 * beradi — jadval katakchalari bilan bir xil mantiq (`DataTable`).
 */
function RowNumber({ index, id }) {
  return (
    <TableCell align="right">
      <Tooltip title={`ID: ${id}`} placement="right">
        <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
          {index + 1}
        </Typography>
      </Tooltip>
    </TableCell>
  )
}

function EmptyRow({ items, colSpan, text }) {
  if (items && items.length > 0) return null
  return (
    <TableRow>
      <TableCell colSpan={colSpan} align="center" sx={{ py: 5 }}>
        <Typography variant="body2" color="text.secondary">{text}</Typography>
      </TableCell>
    </TableRow>
  )
}
