import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Card, CardContent, CardHeader, Chip, CircularProgress,
  Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, FormControlLabel, Grid, MenuItem, Slider, Stack, Switch, Tab, Tabs,
  TextField, Tooltip, Typography,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/SaveOutlined'
import AddIcon from '@mui/icons-material/AddOutlined'
import StarIcon from '@mui/icons-material/StarOutlined'
import DeleteIcon from '@mui/icons-material/DeleteOutlineOutlined'
import FaceIcon from '@mui/icons-material/FaceRetouchingNaturalOutlined'
import CameraIcon from '@mui/icons-material/PhotoCameraOutlined'
import ShieldIcon from '@mui/icons-material/PolicyOutlined'
import RouterIcon from '@mui/icons-material/RouterOutlined'

import PageHeader from '../components/PageHeader'
import ConfirmDialog from '../components/ConfirmDialog'
import { exams as examsApi, settings as settingsApi } from '../api/endpoints'
import { useUi } from '../context/UiContext'
import { useAuth } from '../context/AuthContext'

/** Serverga yuborilmaydigan read-only maydonlar. */
const READ_ONLY = [
  'id', 'created_at', 'updated_at', 'detect_classes_detail',
  'rdp_objects_detail', 'hotkeys_detail', 'detect_model_name',
]

const stripReadOnly = (obj) =>
  Object.fromEntries(Object.entries(obj).filter(([key]) => !READ_ONLY.includes(key)))

/**
 * Client xulq-atvori sozlamalari.
 *
 * Bu yerdagi har bir qiymat 10 000 ta clientga tarqaladi, shuning uchun
 * yuklamaga ta'sir qiladigan maydonlarda (interval, sifat) buni aniq
 * ko'rsatib turamiz — admin bexosdan serverni yiqitmasin.
 */
export default function Settings() {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const { can } = useAuth()
  const canManage = can('controls.manage')

  const [tab, setTab] = useState(0)
  const [form, setForm] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [copyName, setCopyName] = useState(null)   // null = dialog yopiq
  const [confirm, setConfirm] = useState(null)     // {kind, ...}

  // Barcha profillar. Ro'yxat to'liq obyektlarni qaytaradi, shuning uchun
  // tanlaganda qo'shimcha detail so'rovi kerak emas.
  const { data: listData, isLoading } = useQuery({
    queryKey: ['settings-list'],
    queryFn: () => settingsApi.list({ page_size: 100 }),
  })
  const profiles = listData?.results ?? []

  // Qaysi imtihonlar shu profildan foydalanadi — o'chirishdan oldin bilish shart.
  const { data: examData } = useQuery({
    queryKey: ['exams-for-settings'],
    queryFn: () => examsApi.list({ page_size: 200 }),
  })
  const examsBySetting = (examData?.results ?? []).reduce((acc, exam) => {
    if (exam.setting) acc[exam.setting] = (acc[exam.setting] || 0) + 1
    return acc
  }, {})

  // Boshlang'ich tanlov — global standart.
  useEffect(() => {
    if (!profiles.length) return
    const stillExists = profiles.some((item) => item.id === selectedId)
    if (!stillExists) {
      const fallback = profiles.find((item) => item.is_active) || profiles[0]
      setSelectedId(fallback.id)
      setForm(fallback)
    }
  }, [profiles, selectedId])

  const selectProfile = (id) => {
    const next = profiles.find((item) => item.id === id)
    if (next) {
      setSelectedId(id)
      setForm(next)
    }
  }

  const refresh = (message) => {
    notify(message)
    queryClient.invalidateQueries({ queryKey: ['settings-list'] })
    // ExamsPage'dagi `useSettingOptions` keshi — kaliti `['settings', 'options', …]`.
    queryClient.invalidateQueries({ queryKey: ['settings'] })
  }

  const saveMutation = useMutation({
    mutationFn: (payload) => settingsApi.update({ id: payload.id, ...stripReadOnly(payload) }),
    onSuccess: () => refresh('Profil saqlandi — clientlar keyingi handshake’da oladi'),
    onError: notifyError,
  })

  const createMutation = useMutation({
    mutationFn: (name) =>
      settingsApi.create({ ...stripReadOnly(form), name, is_active: false }),
    onSuccess: (created) => {
      setCopyName(null)
      setSelectedId(created.id)
      setForm(created)
      refresh(`«${created.name}» yaratildi — endi uni imtihonga biriktirishingiz mumkin`)
    },
    onError: notifyError,
  })

  const activateMutation = useMutation({
    mutationFn: (id) => settingsApi.activate(id),
    onSuccess: () => {
      setConfirm(null)
      refresh('Global standart o‘zgartirildi')
    },
    onError: notifyError,
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => settingsApi.remove(id),
    onSuccess: () => {
      setConfirm(null)
      setSelectedId(null)
      refresh('Profil o‘chirildi')
    },
    onError: notifyError,
  })

  if (isLoading) {
    return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  }
  if (!form) {
    return (
      <Alert severity="warning">
        Birorta ham profil topilmadi. Uni Django admin panelida yoki
        <code> python manage.py seed_base_data </code> orqali yarating.
      </Alert>
    )
  }

  const usedByExams = examsBySetting[form.id] || 0

  const set = (name) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((prev) => ({ ...prev, [name]: value }))
  }
  const setNumber = (name) => (event) =>
    setForm((prev) => ({ ...prev, [name]: Number(event.target.value) }))
  const setSlider = (name) => (_, value) => setForm((prev) => ({ ...prev, [name]: value }))

  // 10 000 talaba uchun taxminiy yuklama — admin qarorining narxini ko'rsatadi.
  const estimatedRps = form.screenshot_interval ? Math.round(10000 / form.screenshot_interval) : 0
  const estimatedMbps = Math.round((estimatedRps * form.screenshot_quality * 1.8) / 1000)

  return (
    <>
      <PageHeader
        title="Proktorlik profillari"
        subtitle="Har bir imtihon o‘z profiliga ega bo‘lishi mumkin"
        actions={
          canManage && (
            <Button
              variant="contained"
              startIcon={<SaveIcon />}
              onClick={() => saveMutation.mutate(form)}
              disabled={saveMutation.isPending}
            >
              Saqlash
            </Button>
          )
        }
      />

      {!canManage && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Sizda faqat ko‘rish huquqi bor.
        </Alert>
      )}

      {/* --- Profil tanlash paneli --- */}
      <Card sx={{ mb: 2.5 }}>
        <CardContent sx={{ py: 2 }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
            <TextField
              select
              label="Profil"
              value={selectedId ?? ''}
              onChange={(event) => selectProfile(Number(event.target.value))}
              sx={{ minWidth: 280 }}
              size="small"
            >
              {profiles.map((item) => (
                <MenuItem key={item.id} value={item.id}>
                  {item.name}
                  {item.is_active && ' — global standart'}
                </MenuItem>
              ))}
            </TextField>

            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              {form.is_active ? (
                <Chip size="small" color="primary" icon={<StarIcon />} label="Global standart" />
              ) : (
                <Chip size="small" variant="outlined" label="Imtihonga biriktiriladi" />
              )}
              <Chip
                size="small"
                variant="outlined"
                label={usedByExams ? `${usedByExams} ta imtihon` : 'Imtihonga biriktirilmagan'}
                color={usedByExams ? 'default' : 'warning'}
              />
            </Stack>

            <Box sx={{ flex: 1 }} />

            {canManage && (
              <Stack direction="row" spacing={1}>
                <Button
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={() => setCopyName(`${form.name} — nusxa`)}
                >
                  Nusxadan yaratish
                </Button>
                <Tooltip title={form.is_active ? 'Bu allaqachon global standart' : ''}>
                  <span>
                    <Button
                      size="small"
                      startIcon={<StarIcon />}
                      disabled={form.is_active}
                      onClick={() => setConfirm({ kind: 'activate' })}
                    >
                      Standart qilish
                    </Button>
                  </span>
                </Tooltip>
                <Tooltip
                  title={
                    form.is_active
                      ? 'Global standartni o‘chirib bo‘lmaydi'
                      : usedByExams
                        ? `${usedByExams} ta imtihon shu profildan foydalanadi`
                        : ''
                  }
                >
                  <span>
                    <Button
                      size="small"
                      color="error"
                      startIcon={<DeleteIcon />}
                      disabled={form.is_active || profiles.length < 2}
                      onClick={() => setConfirm({ kind: 'delete' })}
                    >
                      O‘chirish
                    </Button>
                  </span>
                </Tooltip>
              </Stack>
            )}
          </Stack>

          {canManage && (
            <TextField
              label="Profil nomi"
              value={form.name ?? ''}
              onChange={set('name')}
              size="small"
              sx={{ mt: 2, minWidth: 320 }}
              error={!form.name?.trim()}
              helperText={!form.name?.trim() ? 'Nom bo‘sh bo‘lmasligi kerak' : ' '}
            />
          )}

          {!form.is_active && !usedByExams && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              Bu profil hech qaysi imtihonga biriktirilmagan, ya’ni hozircha hech qanday
              ta’sirga ega emas. Uni <strong>Imtihonlar</strong> sahifasida
              «Proktorlik profili» maydonidan tanlang.
            </Alert>
          )}
        </CardContent>
      </Card>

      <Alert severity="info" sx={{ mb: 2.5 }}>
        Joriy sozlamalarda 10 000 talaba uchun taxminiy yuklama:
        <strong> ~{estimatedRps} skrinshot/sek</strong>, <strong>~{estimatedMbps} MB/s</strong> trafik.
        Skrinshot binary’si backenddan o‘tmaydi — u to‘g‘ridan-to‘g‘ri object storage’ga ketadi.
      </Alert>

      <Card>
        <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Tab icon={<FaceIcon />} iconPosition="start" label="FaceID" />
          <Tab icon={<CameraIcon />} iconPosition="start" label="Skrinshot" />
          <Tab icon={<ShieldIcon />} iconPosition="start" label="Himoya" />
          <Tab icon={<RouterIcon />} iconPosition="start" label="Tarmoq" />
        </Tabs>

        <CardContent sx={{ p: 3 }}>
          {tab === 0 && (
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Section title="Yoqish">
                  <Toggle label="Talabgor yuz tekshiruvi" checked={form.is_faceid_student} onChange={set('is_faceid_student')} disabled={!canManage} />
                  <Toggle label="Test davomida tekshirish" checked={form.is_faceid_exam} onChange={set('is_faceid_exam')} disabled={!canManage} />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Chegara ballari (0–100)">
                  <TextField label="Kirishda" type="number" value={form.faceid_min_score_student} onChange={setNumber('faceid_min_score_student')} disabled={!canManage} />
                  <TextField label="Test davomida" type="number" value={form.faceid_min_score_exam} onChange={setNumber('faceid_min_score_exam')} disabled={!canManage} />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Tezlik va bardoshlilik">
                  <TextField
                    label="Tekshiruv intervali (soniya)" type="number" value={form.faceid_interval}
                    onChange={setNumber('faceid_interval')} disabled={!canManage}
                    helperText="3 soniyadan kam qiymat qabul qilinmaydi"
                  />
                  <TextField
                    label="Maksimal ketma-ket xato" type="number" value={form.faceid_max_fail}
                    onChange={setNumber('faceid_max_fail')} disabled={!canManage}
                    helperText="Shu songa yetganda sessiya avtomatik chetlashtiriladi"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Server auditi">
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Client hisoblagan embedding’ning shu ulushi serverda qayta tekshiriladi.
                    Clientga to‘liq ishonib bo‘lmaydi — bu statistik nazorat.
                  </Typography>
                  <Box sx={{ px: 1 }}>
                    <Slider
                      value={Math.round((form.faceid_audit_rate || 0) * 100)}
                      onChange={(e, value) => setSlider('faceid_audit_rate')(e, value / 100)}
                      min={0} max={30} step={1} disabled={!canManage}
                      valueLabelDisplay="on" valueLabelFormat={(v) => `${v}%`}
                      marks={[{ value: 0, label: '0%' }, { value: 5, label: '5%' }, { value: 30, label: '30%' }]}
                    />
                  </Box>
                </Section>
              </Grid>
            </Grid>
          )}

          {tab === 1 && (
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Section title="Olish chastotasi">
                  <TextField
                    label="Interval (soniya)" type="number" value={form.screenshot_interval}
                    onChange={setNumber('screenshot_interval')} disabled={!canManage}
                    helperText={`10 000 talabada ~${estimatedRps} yuklash/sekund`}
                  />
                  <Toggle label="Ekranni yozib borish" checked={form.is_screen_record} onChange={set('is_screen_record')} disabled={!canManage} />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Sifat va hajm">
                  <TextField label="JPEG sifati (1–100)" type="number" value={form.screenshot_quality} onChange={setNumber('screenshot_quality')} disabled={!canManage} />
                  <TextField label="Maksimal kenglik (px)" type="number" value={form.screenshot_max_width} onChange={setNumber('screenshot_max_width')} disabled={!canManage} />
                  <TextField
                    label="Dedup chegarasi" type="number" value={form.screenshot_dedup_threshold}
                    onChange={setNumber('screenshot_dedup_threshold')} disabled={!canManage}
                    helperText="Kadr oldingisidan shu darajadan kam farq qilsa — yuborilmaydi. Trafikni ~10x kamaytiradi."
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Qurilma tekshiruvi">
                  <Toggle label="Monitor tekshiruvi" checked={form.is_detect_monitor} onChange={set('is_detect_monitor')} disabled={!canManage} />
                  <Toggle label="Kamera tekshiruvi" checked={form.is_detect_camera} onChange={set('is_detect_camera')} disabled={!canManage} />
                </Section>
              </Grid>
            </Grid>
          )}

          {tab === 2 && (
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Section title="Obyekt aniqlash (YOLO)">
                  <Toggle label="Yoqilgan" checked={form.is_enable_detect} onChange={set('is_enable_detect')} disabled={!canManage} />
                  <TextField label="Ishonch chegarasi (0–1)" type="number" inputProps={{ step: 0.05, min: 0.05, max: 1 }} value={form.detect_confidence} onChange={setNumber('detect_confidence')} disabled={!canManage} />
                  <TextField label="Kadr o‘tkazish" type="number" value={form.detect_frame_skip} onChange={setNumber('detect_frame_skip')} disabled={!canManage} helperText="Har nechanchi kadr tahlil qilinadi — CPU tejaladi" />
                  <Box sx={{ mt: 1 }}>
                    <Typography variant="caption" color="text.secondary">Kuzatiladigan obyektlar:</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 0.5 }}>
                      {(form.detect_classes_detail || []).map((item) => (
                        <Chip key={item.id} size="small" label={item.name} variant="outlined" />
                      ))}
                      {!form.detect_classes_detail?.length && (
                        <Typography variant="caption" color="text.secondary">—</Typography>
                      )}
                    </Stack>
                  </Box>
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Masofaviy boshqaruv (RDP)">
                  <Toggle label="Aniqlash yoqilgan" checked={form.is_enable_rdp_detect} onChange={set('is_enable_rdp_detect')} disabled={!canManage} />
                  <Stack direction="row" flexWrap="wrap" gap={0.5}>
                    {(form.rdp_objects_detail || []).map((item) => (
                      <Chip key={item.id} size="small" label={item.name} variant="outlined" color="warning" />
                    ))}
                  </Stack>
                  <Divider sx={{ my: 1.5 }} />
                  <Typography variant="caption" color="text.secondary">Bloklanadigan tugmalar:</Typography>
                  <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 0.5 }}>
                    {(form.hotkeys_detail || []).map((item) => (
                      <Chip key={item.id} size="small" label={item.name} variant="outlined" />
                    ))}
                  </Stack>
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Texnik muammolar">
                  <Toggle label="Avtomatik tekshirish" checked={form.is_enable_check_tp} onChange={set('is_enable_check_tp')} disabled={!canManage} />
                </Section>
              </Grid>
            </Grid>
          )}

          {tab === 3 && (
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Section title="Aloqa">
                  <TextField
                    label="Heartbeat intervali (soniya)" type="number" value={form.heartbeat_interval}
                    onChange={setNumber('heartbeat_interval')} disabled={!canManage}
                    helperText="Heartbeat DB’ga yozilmaydi — faqat Redis"
                  />
                  <TextField
                    label="Hodisa batch intervali (soniya)" type="number" value={form.event_batch_interval}
                    onChange={setNumber('event_batch_interval')} disabled={!canManage}
                    helperText="Client shu oynada to‘plangan hodisalarni bitta so‘rovda yuboradi"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Oflayn rejim">
                  <TextField
                    label="Lokal buffer hajmi" type="number" value={form.offline_buffer_size}
                    onChange={setNumber('offline_buffer_size')} disabled={!canManage}
                    helperText="Internet uzilganda client shuncha hodisani lokal saqlaydi va tiklanganda yuboradi"
                  />
                  <TextField label="Ogohlantirish kutish vaqti (soniya)" type="number" value={form.warning_timeout} onChange={setNumber('warning_timeout')} disabled={!canManage} />
                </Section>
              </Grid>
            </Grid>
          )}
        </CardContent>
      </Card>

      {/* --- Nusxadan yangi profil --- */}
      <Dialog open={copyName !== null} onClose={() => setCopyName(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Nusxadan yangi profil</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            «{form.name}» ning barcha qiymatlari nusxalanadi. Yangi profil global
            standart bo‘lmaydi — uni imtihonga alohida biriktirasiz.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            label="Yangi profil nomi"
            value={copyName ?? ''}
            onChange={(event) => setCopyName(event.target.value)}
            error={Boolean(copyName !== null && !copyName.trim())}
            helperText={copyName !== null && !copyName.trim() ? 'Nom bo‘sh bo‘lmasligi kerak' : ' '}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCopyName(null)}>Bekor qilish</Button>
          <Button
            variant="contained"
            disabled={!copyName?.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate(copyName.trim())}
          >
            Yaratish
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirm?.kind === 'activate'}
        title="Global standart qilinsinmi?"
        description={
          `«${form.name}» o‘z profili biriktirilmagan BARCHA imtihonlar uchun ` +
          'qo‘llanadi. Hozirgi standart oddiy profilga aylanadi.'
        }
        confirmLabel="Standart qilish"
        loading={activateMutation.isPending}
        onConfirm={() => activateMutation.mutate(form.id)}
        onClose={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={confirm?.kind === 'delete'}
        title="Profil o‘chirilsinmi?"
        description={
          usedByExams
            ? `${usedByExams} ta imtihon shu profildan foydalanadi. O‘chirilsa ular ` +
              'global standartga qaytadi.'
            : 'Bu profil hech qaysi imtihonga biriktirilmagan.'
        }
        color="error"
        confirmLabel="O‘chirish"
        confirmPhrase={form.name}
        loading={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate(form.id)}
        onClose={() => setConfirm(null)}
      />
    </>
  )
}

function Section({ title, children }) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardHeader title={title} titleTypographyProps={{ variant: 'subtitle1', fontWeight: 600 }} sx={{ pb: 0 }} />
      <CardContent>
        <Stack spacing={2}>{children}</Stack>
      </CardContent>
    </Card>
  )
}

function Toggle({ label, checked, onChange, disabled }) {
  return (
    <FormControlLabel
      control={<Switch checked={Boolean(checked)} onChange={onChange} disabled={disabled} />}
      label={label}
    />
  )
}
