import { Alert, Chip, Stack, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { useSettingOptions } from './shared'
import { proctoringPolicies as policiesApi } from '../../api/endpoints'

const CAMERA_KIND = [
  { value: 'auto', label: 'Ixtiyoriy (biriktirishga qarab)' },
  { value: 'local', label: 'Lokal veb-kamera' },
  { value: 'ip', label: 'IP kamera' },
]

const LOST_ACTION = [
  { value: 'warn', label: 'Ogohlantirish' },
  { value: 'pause', label: 'Imtihonni to‘xtatib turish' },
  { value: 'terminate', label: 'Chetlashtirish' },
]

const GPU_PROFILE = [
  { value: 'auto', label: 'Avtomatik (client aniqlaydi)' },
  { value: 'high', label: 'Yuqori' },
  { value: 'medium', label: 'O‘rta' },
  { value: 'low', label: 'Past' },
  { value: 'cpu', label: 'Faqat CPU' },
  { value: 'minimal', label: 'Minimal (faqat yuz)' },
]

const SEVERITY = [
  { value: 1, label: '1 — past' },
  { value: 2, label: '2 — o‘rta' },
  { value: 3, label: '3 — yuqori' },
  { value: 4, label: '4 — kritik' },
]

/** Yoqilgan modullar ustuni — profilni bir qarashda tushunish uchun. */
function ModulesCell({ row }) {
  const modules = [
    [row.enable_identity, 'Shaxs'],
    [row.enable_objects, 'Obyekt'],
    [row.enable_pose, 'Poza'],
    [row.enable_gaze, 'Nigoh'],
  ].filter(([enabled]) => enabled)

  if (!modules.length) {
    return <Typography variant="body2" color="text.disabled">—</Typography>
  }
  return (
    <Stack direction="row" spacing={0.5}>
      {modules.map(([, label]) => (
        <Chip key={label} size="small" variant="outlined" label={label} />
      ))}
    </Stack>
  )
}

/**
 * AI kuzatuv siyosati — har bir client profili uchun bittadan.
 *
 * NIMA UCHUN `Setting` DAN ALOHIDA. Ular bir-birini takrorlamaydi:
 * obyekt aniqlashning "yoqilganmi", "qanday ishonch bilan" va "qaysi
 * klasslar" degan savollari `Setting` da qoladi, siyosat esa faqat
 * qo'shimchasini beradi — necha kadr ketma-ket kelsin, qancha davom
 * etsin, ball qanday pasaysin. Ikkalasini bitta formaga qo'shish
 * 70 maydonli, hech kim oxirigacha o'qimaydigan ekran berardi.
 *
 * MUHIM: bu yerdagi qiymatlar chetlashtirish statistikasiga BEVOSITA
 * ta'sir qiladi, shuning uchun ruxsat ham alohida
 * (`controls.proctoring_manage`, `controls.manage` EMAS).
 */
export default function ProctoringPoliciesPage() {
  const { options: settingOptions } = useSettingOptions()

  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Kuzatuv siyosati"
      subtitle="Kamera talablari, modullar, tasdiqlash chegaralari va xavf balli"
      queryKey="proctoring-policies"
      api={policiesApi}
      permission="controls.proctoring_manage"
      searchPlaceholder="Profil nomi bo‘yicha…"
      defaultSort={{ field: 'setting__name', sort: 'asc' }}
      formMaxWidth="md"
      getRowLabel={(row) => row?.setting_name}
      deleteDescription={
        'Siyosat o‘chirilsa profil STANDART qiymatlarga qaytadi — AI kuzatuv ' +
        'butunlay o‘chmaydi, faqat bu yerda sozlangan chegaralar yo‘qoladi.'
      }
      banner={
        <Alert severity="info" variant="outlined">
          Har bir client profili uchun bitta siyosat. Siyosat biriktirilmagan
          profil standart qiymatlar bilan ishlaydi va unda AI kuzatuv{' '}
          <b>o‘chirilgan</b> bo‘ladi — uni shu yerda ochiq yoqish kerak.
        </Alert>
      }
      defaults={{
        is_enabled: false,
        camera_count: 1,
        primary_camera_kind: 'auto',
        secondary_camera_kind: 'auto',
        primary_required: true,
        secondary_required: false,
        allow_virtual_camera: false,
        min_fps: 12,
        min_width: 640,
        min_height: 480,
        camera_lost_grace_s: 15,
        camera_lost_action: 'warn',
        enable_identity: true,
        enable_objects: true,
        enable_pose: false,
        enable_gaze: true,
        enable_tracking: true,
        identity_fps: 10,
        object_fps: 6,
        pose_fps: 8,
        gaze_fps: 10,
        gpu_profile_override: 'auto',
        no_face_warn_s: 2,
        no_face_suspicious_s: 5,
        gaze_away_warn_s: 2,
        gaze_away_suspicious_s: 5,
        object_min_frames: 5,
        object_min_conf: 0.8,
        object_min_duration_ms: 1200,
        fusion_window_ms: 3000,
        risk_decay_per_min: 5,
        risk_event_cooldown_s: 60,
        threshold_low: 20,
        threshold_medium: 40,
        threshold_high: 70,
        evidence_enabled: true,
        evidence_clip_seconds: 5,
        evidence_min_severity: 2,
        evidence_clip_retention_days: 30,
        evidence_frame_retention_days: 90,
      }}
      columns={[
        {
          field: 'setting_name', headerName: 'Profil', flex: 1, minWidth: 200,
          renderCell: (params) => (
            <Stack direction="row" spacing={0.75} alignItems="center">
              <Typography variant="body2">{params.value || '—'}</Typography>
              {params.row.setting_is_active && (
                <Chip size="small" color="success" variant="outlined" label="global" />
              )}
            </Stack>
          ),
        },
        {
          field: 'camera_count', headerName: 'Kamera', width: 110, type: 'number',
          renderCell: (params) => (
            <Typography variant="body2">
              {params.value}
              {params.row.secondary_required ? ' (2-si majburiy)' : ''}
            </Typography>
          ),
        },
        {
          field: 'modules', headerName: 'Modullar', flex: 1, minWidth: 230, sortable: false,
          exportValue: (_value, row) =>
            [
              row.enable_identity && 'Shaxs',
              row.enable_objects && 'Obyekt',
              row.enable_pose && 'Poza',
              row.enable_gaze && 'Nigoh',
            ].filter(Boolean).join(', '),
          renderCell: (params) => <ModulesCell row={params.row} />,
        },
        {
          field: 'threshold_high', headerName: 'Yuqori xavf', width: 130, type: 'number',
          renderCell: (params) => (
            <Chip size="small" color="error" variant="outlined" label={`≥ ${params.value}`} />
          ),
        },
        {
          field: 'evidence_enabled', headerName: 'Dalil', width: 110,
          exportValue: (value) => (value ? 'yoqilgan' : 'o‘chirilgan'),
          renderCell: (params) => (
            <Chip
              size="small"
              color={params.value ? 'info' : 'default'}
              variant={params.value ? 'filled' : 'outlined'}
              label={params.value ? 'Yoqilgan' : 'Yo‘q'}
            />
          ),
        },
      ]}
      toggleField="is_enabled"
      toggleLabel="AI kuzatuv"
      exportName="ai-kuzatuv-siyosati"
      filters={[
        { name: 'setting', label: 'Profil', type: 'select', options: settingOptions },
        {
          name: 'is_enabled', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Yoqilgan' }, { value: 'false', label: 'O‘chirilgan' }],
        },
      ]}
      fields={[
        // --- Asosiy ---
        {
          name: 'setting', label: 'Client profili', type: 'select', required: true,
          options: settingOptions, colSpan: 8, section: 'Asosiy',
          // Profilni almashtirish "kuzatuv sozlamasi qayerdan keldi?"
          // degan savolni tarixdan yo'qotardi, shuning uchun server
          // uni tahrirlashda rad etadi.
          helperText: (isEdit) =>
            isEdit
              ? 'Profilni almashtirib bo‘lmaydi'
              : 'Har bir profil uchun bitta siyosat',
          disabled: (form, isEdit) => isEdit,
        },
        {
          name: 'is_enabled', label: 'AI kuzatuv yoqilgan', type: 'boolean',
          colSpan: 4, section: 'Asosiy',
        },

        // --- Kamera ---
        {
          name: 'camera_count', label: 'Kameralar soni', type: 'number', required: true,
          min: 1, max: 2, integer: true, colSpan: 4, section: 'Kamera',
          helperText: 'Ko‘pi bilan 2 ta: yuz va xona',
        },
        {
          name: 'primary_camera_kind', label: 'Birlamchi kamera turi', type: 'select',
          options: CAMERA_KIND, colSpan: 4, section: 'Kamera',
        },
        {
          name: 'secondary_camera_kind', label: 'Ikkilamchi kamera turi', type: 'select',
          options: CAMERA_KIND, colSpan: 4, section: 'Kamera',
          hidden: (form) => Number(form.camera_count) < 2,
        },
        {
          name: 'primary_required', label: 'Birlamchi majburiy', type: 'boolean',
          colSpan: 4, section: 'Kamera',
          helperText: 'Bo‘lmasa imtihon boshlanmaydi',
        },
        {
          name: 'secondary_required', label: 'Ikkilamchi majburiy', type: 'boolean',
          colSpan: 4, section: 'Kamera',
          hidden: (form) => Number(form.camera_count) < 2,
        },
        {
          name: 'allow_virtual_camera', label: 'Virtual kameraga ruxsat', type: 'boolean',
          colSpan: 4, section: 'Kamera',
          // Virtual qurilma - sifat masalasi emas, XAVFSIZLIK qoidasi:
          // oldindan yozilgan videoni jonli oqim sifatida ko'rsatish
          // eng oson yo'l aynan shu.
          helperText: 'OBS/ManyCam — yozib olingan videoni jonli ko‘rsatish yo‘li',
        },
        {
          name: 'min_fps', label: 'Minimal FPS', type: 'number', required: true,
          min: 1, max: 60, integer: true, colSpan: 4, section: 'Kamera',
          helperText: 'O‘lchangan, e’lon qilingan emas',
        },
        {
          name: 'min_width', label: 'Minimal kenglik', type: 'number', required: true,
          min: 160, max: 4096, integer: true, colSpan: 4, section: 'Kamera',
        },
        {
          name: 'min_height', label: 'Minimal balandlik', type: 'number', required: true,
          min: 120, max: 2160, integer: true, colSpan: 4, section: 'Kamera',
        },
        {
          name: 'camera_lost_grace_s', label: 'Uzilishga chidam (s)', type: 'number',
          required: true, min: 0, max: 300, integer: true, colSpan: 6, section: 'Kamera',
          helperText: 'Ko‘pchilik uzilish — 15 soniyalik USB nosozligi',
        },
        {
          name: 'camera_lost_action', label: 'Uzilgandan keyin', type: 'select',
          options: LOST_ACTION, colSpan: 6, section: 'Kamera',
        },

        // --- Modullar ---
        {
          name: 'enable_identity', label: 'Shaxs (FaceID)', type: 'boolean',
          colSpan: 4, section: 'Modullar',
        },
        {
          name: 'enable_objects', label: 'Obyekt aniqlash (YOLO)', type: 'boolean',
          colSpan: 4, section: 'Modullar',
          // Client'ga BITTA qiymat ketadi - ikkalasining mantiqiy VA'si.
          helperText: 'Profilda ham yoqilgan bo‘lishi shart',
        },
        {
          name: 'enable_pose', label: 'Poza va qo‘llar', type: 'boolean',
          colSpan: 4, section: 'Modullar',
        },
        {
          name: 'enable_gaze', label: 'Nigoh va bosh holati', type: 'boolean',
          colSpan: 4, section: 'Modullar',
        },
        {
          name: 'enable_tracking', label: 'Obyekt kuzatuvi (ByteTrack)', type: 'boolean',
          colSpan: 4, section: 'Modullar',
          helperText: 'Ikki telefonni ajratadi',
        },
        {
          name: 'gpu_profile_override', label: 'Apparat profili', type: 'select',
          options: GPU_PROFILE, colSpan: 4, section: 'Modullar',
          helperText: 'Avtomatik — client GPU’ni o‘zi aniqlaydi',
        },
        {
          name: 'identity_fps', label: 'Shaxs FPS', type: 'number', required: true,
          min: 0, max: 30, integer: true, colSpan: 3, section: 'Modullar',
          // Apparat ko'tara olmaydigan chastotani siyosat bilan
          // majburlab bo'lmaydi: client `min(siyosat, profil)` oladi.
          helperText: '0 — o‘chirilgan',
          hidden: (form) => !form.enable_identity,
        },
        {
          name: 'object_fps', label: 'Obyekt FPS', type: 'number', required: true,
          min: 0, max: 30, integer: true, colSpan: 3, section: 'Modullar',
          hidden: (form) => !form.enable_objects,
        },
        {
          name: 'pose_fps', label: 'Poza FPS', type: 'number', required: true,
          min: 0, max: 30, integer: true, colSpan: 3, section: 'Modullar',
          hidden: (form) => !form.enable_pose,
        },
        {
          name: 'gaze_fps', label: 'Nigoh FPS', type: 'number', required: true,
          min: 0, max: 30, integer: true, colSpan: 3, section: 'Modullar',
          hidden: (form) => !form.enable_gaze,
        },

        // --- Tasdiqlash ---
        {
          name: 'no_face_warn_s', label: 'Yuz yo‘q — ogohlantirish (s)', type: 'number',
          required: true, min: 1, max: 120, integer: true, colSpan: 3, section: 'Tasdiqlash',
        },
        {
          name: 'no_face_suspicious_s', label: 'Yuz yo‘q — shubha (s)', type: 'number',
          required: true, min: 1, max: 300, integer: true, colSpan: 3, section: 'Tasdiqlash',
        },
        {
          name: 'gaze_away_warn_s', label: 'Nigoh chetda — ogohlantirish (s)', type: 'number',
          required: true, min: 1, max: 120, integer: true, colSpan: 3, section: 'Tasdiqlash',
        },
        {
          name: 'gaze_away_suspicious_s', label: 'Nigoh chetda — shubha (s)', type: 'number',
          required: true, min: 1, max: 300, integer: true, colSpan: 3, section: 'Tasdiqlash',
        },
        {
          name: 'object_min_frames', label: 'Obyekt: min kadr', type: 'number', required: true,
          min: 1, max: 60, integer: true, colSpan: 4, section: 'Tasdiqlash',
          // Uchala shart ham bajarilishi kerak: yuqori FPS da 5 kadr
          // 0.2 s (juda qisqa), CPU rejimida esa 5 kadr 2 s (yetarli).
          helperText: 'Kadr, davomiylik va ishonch — UCHALASI ham kerak',
        },
        {
          name: 'object_min_duration_ms', label: 'Obyekt: min davomiylik (ms)', type: 'number',
          required: true, min: 100, max: 30000, integer: true, colSpan: 4, section: 'Tasdiqlash',
        },
        {
          name: 'object_min_conf', label: 'Obyekt: min ishonch', type: 'number', required: true,
          min: 0.1, max: 1, step: 0.01, colSpan: 4, section: 'Tasdiqlash',
          helperText: '0–1 oralig‘ida (0.80 — tavsiya etilgan)',
        },
        {
          name: 'fusion_window_ms', label: 'Birlashtirish oynasi (ms)', type: 'number',
          required: true, min: 500, max: 30000, integer: true, colSpan: 12, section: 'Tasdiqlash',
          helperText:
            'Shu oyna ichidagi hodisalar «yuqori shubha» xulosasiga birlashadi. ' +
            'Tarkibiy hodisalar O‘CHIRILMAYDI — ular apellyatsiyada asos bo‘ladi.',
        },

        // --- Xavf balli ---
        {
          name: 'risk_decay_per_min', label: 'Ball pasayishi (daqiqasiga)', type: 'number',
          required: true, min: 0, max: 100, integer: true, colSpan: 6, section: 'Xavf balli',
          helperText: '0 — pasaymaydi; uzoq imtihonda hamma «yuqori xavf» bo‘lib qoladi',
        },
        {
          name: 'risk_event_cooldown_s', label: 'Takror oralig‘i (s)', type: 'number',
          required: true, min: 0, max: 3600, integer: true, colSpan: 6, section: 'Xavf balli',
          // Kamera burchagi noto'g'ri bo'lsa yuz vaqti-vaqti bilan
          // yo'qoladi va cooldown'siz TEXNIK nosozlik talabgorning
          // aybiga aylanardi.
          helperText: 'Shu oyna ichidagi bir xil hodisa ballga ikkinchi marta qo‘shilmaydi',
        },
        {
          name: 'threshold_low', label: 'Past chegara', type: 'number', required: true,
          min: 1, max: 99, integer: true, colSpan: 4, section: 'Xavf balli',
        },
        {
          name: 'threshold_medium', label: 'O‘rta chegara', type: 'number', required: true,
          min: 1, max: 99, integer: true, colSpan: 4, section: 'Xavf balli',
        },
        {
          name: 'threshold_high', label: 'Yuqori chegara', type: 'number', required: true,
          min: 1, max: 100, integer: true, colSpan: 4, section: 'Xavf balli',
          helperText: 'Past < o‘rta < yuqori bo‘lishi shart',
        },

        // --- Dalil ---
        {
          name: 'evidence_enabled', label: 'Dalil to‘plash', type: 'boolean',
          colSpan: 4, section: 'Dalil',
        },
        {
          name: 'evidence_clip_seconds', label: 'Klip uzunligi (s)', type: 'number',
          required: true, min: 1, max: 30, integer: true, colSpan: 4, section: 'Dalil',
          hidden: (form) => !form.evidence_enabled,
          helperText: 'Hodisadan OLDINGI lahzalar ham kiradi',
        },
        {
          name: 'evidence_min_severity', label: 'Min jiddiylik', type: 'select',
          options: SEVERITY, colSpan: 4, section: 'Dalil',
          hidden: (form) => !form.evidence_enabled,
          helperText: 'Har bir kichik hodisa uchun klip yozish diskni to‘ldiradi',
        },
        {
          name: 'evidence_clip_retention_days', label: 'Klip saqlash (kun)', type: 'number',
          required: true, min: 1, max: 3650, integer: true, colSpan: 6, section: 'Dalil',
          hidden: (form) => !form.evidence_enabled,
          // Klip kadrdan ~10 barobar katta: 500 mashinali bino kuniga
          // ~5 GB yig'adi.
          helperText: 'Klip kadrdan ~10 barobar katta — muddati ham qisqaroq',
        },
        {
          name: 'evidence_frame_retention_days', label: 'Kadr saqlash (kun)', type: 'number',
          required: true, min: 1, max: 3650, integer: true, colSpan: 6, section: 'Dalil',
          hidden: (form) => !form.evidence_enabled,
        },
      ]}
    />
  )
}
