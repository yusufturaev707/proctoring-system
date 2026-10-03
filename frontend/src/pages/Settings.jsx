import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Autocomplete, Box, Button, ButtonBase, Card, CardContent, CardHeader, Checkbox, Chip,
  CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, Fab, FormControlLabel, Grid, MenuItem, Radio, Slider, Stack, Switch, Tab, Tabs,
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
import CheckBoxIcon from '@mui/icons-material/CheckBox'
import ComputerOutlinedIcon from '@mui/icons-material/DesktopWindowsOutlined'
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined'
import CheckBoxBlankIcon from '@mui/icons-material/CheckBoxOutlineBlank'

import { listAll } from '../components/data/useResource'
import PageHeader from '../components/PageHeader'
import ConfirmDialog from '../components/ConfirmDialog'
import { useOptions } from '../components/data/useResource'
import {
  cocoObjects as cocoObjectsApi,
  exams as examsApi,
  hotkeys as hotkeysApi,
  proctoringPolicies as policiesApi,
  rdpObjects as rdpObjectsApi,
  settings as settingsApi,
} from '../api/endpoints'
import { useUi } from '../context/UiContext'
import { useAuth } from '../context/AuthContext'

/** Serverga yuborilmaydigan read-only maydonlar. */
const READ_ONLY = [
  'id', 'created_at', 'updated_at', 'detect_classes_detail',
  'rdp_objects_detail', 'hotkeys_detail', 'detect_model_name',
  // AI kuzatuv holati - boshqa model (`ProctoringPolicy`), profil bilan
  // birga saqlanmaydi.
  'ai_proctoring',
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
  // Sozlama profili BARCHA viloyatlarning mashinalariga amal qiladi —
  // o'zgartirish faqat respublika darajasida (`canShared`).
  const { canShared } = useAuth()
  const canManage = canShared('controls.manage')
  // AI kuzatuvni yoqish ALOHIDA ruxsat: u chetlashtirish statistikasiga
  // bevosita ta'sir qiladi (`ProctoringPoliciesPage`).
  const canManageAi = canShared('controls.proctoring_manage')

  const [tab, setTab] = useState(0)
  const [form, setForm] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [copyName, setCopyName] = useState(null)   // null = dialog yopiq
  const [confirm, setConfirm] = useState(null)     // {kind, ...}

  // Barcha profillar. Ro'yxat to'liq obyektlarni qaytaradi, shuning uchun
  // tanlaganda qo'shimcha detail so'rovi kerak emas.
  const { data: listData, isLoading } = useQuery({
    queryKey: ['settings-list'],
    queryFn: () => listAll(settingsApi),
  })
  const profiles = listData?.results ?? []

  // RDP dasturlari va tezkor tugmalar ma'lumotnomasi — tanlash uchun.
  //
  // `useOptions` CRUD sahifalari bilan BIR XIL dvigatel: u barcha
  // sahifalarni oxirigacha oladi (ro'yxat 200 tadan oshsa ham hech
  // narsa jimgina tushib qolmaydi) va natijani uzoq keshlaydi.
  // Ma'lumotnoma profildan mustaqil — profil almashtirilganda qayta
  // so'ralmaydi.
  const { options: rdpOptions } = useOptions('rdp-objects', rdpObjectsApi, (item) => ({
    value: item.id,
    label: item.name,
    code: item.code,
    is_active: item.is_active,
  }))
  const { options: hotkeyOptions } = useOptions('hotkeys', hotkeysApi, (item) => ({
    value: item.id,
    label: item.name,
    code: item.code,
    is_active: item.is_active,
  }))
  // COCO obyektlari GURUHLANGAN ko'rinadi (`CocoObjectGroup`): 80 ta
  // klass orasidan "telefon" ni topish uchun guruh sarlavhasi eng
  // tez yo'l. `groupBy` ro'yxat guruh bo'yicha TARTIBLANGAN bo'lishini
  // talab qiladi — aks holda bitta guruh ro'yxatda bir necha marta
  // takrorlanadi.
  const { options: cocoRaw } = useOptions('coco-objects', cocoObjectsApi, (item) => ({
    value: item.id,
    label: item.name,
    code: item.code,
    is_active: item.is_active,
    group: item.group_name || 'Guruhsiz',
  }))
  const cocoOptions = useMemo(
    () => [...cocoRaw].sort((left, right) => left.group.localeCompare(right.group)),
    [cocoRaw],
  )

  // Qaysi imtihonlar shu profildan foydalanadi — o'chirishdan oldin bilish shart.
  const { data: examData } = useQuery({
    queryKey: ['exams-for-settings'],
    queryFn: () => listAll(examsApi),
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

  // AI kuzatuvni SHU PROFIL uchun yoqadi: siyosat bo'lsa - kalitni,
  // bo'lmasa - standart qiymatlar bilan yangi siyosat yaratadi.
  // Profil formasidagi saqlanmagan o'zgarishlarga TEGMAYDI: faqat
  // `ai_proctoring` holati yangilanadi.
  const enableAiMutation = useMutation({
    mutationFn: () => {
      const status = form?.ai_proctoring || {}
      return status.policy_id
        ? policiesApi.update({ id: status.policy_id, is_enabled: true })
        : policiesApi.create({ setting: form.id, is_enabled: true })
    },
    onSuccess: (policy) => {
      setForm((prev) => ({
        ...prev,
        ai_proctoring: {
          policy_id: policy.id,
          enabled: Boolean(policy.is_enabled),
          objects: Boolean(policy.is_enabled && policy.enable_objects && prev.is_enable_detect),
          evidence: Boolean(policy.is_enabled && policy.evidence_enabled),
        },
      }))
      setConfirm(null)
      queryClient.invalidateQueries({ queryKey: ['settings-list'] })
      queryClient.invalidateQueries({ queryKey: ['proctoring-policies'] })
      notify('AI kuzatuv yoqildi — clientlar imtihon profilini keyingi safar olganda qo‘llanadi')
    },
    onError: notifyError,
  })

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
  // M2M maydonlar: serializer ularni ID ro'yxati sifatida oladi
  // (`rdp_objects`, `hotkeys`), `*_detail` esa faqat o'qish uchun va
  // `stripReadOnly` uni yubormaydi.
  const setIds = (name) => (ids) => setForm((prev) => ({ ...prev, [name]: ids }))

  // Bitta kadr hajmi O'LCHANGAN jadvaldan (1920 px ekran, optimallashtirilgan
  // progressiv JPEG): 1920/80 ~157 KB, sifatning har birligi ~4.9 KB,
  // kenglik bo'yicha ~1.5-daraja (960 px da 0.35 barobar).
  const shotKb = Math.max(
    10,
    (157 + ((form.screenshot_quality || 80) - 80) * 4.9) *
      (Math.min(form.screenshot_max_width || 1920, 1920) / 1920) ** 1.5,
  )
  // Skrinshot BUYRUQ bilan — har belgilangan javobga bitta kadr (taymer
  // yo'q). Hajm shuning uchun "bitta talabgor, 100 ta javob" da: interval
  // endi yo'q va sekundlik yuklama savol soniga bog'liq.
  const perCandidateMb = Math.round((100 * shotKb) / 1024)
  // Ekran yozuvi hajmi O'LCHANGAN jadvaldan (mp4v, 3 soat): 1600 px @ 5 FPS
  // ~550 MB, 1280 @ 5 ~470, 1280 @ 1 ~110, 1280 @ 8 ~730. FPS bo'yicha
  // ~0.9-daraja, kenglik bo'yicha ~0.7-daraja. Fayl MASHINADA qoladi -
  // bu diskning narxi, tarmoqniki emas.
  const recordMbPerHour = Math.round(
    (550 / 3) *
      ((form.screen_record_fps || 5) / 5) ** 0.9 *
      ((form.screen_record_width || 1600) / 1600) ** 0.7,
  )

  return (
    <>
      <PageHeader
        title="Client sozlamalari"
        subtitle="Har bir imtihon o‘z profiliga ega bo‘lishi mumkin"
        actions={
          canManage && (
            <Button
              variant="contained"
              startIcon={<SaveIcon />}
              onClick={() => saveMutation.mutate(form)}
              disabled={saveMutation.isPending}
              sx={{ display: { xs: 'none', md: 'inline-flex' } }}
            >
              Saqlash
            </Button>
          )
        }
      />

      {/* Telefonda saqlash tugmasi SUZADI (M3 extended FAB): forma uzun va
          sarlavhadagi tugma birinchi tab'ning o'rtasidayoq ko'rinmay
          qolardi — operator o'zgartirib, saqlamasdan chiqib ketardi. */}
      {canManage && (
        <Fab
          variant="extended"
          color="primary"
          onClick={() => saveMutation.mutate(form)}
          disabled={saveMutation.isPending}
          sx={{
            display: { xs: 'inline-flex', md: 'none' },
            position: 'fixed', right: 16, bottom: 'calc(16px + env(safe-area-inset-bottom))',
            zIndex: (t) => t.zIndex.speedDial,
          }}
        >
          <SaveIcon sx={{ mr: 1 }} />
          Saqlash
        </Fab>
      )}

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
              sx={{ minWidth: { md: 280 } }}
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
              // Telefonda o'raladi, tugma matni esa BO'LINMAYDI: ilgari
              // "Nusxadan yaratish" ikki qatorga sinib, uchta tugma bitta
              // tor qatorga siqilardi.
              <Stack
                direction="row"
                spacing={1}
                flexWrap="wrap"
                useFlexGap
                sx={{ '& .MuiButton-root': { whiteSpace: 'nowrap' } }}
              >
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
              sx={{ mt: 2, minWidth: { md: 320 } }}
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
        Skrinshot talabgor <strong>javob belgilaganda</strong> olinadi (test platformasi buyrug‘i).
        100 ta javobli testda bitta talabgorga ~<strong>{perCandidateMb} MB</strong>
        {form.is_screenshot_upload
          ? ' — mashinada saqlanadi va fonda serverga yuboriladi.'
          : ' — faqat client mashinasida saqlanadi, serverga yuborilmaydi.'}
      </Alert>

      <Card>
        <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ px: { xs: 0, sm: 2 }, borderBottom: 1, borderColor: 'divider' }}>
          <Tab icon={<FaceIcon />} iconPosition="start" label="FaceID" />
          <Tab icon={<CameraIcon />} iconPosition="start" label="Skrinshot va yozuv" />
          <Tab icon={<ShieldIcon />} iconPosition="start" label="Himoya" />
          <Tab icon={<RouterIcon />} iconPosition="start" label="Tarmoq" />
        </Tabs>

        <CardContent sx={{ p: { xs: 1.5, sm: 3 } }}>
          {tab === 0 && (
            <Grid container spacing={{ xs: 1.5, sm: 3 }}>
              <Grid item xs={12} md={6}>
                <Section title="Yoqish">
                  <Toggle label="Talabgor yuz tekshiruvi" checked={form.is_faceid_student} onChange={set('is_faceid_student')} disabled={!canManage} />
                  <Toggle label="Test davomida tekshirish" checked={form.is_faceid_exam} onChange={set('is_faceid_exam')} disabled={!canManage} />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Chegara ballari (0–100)">
                  {/* Ball = cosine o'xshashlik × 100 (manfiysi 0 ga
                      siqiladi). Amaliy oraliq: bir xil odam odatda
                      40–70, butunlay boshqa odam 0–15. */}
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Ball — yuz vektorlari o‘xshashligi × 100. Bir xil odamning hujjat
                    rasmi va jonli kadri odatda 40–70, butunlay boshqa odam 0–15 beradi.
                  </Typography>
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
                  {/* Chegaraga yetilganda server sessiyani TO'XTATMAYDI —
                      kritik `high_suspicion_identity` hodisasini beradi,
                      qarorni proktor qabul qiladi. Ilgari yozuv
                      "avtomatik chetlashtiriladi" deb va'da qilardi. */}
                  <TextField
                    label="Maksimal ketma-ket xato" type="number" value={form.faceid_max_fail}
                    onChange={setNumber('faceid_max_fail')} disabled={!canManage}
                    helperText="Shu songa yetganda proktorga kritik ogohlantirish ketadi (sessiya to‘xtatilmaydi)"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                {/* Ilgari bu to'rttasi har mashinaning .env faylida edi.
                    Endi client ularni imtihon profilidan oladi, .env esa
                    faqat zaxira (server javob bermasa). */}
                <Section title="Kirish tekshiruvi oqimi">
                  <TextField
                    label="Joylashish sanog‘i (soniya)" type="number"
                    value={form.faceid_guide_seconds}
                    onChange={setNumber('faceid_guide_seconds')} disabled={!canManage}
                    inputProps={{ min: 0, max: 30 }}
                    helperText="Kamera ochilgach yuzni ovalga joylash vaqti. 0 — sanoqsiz, tekshiruv darhol"
                  />
                  <TextField
                    label="Tasdiq uchun ketma-ket kadr" type="number"
                    value={form.faceid_match_streak}
                    onChange={setNumber('faceid_match_streak')} disabled={!canManage}
                    inputProps={{ min: 1, max: 30 }}
                    helperText="Bitta kadr yetarli emas — tasodifiy rakurs yolg‘on natija berishi mumkin"
                  />
                  <TextField
                    label="Rad uchun ketma-ket kadr" type="number"
                    value={form.faceid_fail_streak}
                    onChange={setNumber('faceid_fail_streak')} disabled={!canManage}
                    inputProps={{ min: 1, max: 300 }}
                  />
                  <TextField
                    label="Rad uchun minimal vaqt (soniya)" type="number"
                    value={form.faceid_fail_min_seconds}
                    onChange={setNumber('faceid_fail_min_seconds')} disabled={!canManage}
                    inputProps={{ min: 1, max: 120 }}
                    helperText="Urinish IKKALA shart bajarilganda yopiladi: kadrlar soni VA shu vaqt. Ko‘zoynagini to‘g‘rilayotgan haqiqiy talabgor «kira olmadi» bo‘lib qolmasligi uchun"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                {/* Yuz kadrda bor, lekin solishtirish uchun kichik — davriy
                    tekshiruv "solishtirib bo'lmadi" deydi va serverga hech
                    narsa ketmaydi. Usiz talabgor kameradan uzoq o'tirib shaxs
                    tekshiruvini jimgina chetlab o'tardi (client
                    `face_presence.py`). */}
                <Section title="Test davomida: yuz uzoqda">
                  <TextField
                    label="Ogohlantirish (soniya)" type="number"
                    value={form.faceid_far_warn_s}
                    onChange={setNumber('faceid_far_warn_s')} disabled={!canManage}
                    inputProps={{ min: 1, max: 600 }}
                    helperText="Shuncha uzluksiz uzoq o‘tirsa — past jiddiylikdagi hodisa. Suyanib o‘tirish tabiiy, juda kichik qilmang"
                  />
                  <TextField
                    label="Shaxs tasdiqlanmadi (soniya)" type="number"
                    value={form.faceid_far_unverified_s}
                    onChange={setNumber('faceid_far_unverified_s')} disabled={!canManage}
                    inputProps={{ min: 1, max: 3600 }}
                    helperText="Shuncha vaqt yuzni solishtirib bo‘lmasa — o‘rta jiddiylikdagi hodisa. Ogohlantirishdan kam bo‘lmaydi"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Server auditi (ishlamaydi)">
                  {/* Maydon SAQLANGAN, lekin uni hech kim o'qimaydi:
                      server ballni qayta hisoblay olmaydi — buning
                      uchun rasmdan embedding olish, ya'ni serverda ML
                      runtime kerak. Slayderni "ishlaydi" deb
                      ko'rsatish administratorga mavjud bo'lmagan
                      himoyani va'da qilardi. */}
                  <Alert severity="info" sx={{ mb: 1 }}>
                    Bu sozlama hozircha QO‘LLANMAYDI. Solishtirish client dasturda
                    bajariladi, server esa ballni qayta hisoblay olmaydi (buning uchun
                    unda yuz modeli yo‘q). Maydon kelajakdagi GPU servisi uchun
                    saqlab qolindi.
                  </Alert>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Client hisoblagan embedding’ning shu ulushi serverda qayta tekshirilishi
                    ko‘zda tutilgan edi.
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
            <Grid container spacing={{ xs: 1.5, sm: 3 }}>
              <Grid item xs={12} md={6}>
                {/* Skrinshot TAYMERSIZ: test platformasi javob belgilanganda
                    client'ning lokal xizmatiga buyruq yuboradi
                    (`client/services/local_service.py`). Kadr mashinada
                    HAR DOIM qoladi — tanlov faqat serverga yuborish. */}
                <Section title="Saqlash joyi">
                  <Typography variant="body2" color="text.secondary">
                    Kadr javob belgilangan lahzada olinadi va client mashinasida har doim saqlanadi.
                  </Typography>
                  <ChoiceCards
                    value={form.is_screenshot_upload ? 'server' : 'local'}
                    disabled={!canManage}
                    onChange={(value) => setForm((prev) => ({ ...prev, is_screenshot_upload: value === 'server' }))}
                    options={[
                      {
                        value: 'local', icon: <ComputerOutlinedIcon />, title: 'Faqat mashinada',
                        text: 'Serverga trafik yo‘q. Proktor skrinshotni panelda ko‘rmaydi — komissiya uni mashinadan oladi.',
                      },
                      {
                        value: 'server', icon: <CloudUploadOutlinedIcon />, title: 'Mashinada + serverga',
                        text: 'Fonda, imtihonga xalaqit bermasdan yuboriladi. Proktor panelda real vaqtda ko‘radi.',
                      },
                    ]}
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Sifat va hajm">
                  <TextField label="JPEG sifati (1–100)" type="number" value={form.screenshot_quality} onChange={setNumber('screenshot_quality')} disabled={!canManage} />
                  <TextField
                    label="Maksimal kenglik (px)" type="number" value={form.screenshot_max_width}
                    onChange={setNumber('screenshot_max_width')} disabled={!canManage}
                    helperText={`Kadr ~${Math.round(shotKb)} KB. 1920 — ekrandagidek; 1280 dan kichigida test matni o‘qilmay qoladi.`}
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Kamera tasmasi">
                  {/* Kamera kadri skrinshot OSTIGA qo'shilgan tasmaga
                      chiziladi — ekran tasviri yopilmaydi, lekin har kadr
                      ~24% og'irlashadi. */}
                  <Toggle
                    label="Skrinshotga kamera kadrini qo‘shish"
                    checked={form.is_screenshot_camera_overlay}
                    onChange={set('is_screenshot_camera_overlay')} disabled={!canManage}
                  />
                  <TextField
                    label="Kamera ramkasi (% kenglik)" type="number"
                    value={form.screenshot_pip_percent}
                    onChange={setNumber('screenshot_pip_percent')}
                    disabled={!canManage || !form.is_screenshot_camera_overlay}
                    inputProps={{ min: 5, max: 40 }}
                    helperText="Skrinshot kengligiga nisbatan. Tasma kadrni ~24% og‘irlashtiradi — trafikka qarang"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                {/* Yozuv MASHINADA qoladi (serverga faqat manzili boradi).
                    Ilgari bu kalit panelda bor edi, lekin client uni
                    o'qimasdi va ekranni .env bo'yicha doim yozardi. */}
                <Section title="Ekran yozuvi">
                  <Toggle label="Ekranni yozib borish" checked={form.is_screen_record} onChange={set('is_screen_record')} disabled={!canManage} />
                  <TextField
                    label="Kadr chastotasi (FPS)" type="number"
                    value={form.screen_record_fps}
                    onChange={setNumber('screen_record_fps')}
                    disabled={!canManage || !form.is_screen_record}
                    inputProps={{ min: 1, max: 15 }}
                    helperText="5 — silliq; 1 da yozuv «qotib-qotib» ko‘rinadi, 8 dan yuqorisi sezilarli foyda bermaydi"
                  />
                  <TextField
                    label="Yozuv kengligi (px)" type="number"
                    value={form.screen_record_width}
                    onChange={setNumber('screen_record_width')}
                    disabled={!canManage || !form.is_screen_record}
                    inputProps={{ min: 640, max: 3840 }}
                    helperText={`Taxminan ~${recordMbPerHour} MB/soat mashina diskida. 1280 dan pastida kichik shriftli savol o‘qilmay qoladi`}
                  />
                  <TextField
                    label="Kamera oynasi (% kenglik)" type="number"
                    value={form.screen_record_pip_percent}
                    onChange={setNumber('screen_record_pip_percent')}
                    disabled={!canManage || !form.is_screen_record}
                    inputProps={{ min: 5, max: 30 }}
                    helperText="Yozuvning o‘ng yuqori burchagida. Katta oyna test sahifasini yopadi"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Qurilma tekshiruvi">
                  <Toggle label="Monitor tekshiruvi" checked={form.is_detect_monitor} onChange={set('is_detect_monitor')} disabled={!canManage} />
                  <Toggle label="Kamera tekshiruvi" checked={form.is_detect_camera} onChange={set('is_detect_camera')} disabled={!canManage} />
                  <Toggle label="Qo‘shimcha qurilmalar (fleshka, telefon, naushnik…)" checked={form.is_detect_peripherals} onChange={set('is_detect_peripherals')} disabled={!canManage} />
                </Section>
              </Grid>
            </Grid>
          )}

          {tab === 2 && (
            <Grid container spacing={{ xs: 1.5, sm: 3 }}>
              <Grid item xs={12} md={6}>
                <Section title="Obyekt aniqlash (YOLO)">
                  <Toggle label="Yoqilgan" checked={form.is_enable_detect} onChange={set('is_enable_detect')} disabled={!canManage} />
                  <AiProctoringNotice
                    status={form.ai_proctoring}
                    detectEnabled={form.is_enable_detect}
                    canManageAi={canManageAi}
                    onEnable={() => setConfirm({ kind: 'enable-ai' })}
                  />
                  <TextField label="Ishonch chegarasi (0–1)" type="number" inputProps={{ step: 0.05, min: 0.05, max: 1 }} value={form.detect_confidence} onChange={setNumber('detect_confidence')} disabled={!canManage} />
                  <TextField label="Kadr o‘tkazish" type="number" value={form.detect_frame_skip} onChange={setNumber('detect_frame_skip')} disabled={!canManage} helperText="Har nechanchi kadr tahlil qilinadi — CPU tejaladi" />
                  {/* Klasslar clientga `detection.classes` bo'lib
                      ketadi va YOLO faqat shularni qidiradi. Bo'sh
                      ro'yxat — obyekt aniqlash amalda o'chirilgan
                      (model yuklanadi, lekin hech nima topilmaydi). */}
                  <MultiPicker
                    label="Kuzatiladigan obyektlar"
                    options={cocoOptions}
                    value={form.detect_classes}
                    onChange={setIds('detect_classes')}
                    disabled={!canManage}
                    groupBy={(option) => option.group}
                    helperText={
                      form.is_enable_detect
                        ? 'Tanlanmasa — model hech qanday obyektni qidirmaydi'
                        : 'Aniqlash o‘chirilgan — ro‘yxat saqlanadi, lekin qo‘llanmaydi'
                    }
                    emptyText="COCO obyektlari ma’lumotnomasi bo‘sh"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Masofaviy boshqaruv (RDP)">
                  <Toggle label="Aniqlash yoqilgan" checked={form.is_enable_rdp_detect} onChange={set('is_enable_rdp_detect')} disabled={!canManage} />
                  {/* Tanlanganlari clientga jarayon NOMLARI bo'lib ketadi
                      (`RdpObject.process_names`), ya'ni bu ro'yxat
                      "qaysi dasturlar qidiriladi" degan savolga javob
                      beradi. Bo'sh ro'yxat — hech nima qidirilmaydi. */}
                  <MultiPicker
                    label="Aniqlanadigan dasturlar"
                    options={rdpOptions}
                    value={form.rdp_objects}
                    onChange={setIds('rdp_objects')}
                    // Aniqlash o'chirilganda ham TAHRIRLASH mumkin:
                    // ro'yxatni oldindan tayyorlab, keyin yoqish
                    // odatiy ish tartibi. Holat esa pastda yozilgan.
                    disabled={!canManage}
                    helperText={
                      form.is_enable_rdp_detect
                        ? 'Tanlanmasa — masofaviy boshqaruv dasturlari qidirilmaydi'
                        : 'Aniqlash o‘chirilgan — ro‘yxat saqlanadi, lekin qo‘llanmaydi'
                    }
                    emptyText="RDP dasturlar ma’lumotnomasi bo‘sh"
                  />
                  {/* Skanerning o'zi (yoqilishi, ruxsat ro'yxati) client
                      .env faylida — u dastur ishga tushganda, serverdan
                      OLDIN ishlaydi. Bu yerda faqat imtihon qarori. */}
                  <Toggle
                    label="Yo‘q qilinmagan dastur imtihonni to‘sadi"
                    checked={form.is_threat_block_exam}
                    onChange={set('is_threat_block_exam')} disabled={!canManage}
                  />
                  <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5 }}>
                    O‘chirilsa hodisa baribir yoziladi va proktor ko‘radi, lekin operator
                    imtihonni boshlay oladi (masalan administrator huquqi yetmay xizmat
                    to‘xtamagan holatda).
                  </Typography>
                  <Divider sx={{ my: 0.5 }} />
                  {/* Tugmalar clientga uch marta ketadi: preflight'da
                      (login'dan oldin), handshake'da va imtihon profilida.
                      Undan OLDIN (dastur ochilishi bilan) clientning
                      .env dagi BLOCKED_HOTKEYS standarti ishlaydi; bo'sh
                      ro'yxat o'sha standartni qoldiradi. */}
                  <MultiPicker
                    label="Bloklanadigan tezkor tugmalar"
                    options={hotkeyOptions}
                    value={form.hotkeys}
                    onChange={setIds('hotkeys')}
                    disabled={!canManage}
                    helperText="Tanlanmasa — client o‘z standart ro‘yxatini (.env) qo‘llaydi. Kiosk rejimida ishlaydi; ctrl+q hech qachon bloklanmaydi"
                    emptyText="Tezkor tugmalar ma’lumotnomasi bo‘sh"
                  />
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
            <Grid container spacing={{ xs: 1.5, sm: 3 }}>
              <Grid item xs={12} md={6}>
                <Section title="Aloqa">
                  {/* Yuqori chegara serverdagi HEARTBEAT_TIMEOUT ning yarmi
                      (standart 45 s) — uni server tekshiradi va xato
                      matnini qaytaradi. */}
                  <TextField
                    label="Heartbeat intervali (soniya)" type="number" value={form.heartbeat_interval}
                    onChange={setNumber('heartbeat_interval')} disabled={!canManage}
                    inputProps={{ min: 5 }}
                    helperText="5–45 s. Katta qiymatda ishlab turgan client ham panelda «aloqa yo‘q» bo‘lib ko‘rinadi"
                  />
                  <TextField
                    label="Hodisa batch intervali (soniya)" type="number" value={form.event_batch_interval}
                    onChange={setNumber('event_batch_interval')} disabled={!canManage}
                    inputProps={{ min: 1, max: 60 }}
                    helperText="Client shu oynada to‘plangan hodisalarni bitta so‘rovda yuboradi"
                  />
                </Section>
              </Grid>
              <Grid item xs={12} md={6}>
                <Section title="Oflayn rejim">
                  <TextField
                    label="Lokal buffer hajmi" type="number" value={form.offline_buffer_size}
                    onChange={setNumber('offline_buffer_size')} disabled={!canManage}
                    inputProps={{ min: 100, max: 50000 }}
                    helperText="Internet uzilganda client shuncha hodisani xotirada ushlaydi va tiklanganda yuboradi"
                  />
                  <TextField label="Ogohlantirish kutish vaqti (soniya)" type="number" value={form.warning_timeout} onChange={setNumber('warning_timeout')} disabled={!canManage} />
                </Section>
              </Grid>
              <Grid item xs={12}>
                {/* Ikki qatlam chegarasi administratorga ko'rinib turishi
                    kerak: "panelda topolmadim" degan savol ko'pincha
                    sozlama umuman panelga tegishli emasligidan chiqadi. */}
                <Alert severity="info" variant="outlined">
                  Mashinaga xos sozlamalar panelda YO‘Q — ular har bir kompyuterdagi client
                  <code> .env </code> faylida: server manzili, kamera indeksi va kadr o‘lchami,
                  GPU, kiosk rejimi, ortiqcha monitorlar, ishga tushishda dasturlarni yopish,
                  tahdid skanerining ruxsat ro‘yxati, mahalliy arxiv (disk va muddat) va
                  standart tezkor tugmalar. Ular serverga ulanishdan oldin kerak yoki apparatga
                  bog‘liq. «Client ishlab turibdi» signali oralig‘ini server o‘zi belgilaydi.
                </Alert>
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
        open={confirm?.kind === 'enable-ai'}
        title="AI kuzatuv yoqilsinmi?"
        description={
          `«${form.name}» profilidagi imtihonlarda kamera orqali AI kuzatuv ishlaydi: ` +
          'yuz, nigoh va (model bo‘lsa) obyekt aniqlash, hodisalar xavf balliga qo‘shiladi, ' +
          'tasdiqlangan hodisadan kamera klipi yoziladi. Yuz kamerasi MAJBURIY bo‘ladi.'
        }
        details="Chegaralar va modullarni «AI kuzatuv → Kuzatuv siyosati» bo‘limida sozlash mumkin."
        confirmLabel="Yoqish"
        loading={enableAiMutation.isPending}
        onConfirm={() => enableAiMutation.mutate()}
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
      {/* Suzuvchi tugma oxirgi maydonni yopmasligi uchun joy. */}
      {canManage && <Box sx={{ height: { xs: 72, md: 0 } }} />}
    </>
  )
}

/**
 * Ko'p tanlovli ro'yxat (RDP dasturlari, tezkor tugmalar).
 *
 * KO'RINISH `ResourceForm` DAGI `multiselect` BILAN BIR XIL: belgili
 * variantlar, tanlanganlari chip bo'lib qoladi, pastda soni. Sozlamalar
 * sahifasi CRUD dvigatelidan tashqarida (u yagona obyektni tahrirlaydi,
 * ro'yxatni emas), lekin operator uchun ikkalasi bir xil ko'rinishi
 * kerak — aks holda bir xil amal ikki joyda ikki xil ishlaydi.
 *
 * NOFAOL YOZUVLAR KO'RSATILADI, lekin belgilanadi: `get_client_config`
 * ularni clientga UMUMAN yubormaydi (`if obj.is_active`). Ro'yxatdan
 * yashirish "tanladim, lekin ishlamayapti" holatini tushuntirib
 * bo'lmaydigan qilardi, jimgina qo'shib qo'yish esa yolg'on bo'lardi.
 */
function MultiPicker({
  label, options, value, onChange, disabled, helperText, emptyText, groupBy,
}) {
  const selected = Array.isArray(value) ? value : []
  const picked = options.filter((option) => selected.includes(option.value))

  if (!options.length) {
    return (
      <TextField
        label={label}
        value=""
        disabled
        helperText={emptyText || 'Ro‘yxat bo‘sh — avval ma’lumotnomaga qo‘shing'}
      />
    )
  }

  return (
    <Autocomplete
      multiple
      disableCloseOnSelect
      options={options}
      value={picked}
      onChange={(_, next) => onChange(next.map((option) => option.value))}
      disabled={disabled}
      getOptionLabel={(option) => option.label ?? ''}
      isOptionEqualToValue={(option, item) => option.value === item.value}
      groupBy={groupBy}
      limitTags={6}
      renderOption={(props, option, { selected: isSelected }) => {
        const { key, ...rest } = props
        return (
          <li key={key} {...rest}>
            <Checkbox
              size="small"
              icon={<CheckBoxBlankIcon fontSize="small" />}
              checkedIcon={<CheckBoxIcon fontSize="small" />}
              checked={isSelected}
              sx={{ mr: 1, p: 0.5 }}
            />
            <Stack spacing={0}>
              <Typography variant="body2">{option.label}</Typography>
              <Typography variant="caption" color="text.secondary">
                {option.code}
                {option.is_active === false ? ' • nofaol' : ''}
              </Typography>
            </Stack>
          </li>
        )
      }}
      renderTags={(items, getTagProps) =>
        items.map((option, index) => {
          const { key, ...rest } = getTagProps({ index })
          return (
            <Chip
              key={key}
              {...rest}
              size="small"
              label={option.label}
              variant="outlined"
              color={option.is_active === false ? 'default' : 'primary'}
            />
          )
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          helperText={
            selected.length ? `${selected.length} ta tanlangan` : helperText
          }
        />
      )}
    />
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

/**
 * MD3 tanlov kartalari (radio) — ikki-uch variantli qaror uchun.
 *
 * Kalit (Switch) o'rniga: "serverga yuborishni o'chirish" nimani
 * anglatishi (skrinshot yo'qoladimi?) kalit yonidagi matndan
 * tushunilmaydi, karta esa har variantning oqibatini yonma-yon aytadi.
 */
function ChoiceCards({ value, options, onChange, disabled }) {
  return (
    <Stack spacing={1} role="radiogroup">
      {options.map((option) => {
        const selected = option.value === value
        return (
          <ButtonBase
            key={option.value}
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            sx={{
              display: 'flex', alignItems: 'flex-start', gap: 1.5, p: 1.5, width: '100%',
              textAlign: 'left', borderRadius: '16px', border: 1,
              borderColor: selected ? 'primary.main' : 'divider',
              bgcolor: selected ? 'm3.secondaryContainer' : 'transparent',
              transition: (theme) => theme.transitions.create(['background-color', 'border-color'], { duration: 150 }),
              '&:hover': { bgcolor: selected ? 'm3.secondaryContainer' : 'action.hover' },
              opacity: disabled ? 0.6 : 1,
            }}
          >
            <Box
              sx={{
                width: 40, height: 40, borderRadius: '12px', flexShrink: 0, display: 'grid', placeItems: 'center',
                bgcolor: selected ? 'primary.main' : 'm3.surfaceContainerHigh',
                color: selected ? 'primary.contrastText' : 'text.secondary',
              }}
            >
              {option.icon}
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="subtitle2" fontWeight={700}>{option.title}</Typography>
              <Typography variant="body2" color="text.secondary">{option.text}</Typography>
            </Box>
            <Radio checked={selected} size="small" tabIndex={-1} sx={{ mt: -0.5, mr: -0.5 }} />
          </ButtonBase>
        )
      })}
    </Stack>
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

/**
 * AI kuzatuv holati - YOLO kaliti yonida.
 *
 * YOLO bu profilda yoqiladi, AI kuzatuvning bosh kaliti esa
 * boshqa bo'limda (`ProctoringPolicy`). Ikkalasi ham kerak va
 * ilgari ekranda buni aytadigan hech narsa yo'q edi: administrator
 * YOLO ni yoqar, siyosat esa yaratilmagan bo'lar va client jimgina
 * AI siz ishlardi. Shuning uchun holat SHU YERDA ko'rinadi va
 * yoqish bir bosishda.
 */
function AiProctoringNotice({ status, detectEnabled, canManageAi, onEnable }) {
  const enabled = Boolean(status?.enabled)

  if (enabled) {
    return (
      <Alert severity="success" variant="outlined" sx={{ py: 0.25 }}>
        AI kuzatuv yoqilgan
        {detectEnabled && !status?.objects && (
          <> — lekin siyosatda «Obyekt aniqlash» moduli o‘chiq, YOLO ishlamaydi</>
        )}
        . Chegaralar: «AI kuzatuv → Kuzatuv siyosati».
      </Alert>
    )
  }

  return (
    <Alert
      severity={detectEnabled ? 'warning' : 'info'}
      variant="outlined"
      action={
        canManageAi ? (
          <Button color="inherit" size="small" onClick={onEnable} sx={{ whiteSpace: 'nowrap' }}>
            AI kuzatuvni yoqish
          </Button>
        ) : null
      }
    >
      {detectEnabled
        ? 'YOLO yoqilgan, lekin bu profil uchun AI kuzatuv O‘CHIQ — obyekt aniqlash ishlamaydi. '
        : 'Bu profil uchun AI kuzatuv o‘chiq. '}
      {status?.policy_id
        ? 'Kuzatuv siyosati bor, lekin o‘chirilgan.'
        : 'Kuzatuv siyosati yaratilmagan.'}
      {!canManageAi && ' Yoqish uchun «AI kuzatuv» ruxsati kerak.'}
    </Alert>
  )
}
