import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Avatar, Box, Button, Card, CardContent, CardHeader, Chip, CircularProgress,
  Divider, Grid, Stack, Tab, Table,
  TableBody, TableCell, TableHead, TableRow, Tabs, Tooltip, Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBackOutlined'
import CampaignIcon from '@mui/icons-material/CampaignOutlined'
import BlockIcon from '@mui/icons-material/BlockOutlined'
import PersonIcon from '@mui/icons-material/PersonOutline'
import ImageIcon from '@mui/icons-material/ImageOutlined'

import PageHeader from '../components/PageHeader'
import ConfirmDialog from '../components/ConfirmDialog'
import { RiskBar, SeverityChip, StatusChip } from '../components/StatusChip'
import { useUi } from '../context/UiContext'
import { useAuth } from '../context/AuthContext'
import { faceLogFile, sessions as sessionsApi } from '../api/endpoints'
import {
  AI_PROFILE_LABEL, computerLabel, EVENT_LABEL, formatDateTime,
  formatDuration, formatTime,
} from '../utils/labels'
import { CATEGORY_META, categoryOf } from '../utils/events'
import ScreenshotGallery from '../components/session/ScreenshotGallery'
import LocalRecordings from '../components/session/LocalRecordings'
import EvidenceCard from '../components/session/EvidenceCard'
import { TablePager } from '../components/data/DataTable'
import { cursorFrom, useCursorPages } from '../hooks/useCursorPages'

/** Bitta kursorli endpoint -> `useCursorPages` sahifasi. */
const cursorPage = (load) => async ({ cursor, pageSize }) => {
  const data = await load({ page_size: pageSize, ...(cursor ? { cursor } : {}) })
  return { results: data?.results || [], nextCursor: cursorFrom(data?.next) }
}

/**
 * Skrinshotlar IKKI manbadan (obyekt storage va fayl tizimi) va har
 * birining o'z kursori bor — sahifa kursori ularning JUFTLIGI. Tugagan
 * manba (`done`) boshqa so'ralmaydi. O'rnatishda odatda bittasi yoqilgan,
 * ya'ni amalda bu oddiy bitta ro'yxat.
 */
const DONE = 'done'
const screenshotPage = (id) => async ({ cursor, pageSize }) => {
  const state = cursor || { object: null, file: null }
  const load = (fn, value) =>
    value === DONE
      ? Promise.resolve({ results: [], next: null })
      : fn(id, { page_size: pageSize, ...(value ? { cursor: value } : {}) })
  const [objectStore, fileStore] = await Promise.all([
    load(sessionsApi.screenshots, state.object),
    load(sessionsApi.storedScreenshots, state.file),
  ])
  const results = [
    ...(objectStore?.results || []).map((shot) => ({ ...shot, source: 'object' })),
    ...(fileStore?.results || []).map((shot) => ({ ...shot, source: 'file' })),
  ].sort((a, b) => String(b.captured_at).localeCompare(String(a.captured_at)))
  const next = {
    object: cursorFrom(objectStore?.next) || DONE,
    file: cursorFrom(fileStore?.next) || DONE,
  }
  return { results, nextCursor: next.object === DONE && next.file === DONE ? null : next }
}

/** Kuzatuv holati — `status` dan ALOHIDA savolga javob beradi. */
const PROCTORING_STATE_COLOR = {
  active: 'success',
  degraded: 'warning',
  failed: 'error',
  stopped: 'default',
}

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

  // Tab'lar — SAHIFALANGAN (standart 50 ta). Ilgari har biri faqat
  // birinchi sahifani so'rardi va qolgani jimgina ko'rinmasdi.
  // Faqat ochiq tab so'raladi (`enabled`): sessiya sahifasi ochilganda
  // beshta ro'yxatni birdaniga tortish keraksiz yuk.
  const events = useCursorPages({
    key: ['session-events', id],
    fetchPage: cursorPage((params) => sessionsApi.events(id, params)),
    enabled: tab === 0,
  })

  const faceLogs = useCursorPages({
    key: ['session-face-logs', id],
    fetchPage: cursorPage((params) => sessionsApi.faceLogs(id, params)),
    enabled: tab === 1,
  })

  // SKRINSHOT IKKI MANBADAN va ikkalasi ham so'raladi: o'rnatishda
  // obyekt storage (`ScreenshotMeta`) yoki fayl tizimi
  // (`ProctoringScreenshot`) yoqilgan bo'ladi va panel qaysi biri
  // ekanini oldindan bilmaydi. Ilgari faqat birinchisi so'ralardi -
  // fayl tizimli o'rnatishda skrinshotlar bazada turgan holda tab
  // doim bo'sh ko'rinardi.
  const screenshots = useCursorPages({
    key: ['session-screenshots', id],
    fetchPage: screenshotPage(id),
    enabled: tab === 2,
  })

  // Dalil ro'yxati — FAYLLARSIZ. Baytlar har bir karta o'z blob'ini
  // so'raganda keladi (`EvidenceCard`), aks holda 20 ta klipli
  // sahifa o'nlab megabaytni bir vaqtda tortib olardi.
  const evidence = useCursorPages({
    key: ['session-evidence', id],
    fetchPage: cursorPage((params) => sessionsApi.evidence(id, params)),
    enabled: tab === 3,
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
  // `meta` — sessiyaga MUZLATILGAN ma'lumot: platformaning javobi va
  // uchta tarmoq manzili (`session.py:_create_session`).
  const platform = session.meta?.platform || {}
  const network = session.meta?.network || {}
  const identity = session.identity || {}
  const identityUnverified = session.meta?.face_identity_verified === false

  return (
    <>
      <PageHeader
        title={candidate.full_name || 'Sessiya'}
        subtitle={`${session.exam_name} • ${session.zone_name || '—'} • ${computerLabel(session.computer_number, session.computer_code) || '—'} • ${session.attempt_no}-urinish`}
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
                  <Typography variant="subtitle1" fontWeight={600}>
                    {candidate.full_name || '—'}
                  </Typography>
                  {/*
                    JSHSHIR TO'LIQ va NUSXA OLSA BO'LADIGAN shaklda:
                    proktor uni platformaga yoki hujjatga solishtiradi,
                    niqoblangan raqamdan esa buni qilib bo'lmasdi.
                  */}
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ fontFamily: 'ui-monospace, monospace', userSelect: 'all' }}
                  >
                    {candidate.pinfl || candidate.masked_pinfl || '—'}
                  </Typography>
                </Box>
              </Stack>
              <InfoRow label="Holat" value={<StatusChip status={session.status} label={session.status_display} />} />
              <InfoRow label="Xavf ballari" value={<RiskBar value={session.risk_score} width={120} />} />
              <InfoRow
                label="Shaxs tasdig‘i"
                value={
                  <Chip
                    size="small"
                    color={session.identity_verified ? 'success' : 'default'}
                    variant={session.identity_verified ? 'filled' : 'outlined'}
                    label={session.identity_verified ? 'Tasdiqlangan' : 'Tasdiqlanmagan'}
                  />
                }
              />
              {identity.confirmed_by_name && (
                <InfoRow label="Tasdiqladi" value={identity.confirmed_by_name} />
              )}
              {identity.confirmed_at && (
                <InfoRow label="Tasdiqlangan vaqt" value={formatDateTime(identity.confirmed_at)} />
              )}
              <Divider sx={{ my: 1 }} />
              <InfoRow label="Platforma ID" value={session.external_candidate_id || '—'} />
              <InfoRow label="Abituriyent ID" value={platform.abitur_id || '—'} />
              {platform.message && <InfoRow label="Platforma javobi" value={platform.message} />}
              <InfoRow
                label="Testga ajratilgan vaqt"
                value={platform.duration_minutes ? formatMinutes(platform.duration_minutes) : '—'}
              />
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8}>
          <Card sx={{ height: '100%' }}>
            <CardHeader
              title="Sessiya ma’lumotlari"
              titleTypographyProps={{ variant: 'h6' }}
              subheader={`№ ${session.public_id} · ${session.attempt_no}-urinish`}
            />
            <CardContent>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <Typography variant="overline" color="text.secondary">Vaqt</Typography>
                  <InfoRow label="Imtihon sanasi" value={session.exam_date || '—'} />
                  <InfoRow label="Boshlangan" value={formatDateTime(session.started_at)} />
                  <InfoRow label="Tugagan" value={formatDateTime(session.finished_at)} />
                  <InfoRow label="Davomiyligi" value={formatDuration(session.duration_seconds)} />
                  <InfoRow label="Oxirgi signal" value={formatDateTime(session.last_heartbeat_at)} />

                  <Typography variant="overline" color="text.secondary">Joylashuv</Typography>
                  <InfoRow label="Imtihon" value={session.exam_name || '—'} />
                  <InfoRow label="Viloyat" value={session.region_name || '—'} />
                  <InfoRow label="Bino" value={session.zone_name || '—'} />
                  <InfoRow
                    label="Kompyuter"
                    value={computerLabel(session.computer_number, session.computer_code) || '—'}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <Typography variant="overline" color="text.secondary">Tarmoq va qurilma</Typography>
                  {/*
                    UCHTA MANZIL UCHTA SAVOLGA javob beradi va ular
                    ataylab alohida ko'rsatiladi: LAN — qaysi mashina,
                    manba — serverga qaysi manzildan kelgan (NAT ortida
                    butun bino uchun bitta), tashqi — bino qaysi IP
                    bilan internetga chiqadi.
                  */}
                  <InfoRow label="IP manzil (mashina)" value={session.ip_address || '—'} />
                  <InfoRow label="So‘rov manbai" value={network.source_ip || '—'} />
                  <InfoRow label="Tashqi IP" value={network.public_ip || '—'} />
                  <InfoRow label="Machine UUID" value={session.machine_uuid || '—'} />
                  <InfoRow label="MAC" value={session.mac_address || '—'} />
                  <InfoRow
                    label="Apparat profili"
                    value={AI_PROFILE_LABEL[session.ai_profile] || session.ai_profile || '—'}
                  />

                  <Typography variant="overline" color="text.secondary">Kuzatuv</Typography>
                  <InfoRow
                    label="AI kuzatuv"
                    value={
                      <Chip
                        size="small"
                        color={PROCTORING_STATE_COLOR[session.proctoring_state] || 'default'}
                        variant={session.proctoring_state === 'active' ? 'filled' : 'outlined'}
                        label={session.proctoring_state_display || session.proctoring_state || '—'}
                      />
                    }
                  />
                  <InfoRow label="Kamera tekshiruvi" value={cameraCheckLabel(session.camera_check)} />
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

              {session.termination_reason && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  Chetlashtirildi{session.terminated_by_name ? ` (${session.terminated_by_name})` : ''}:{' '}
                  {session.termination_reason}
                </Alert>
              )}
            </CardContent>
          </Card>
        </Grid>

      </Grid>

      <RiskBreakdownCard breakdown={session.risk_breakdown} score={session.risk_score} />

      <Card>
        <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ px: { xs: 0, sm: 2 }, borderBottom: 1, borderColor: 'divider' }}>
          <Tab label="Hodisalar" />
          <Tab label="Yuz tekshiruvlari" />
          <Tab label="Skrinshotlar" />
          <Tab label="Dalillar" />
          <Tab label="Mashinadagi yozuvlar" />
        </Tabs>

        {/* Telefonda jadvallar SIQILMAYDI, suriladi (`minWidth`): siqilganda
            "Kadrda ikkinchi odam" uch qatorga bo'linib, har qator ~70 px
            bo'lardi va 100 ta hodisa ekranni o'n marta to'ldirardi. */}
        {tab === 0 && (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 640 }}>
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
                <EmptyRow items={events.rows} loading={events.isLoading} colSpan={5} text="Hodisa qayd etilmagan" />
                {events.rows.map((event, index) => (
                  <TableRow key={event.id} hover>
                    <RowNumber index={events.offset + index} id={event.id} />
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatTime(event.occurred_at)}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{EVENT_LABEL[event.type] || event.type_display}</TableCell>
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
            <TabPager list={events} />
          </Box>
        )}

        {tab === 1 && (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 760 }}>
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
                  <TableCell>Kadr</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <EmptyRow items={faceLogs.rows} loading={faceLogs.isLoading} colSpan={9} text="Yuz tekshiruvi yo‘q" />
                {faceLogs.rows.map((log, index) => (
                  <TableRow key={log.id} hover>
                    <RowNumber index={faceLogs.offset + index} id={log.id} />
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
                    <TableCell>
                      <FaceImageCell
                        id={log.id}
                        hasImage={Boolean(log.image_url)}
                        hasReference={Boolean(log.reference_image_url)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <TabPager list={faceLogs} />
          </Box>
        )}

        {tab === 2 && (
          <CardContent>
            {screenshots.isLoading ? (
              <TabLoading />
            ) : screenshots.rows.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                Skrinshot yo‘q. Imtihon sahifasi ochilmagan bo‘lishi yoki skrinshot
                olish sozlamada o‘chirilgan bo‘lishi mumkin.
              </Typography>
            ) : (
              <ScreenshotGallery shots={screenshots.rows} />
            )}
          </CardContent>
        )}
        {tab === 2 && <TabPager list={screenshots} />}

        {tab === 3 && (
          <CardContent>
            {evidence.isLoading ? (
              <TabLoading />
            ) : evidence.rows.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                Dalil yo‘q. Dalil faqat AI kuzatuv tasdiqlagan hodisadan
                tug‘iladi: kuzatuv siyosatida AI kuzatuv va «Dalil to‘plash»
                yoqilganini, hodisa jiddiyligi chegaradan past emasligini
                tekshiring.
              </Typography>
            ) : (
              <Grid container spacing={2}>
                {evidence.rows.map((item) => (
                  <Grid item xs={12} sm={6} md={4} key={item.id}>
                    <EvidenceCard item={item} />
                  </Grid>
                ))}
              </Grid>
            )}
          </CardContent>
        )}
        {tab === 3 && <TabPager list={evidence} />}

        {tab === 4 && (
          <CardContent>
            <LocalRecordings session={session} />
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
        description="Talabgor imtihondan darhol chetlashtiriladi va kirish tokeni bekor qilinadi. Kompyuter broni ham bo‘shatiladi — joy keyingi talabgorga beriladi."
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

/**
 * Xavf ballining TARKIBI — apellyatsiya hujjati.
 *
 * Yagona "72" raqami proktorga hech narsa aytmaydi va uni tekshirib
 * ham bo'lmaydi. "72 ball, shundan 40 tasi telefon, 20 tasi ikkinchi
 * odam" esa tekshirib bo'ladigan da'vo — aynan shu farq
 * chetlashtirish qarorini asoslaydi.
 *
 * TARKIB PASAYMAYDI, ball esa pasayadi: birinchisi "nima bo'lgan"
 * degan savolga javob beradi, ikkinchisi "hozir qanchalik xavfli"
 * degan savolga. Shuning uchun yig'indi joriy balldan KATTA
 * bo'lishi normal va buni izohda ochiq aytish kerak — aks holda u
 * xatoday ko'rinardi.
 */
function RiskBreakdownCard({ breakdown, score }) {
  const entries = Object.entries(breakdown || {})
    .filter(([, points]) => Number(points) > 0)
    .sort((a, b) => b[1] - a[1])

  if (!entries.length) return null

  const total = entries.reduce((sum, [, points]) => sum + Number(points), 0)

  return (
    <Card sx={{ mb: 2.5 }}>
      <CardHeader
        title="Xavf balli tarkibi"
        titleTypographyProps={{ variant: 'h6' }}
        subheader={
          total > score
            ? `Jami ${total} ball to‘plangan, joriy ball ${score} — farq vaqt o‘tishi bilan pasayish hisobiga`
            : `Jami ${total} ball`
        }
      />
      <CardContent sx={{ pt: 0 }}>
        <Stack spacing={1}>
          {entries.map(([type, points]) => {
            const meta = CATEGORY_META[categoryOf(type)]
            return (
              <Stack key={type} direction="row" spacing={1.5} alignItems="center">
                <Chip size="small" variant="outlined" color={meta.color} label={meta.label} />
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {EVENT_LABEL[type] || type}
                </Typography>
                {/* Ulush chizig'i: raqamlar ro'yxatida eng og'ir sabab
                    ko'zga tashlanmasdi. */}
                <Box
                  sx={{
                    width: 160, height: 6, borderRadius: 3,
                    bgcolor: 'action.hover', overflow: 'hidden',
                  }}
                >
                  <Box
                    sx={{
                      width: `${Math.round((points / total) * 100)}%`,
                      height: '100%',
                      bgcolor: `${meta.color === 'default' ? 'grey' : meta.color}.main`,
                    }}
                  />
                </Box>
                <Typography variant="body2" fontWeight={700} sx={{ minWidth: 40, textAlign: 'right' }}>
                  +{points}
                </Typography>
              </Stack>
            )
          })}
        </Stack>
      </CardContent>
    </Card>
  )
}

/**
 * Yuz tekshiruvining JONLI KADRI.
 *
 * TALAB BO'YICHA yuklanadi. Sabab audit'da: faylni ochish serverda
 * `evidence_view` yozuvini qoldiradi (bu talabgorning yuzi, ya'ni
 * shaxsiy ma'lumot). Jadval ochilishi bilan 100 ta rasmni yuklash
 * jurnalni "kim nimani ko'rdi" degan savolga javob berolmaydigan
 * holga keltirardi.
 *
 * Blob komponent yopilganda DARHOL bo'shatiladi — `URL.createObjectURL`
 * ni brauzer o'zi tozalamaydi.
 */
function FaceImageCell({ id, hasImage, hasReference }) {
  const [live, setLive] = useState('')
  const [reference, setReference] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => () => {
    if (live) URL.revokeObjectURL(live)
  }, [live])
  useEffect(() => () => {
    if (reference) URL.revokeObjectURL(reference)
  }, [reference])

  if (!hasImage && !hasReference) {
    return (
      <Typography variant="caption" color="text.disabled">
        —
      </Typography>
    )
  }

  if (live || reference) {
    return (
      // IKKI RASM YONMA-YON. Aynan shu juftlik ballni TUSHUNTIRADI:
      // "47 ball" degan yozuv o'zicha na tasdiq, na rad — qaror
      // hujjatdagi va kameradagi odamni solishtirgandan keyin
      // qabul qilinadi.
      <Stack direction="row" spacing={1}>
        {reference && (
          <Box>
            <Typography variant="caption" color="text.secondary">Hujjat</Typography>
            <Box
              component="img"
              src={reference}
              alt="Hujjat rasmi"
              sx={{ width: 84, borderRadius: 1, display: 'block' }}
            />
          </Box>
        )}
        {live && (
          <Box>
            <Typography variant="caption" color="text.secondary">Kamera</Typography>
            <Box
              component="img"
              src={live}
              alt="Jonli kadr"
              sx={{ width: 84, borderRadius: 1, display: 'block' }}
            />
          </Box>
        )}
      </Stack>
    )
  }

  const load = () => {
    setLoading(true)
    setError('')
    // Ikkala rasm BIRGA so'raladi: operator ularni faqat birga
    // ishlatadi, alohida tugma esa ikki marta bosishga majbur
    // qilardi. Bittasi bo'lmasa (test davomidagi tekshiruv)
    // ikkinchisi baribir ko'rsatiladi.
    Promise.allSettled([
      hasReference ? faceLogFile.objectUrl(id, 'reference') : Promise.reject(),
      hasImage ? faceLogFile.objectUrl(id) : Promise.reject(),
    ])
      .then(([ref, shot]) => {
        if (ref.status === 'fulfilled') setReference(ref.value)
        if (shot.status === 'fulfilled') setLive(shot.value)
        if (ref.status !== 'fulfilled' && shot.status !== 'fulfilled') setError('Ochilmadi')
      })
      .finally(() => setLoading(false))
  }

  return (
    <Button size="small" onClick={load} disabled={loading} startIcon={<ImageIcon />}>
      {loading ? '...' : error || 'Ko‘rish'}
    </Button>
  )
}

/**
 * Daqiqani odam o'qiydigan shaklga keltiradi ("180" -> "3 soat").
 *
 * Client tomonda ham xuddi shu qoida bor (`Candidate.duration_label`)
 * va ular MOS bo'lishi kerak: bir xil qiymatni panelda "180 daqiqa",
 * talabgor ekranida "3 soat" deb ko'rsatish bir xil ma'lumotni ikki
 * xil qilib ko'rsatardi.
 */
function formatMinutes(minutes) {
  const total = Number(minutes) || 0
  if (total <= 0) return '—'
  const hours = Math.floor(total / 60)
  const rest = total % 60
  if (hours && rest) return `${hours} soat ${rest} daqiqa`
  if (hours) return `${hours} soat`
  return `${rest} daqiqa`
}

/**
 * Kamera tekshiruvining qisqa xulosasi.
 *
 * To'liq natija (14 ta tekshiruv) sessiyaga MUZLATILGAN, lekin
 * kartochkada faqat yakuniy holat kerak: tafsilot bu ekranda
 * o'qilmaydi, u nosozlikni tekshirishda kerak bo'ladi.
 */
function cameraCheckLabel(check) {
  if (!check || !Object.keys(check).length) return 'O‘tkazilmagan'
  const map = { ready: 'O‘tdi', warning: 'Ogohlantirish bilan', failed: 'O‘tmadi' }
  return map[check.status] || check.status || '—'
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

function EmptyRow({ items, loading, colSpan, text }) {
  if (items && items.length > 0) return null
  return (
    <TableRow>
      <TableCell colSpan={colSpan} align="center" sx={{ py: 5 }}>
        {/* Yuklanayotganda "Hodisa qayd etilmagan" deyish yolg'on bo'lardi. */}
        {loading ? <CircularProgress size={22} /> : (
          <Typography variant="body2" color="text.secondary">{text}</Typography>
        )}
      </TableCell>
    </TableRow>
  )
}

/**
 * Tab futeri — `DataTable` dagi AYNAN o'sha futer (kursor rejimi):
 * «Sahifada» (25/50/100) va oldinga/orqaga. Bo'sh birinchi sahifada
 * chizilmaydi — boshqaradigan narsa yo'q.
 */
function TabPager({ list }) {
  if (!list.rows.length && list.pageIndex === 0) return null
  return (
    <TablePager
      cursorNav={list.cursorNav}
      rowsOnPage={list.rows.length}
      fetching={list.isFetching}
    />
  )
}

function TabLoading() {
  return (
    <Box sx={{ display: 'grid', placeItems: 'center', py: 6 }}>
      <CircularProgress size={26} />
    </Box>
  )
}
