import { useEffect, useState } from 'react'
import {
  Box, ButtonBase, Card, CardContent, Chip, CircularProgress, Dialog, IconButton,
  Stack, Tooltip, Typography, useMediaQuery,
} from '@mui/material'
import { alpha, useTheme } from '@mui/material/styles'
import ImageIcon from '@mui/icons-material/ImageOutlined'
import MovieIcon from '@mui/icons-material/MovieOutlined'
import CloseIcon from '@mui/icons-material/CloseRounded'
import VisibilityIcon from '@mui/icons-material/VisibilityOutlined'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOffOutlined'

import { evidenceFile } from '../../api/endpoints'
import { EVENT_LABEL, formatBytes, formatDateTime, formatTime } from '../../utils/labels'

/**
 * Belgi turi -> rang va ma'no. Turlar client'da yasaladi
 * (`behavior_analyzer._mark`) va server ularni shu to'rttasiga
 * cheklaydi (`client_serializers._MARK_KINDS`).
 *
 * `student` — talabgorning o'zi: u XAVF EMAS, KONTEKST ("qaysi biri
 * begona?" degan savolga ikkalasi yonma-yon javob beradi), shuning
 * uchun yashil va chiplar ro'yxatiga tushmaydi.
 */
const MARK_KIND = {
  object: { color: 'error', title: 'Taqiqlangan obyekt' },
  person: { color: 'warning', title: 'Begona odam' },
  face: { color: 'info', title: 'Yuz' },
  student: { color: 'success', title: 'Talabgor' },
}

/**
 * Faqat YANGI formatdagi belgilar: nisbiy ramka (`box`, 0..1).
 *
 * Eski yozuvlarda piksel `bbox` bor va u detektor kadrida (masalan
 * 2688x1520) edi, dalil kadri esa 640 px — ularni chizish ramkani
 * rasmdan tashqariga qo'yardi. Noto'g'ri joydagi ramka ramkasizlikdan
 * yomonroq: u proktorni boshqa narsaga qaratadi.
 */
function marksOf(item) {
  return (item?.boxes || []).filter(
    (mark) => Array.isArray(mark?.box) && mark.box.length === 4,
  )
}

function markText(mark) {
  const conf = typeof mark.conf === 'number' && mark.kind !== 'student'
    ? ` ${Math.round(mark.conf * 100)}%`
    : ''
  return `${mark.label || MARK_KIND[mark.kind]?.title || ''}${conf}`
}

/**
 * Sarlavha: hodisa turi + TOPILGAN NARSA ("Taqiqlangan obyekt · Telefon").
 *
 * Nom belgilardan olinadi — aynan shu kadrda nima ko'ringan. Bir xil
 * nom takrorlanmaydi (ikkita telefon — bitta "Telefon").
 */
export function evidenceTitle(item) {
  const base = EVENT_LABEL[item.event_type] || item.event_type || '—'
  if (item.event_type !== 'object_detected') return base
  const names = [...new Set(
    marksOf(item).filter((mark) => mark.kind === 'object' && mark.label).map((mark) => mark.label),
  )]
  return names.length ? `${base} · ${names.join(', ')}` : base
}

/**
 * Rasm ustidagi belgilar qatlami.
 *
 * SVG `viewBox` kadr o'lchamida va `preserveAspectRatio="xMidYMid meet"`
 * — bu `<img objectFit: contain>` bilan AYNAN bir xil joylashuv. Ya'ni
 * ramka har qanday karta yoki oyna o'lchamida rasmga yopishib turadi,
 * rasmning chizilgan maydonini JS'da hisoblash shart emas.
 *
 * Chiziq va yozuv o'lchami ham kadr kengligiga nisbatan: 640 px kadr
 * kichik kartada ham, katta oynada ham bir xil ko'rinadi.
 */
function MarksOverlay({ marks, width, height }) {
  const theme = useTheme()
  if (!marks.length || !width || !height) return null

  const stroke = Math.max(2, width * 0.0045)
  const font = Math.max(11, width * 0.028)
  const pad = font * 0.35

  return (
    <Box
      component="svg"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
      sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
    >
      {marks.map((mark, index) => {
        const [x1, y1, x2, y2] = mark.box
        const color = theme.palette[MARK_KIND[mark.kind]?.color || 'error'].main
        const x = x1 * width
        const y = y1 * height
        const w = (x2 - x1) * width
        const h = (y2 - y1) * height
        const text = markText(mark)
        // Yozuv kengligi taxminiy (SVG'da o'lchashsiz): sans-serif'da
        // belgi ~0.58 em. Aniq o'lchov faqat kichik ortiqcha fon beradi.
        const labelW = text.length * font * 0.58 + pad * 2
        const labelH = font + pad * 1.4
        // Yozuv ramka USTIDA; joy bo'lmasa (kadr tepasi) — ichida.
        const labelY = y - labelH >= 0 ? y - labelH : y
        const labelX = Math.min(Math.max(0, x - stroke / 2), width - labelW)
        return (
          <g key={index}>
            <rect
              x={x} y={y} width={w} height={h}
              fill={alpha(color, 0.08)} stroke={color} strokeWidth={stroke} rx={stroke}
            />
            {text && (
              <>
                <rect x={labelX} y={labelY} width={labelW} height={labelH} fill={color} rx={stroke} />
                <text
                  x={labelX + pad} y={labelY + labelH - pad * 1.05}
                  fill={theme.palette.getContrastText(color)}
                  fontSize={font} fontWeight={600}
                  fontFamily={theme.typography.fontFamily}
                >
                  {text}
                </text>
              </>
            )}
          </g>
        )
      })}
    </Box>
  )
}

/** Topilgan narsalar — kontekst (`student`) ro'yxatga tushmaydi. */
function MarkChips({ marks, size = 'small', sx }) {
  const items = marks.filter((mark) => mark.kind !== 'student')
  if (!items.length) return null
  return (
    <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={sx}>
      {items.map((mark, index) => (
        <Chip
          key={index}
          size={size}
          color={MARK_KIND[mark.kind]?.color || 'error'}
          variant="outlined"
          label={markText(mark)}
        />
      ))}
    </Stack>
  )
}

/**
 * Bitta dalil: kadr yoki qisqa klip.
 *
 * Fayl SO'RALGANDA yuklanadi va komponent yopilganda blob DARHOL
 * bo'shatiladi. Usiz o'nlab klipni ko'rgan proktorning brauzeri
 * yuzlab megabaytni ushlab qolardi — `URL.createObjectURL` ni
 * brauzer o'zi tozalamaydi.
 *
 * Kadr TOZA saqlanadi, belgilar faqat shu yerda, rasm USTIDA
 * chiziladi va ularni yashirish mumkin: apellyatsiyada dalil —
 * asl kadr, belgi esa tizimning talqini.
 */
export default function EvidenceCard({ item }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [showMarks, setShowMarks] = useState(true)
  const [natural, setNatural] = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let objectUrl = ''
    let cancelled = false

    evidenceFile
      .objectUrl(item.id)
      .then((value) => {
        objectUrl = value
        // Komponent allaqachon yopilgan bo'lsa blob'ni DARHOL
        // bo'shatamiz: `setUrl` bekor qilinadi, blob esa
        // bo'shatilmasdan qolib ketardi.
        if (cancelled) URL.revokeObjectURL(value)
        else setUrl(value)
      })
      .catch(() => {
        if (!cancelled) setError('Faylni ochib bo‘lmadi')
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [item.id])

  const isClip = item.kind === 'clip'
  const marks = isClip ? [] : marksOf(item)
  // O'lcham rasmning O'ZIDAN (yuklangach) — server qiymati zaxira.
  const width = natural?.width || item.width
  const height = natural?.height || item.height

  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <Box
        sx={{
          position: 'relative', bgcolor: 'action.hover',
          aspectRatio: '16 / 9', display: 'grid', placeItems: 'center', overflow: 'hidden',
        }}
      >
        {error && <Typography variant="caption" color="error">{error}</Typography>}
        {!error && !url && <CircularProgress size={22} />}
        {!error && url && isClip && (
          <video src={url} controls preload="metadata" style={{ width: '100%', height: '100%' }} />
        )}
        {!error && url && !isClip && (
          <ButtonBase
            onClick={() => setOpen(true)}
            aria-label="Dalilni kattalashtirib ko‘rish"
            sx={{ position: 'absolute', inset: 0 }}
          >
            <img
              src={url}
              alt={evidenceTitle(item)}
              onLoad={(event) => setNatural({
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              })}
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            />
            {showMarks && <MarksOverlay marks={marks} width={width} height={height} />}
          </ButtonBase>
        )}
        {url && marks.length > 0 && (
          <Tooltip title={showMarks ? 'Belgilarni yashirish (asl kadr)' : 'Belgilarni ko‘rsatish'}>
            <IconButton
              size="small"
              aria-label={showMarks ? 'Belgilarni yashirish' : 'Belgilarni ko‘rsatish'}
              onClick={() => setShowMarks((value) => !value)}
              sx={{
                position: 'absolute', top: 6, right: 6, color: 'common.white',
                bgcolor: alpha('#000000', 0.45), backdropFilter: 'blur(4px)',
                '&:hover': { bgcolor: alpha('#000000', 0.65) },
              }}
            >
              {showMarks ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        )}
      </Box>
      <CardContent sx={{ py: 1.5 }}>
        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.5, minWidth: 0 }}>
          <Chip
            size="small"
            icon={isClip ? <MovieIcon /> : <ImageIcon />}
            variant="outlined"
            color={isClip ? 'secondary' : 'default'}
            label={item.kind_display || item.kind}
          />
          <Tooltip title={evidenceTitle(item)}>
            <Typography variant="body2" fontWeight={600} noWrap>
              {evidenceTitle(item)}
            </Typography>
          </Tooltip>
        </Stack>
        <MarkChips marks={marks} sx={{ mb: 0.75 }} />
        <Typography variant="caption" color="text.secondary" display="block">
          {formatTime(item.captured_at)}
          {/* Kamera roli ko'rsatiladi: "telefon stolda" xulosasi
              yuz kamerasidan kelgan bo'lsa, u shubhali. */}
          {item.camera_role && ` • ${item.camera_role === 'primary' ? 'asosiy' : 'ikkinchi'} kamera`}
          {item.confidence > 0 && ` • ishonch ${item.confidence}%`}
          {item.duration_ms > 0 && ` • ${Math.round(item.duration_ms / 1000)} s`}
        </Typography>
        <Typography variant="caption" color="text.disabled" display="block">
          {formatBytes(item.size_bytes)}
          {item.width > 0 && ` • ${item.width}×${item.height}`}
        </Typography>
      </CardContent>

      {open && (
        <EvidenceViewer
          item={item}
          url={url}
          marks={marks}
          width={width}
          height={height}
          showMarks={showMarks}
          onToggleMarks={() => setShowMarks((value) => !value)}
          onClose={() => setOpen(false)}
        />
      )}
    </Card>
  )
}

/**
 * Kattalashtirilgan dalil — skrinshot ko'rish oynasi bilan bir xil
 * "media viewer" (mavzudan qat'i nazar qorong'i): kadr ichidagi ranglar
 * va belgi ranglari oq fonda boshqacha o'qilardi.
 */
function EvidenceViewer({ item, url, marks, width, height, showMarks, onToggleMarks, onClose }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('md'))
  const surface = '#121316'
  const onSurface = alpha('#ffffff', 0.92)
  const toolbarButton = { color: onSurface, '&:hover': { bgcolor: alpha('#ffffff', 0.08) } }

  return (
    <Dialog
      open
      onClose={onClose}
      fullScreen={fullScreen}
      maxWidth={false}
      aria-label="Dalilni ko‘rish"
      PaperProps={{
        sx: {
          bgcolor: surface, color: onSurface, backgroundImage: 'none',
          borderRadius: fullScreen ? 0 : '28px',
          width: fullScreen ? '100%' : 'min(1280px, 94vw)',
          height: fullScreen ? '100%' : '88vh',
          overflow: 'hidden', display: 'flex', flexDirection: 'column',
        },
      }}
      slotProps={{ backdrop: { sx: { bgcolor: alpha('#000000', 0.72) } } }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2.5, py: 1.5 }}>
        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Typography variant="subtitle1" fontWeight={600} noWrap>
            {evidenceTitle(item)}
          </Typography>
          <Typography variant="caption" sx={{ color: alpha('#ffffff', 0.64) }}>
            {[
              formatDateTime(item.captured_at),
              item.camera_role && `${item.camera_role === 'primary' ? 'asosiy' : 'ikkinchi'} kamera`,
              width ? `${width}×${height}` : null,
            ].filter(Boolean).join(' · ')}
          </Typography>
        </Box>
        {marks.length > 0 && (
          <Tooltip title={showMarks ? 'Belgilarni yashirish (asl kadr)' : 'Belgilarni ko‘rsatish'}>
            <IconButton
              onClick={onToggleMarks}
              aria-label={showMarks ? 'Belgilarni yashirish' : 'Belgilarni ko‘rsatish'}
              sx={toolbarButton}
            >
              {showMarks ? <VisibilityOffIcon /> : <VisibilityIcon />}
            </IconButton>
          </Tooltip>
        )}
        <Tooltip title="Yopish (Esc)">
          <IconButton onClick={onClose} aria-label="Yopish" sx={toolbarButton}>
            <CloseIcon />
          </IconButton>
        </Tooltip>
      </Stack>

      <Box sx={{ position: 'relative', flexGrow: 1, minHeight: 0, mx: 2 }}>
        <img
          src={url}
          alt={evidenceTitle(item)}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }}
        />
        {showMarks && <MarksOverlay marks={marks} width={width} height={height} />}
      </Box>

      <Box sx={{ px: 2.5, py: 1.5, minHeight: 48 }}>
        <MarkChips marks={marks} size="medium" />
      </Box>
    </Dialog>
  )
}
