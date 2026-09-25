import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box, Button, Chip, CircularProgress, Dialog, IconButton, Stack, Tooltip, Typography,
  useMediaQuery,
} from '@mui/material'
import { alpha, keyframes, useTheme } from '@mui/material/styles'
import CloseIcon from '@mui/icons-material/Close'
import PauseIcon from '@mui/icons-material/PauseRounded'
import PlayIcon from '@mui/icons-material/PlayArrowRounded'
import NetworkCheckIcon from '@mui/icons-material/NetworkCheckOutlined'
import VideocamOffIcon from '@mui/icons-material/VideocamOffOutlined'

import api, { tokens } from '../../api/client'
import { cameras as camerasApi } from '../../api/endpoints'
import { readMjpeg } from './mjpegStream'

/**
 * Shuncha vaqtdan keyin ko'rish O'ZI to'xtaydi.
 *
 * Serverda kamera oqimi ko'ruvchi bor paytda ochiq turadi va
 * kameraning cheklangan ulanishlaridan birini, gunicorn'ning esa
 * bitta thread'ini band qiladi. Ochiq qolib ketgan brauzer yorlig'i
 * ularni soatlab ushlab turmasligi kerak.
 */
const AUTO_STOP_MS = 5 * 60 * 1000
/** Yangi kadr shuncha vaqt kelmasa "oqim to'xtadi" deb ko'rsatiladi. */
const STALE_MS = 3000
/** Tarmoq uzilishida ketma-ket qayta ulanish urinishlari. */
const MAX_RETRIES = 3

const pulse = keyframes`
  0% { opacity: 1 } 50% { opacity: .35 } 100% { opacity: 1 }
`

const surface = '#0f1115'
const onSurface = alpha('#ffffff', 0.92)

const median = (values) => {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)]
}

/**
 * IP kamera tasviri - panelda JONLI ko'rish.
 *
 * OQIM, SO'ROVLAR EMAS. Ilgari panel har kadr uchun alohida so'rov
 * yuborardi (~4 kadr/s, har biri autentifikatsiya va DB'dan o'tardi) va
 * tasvir "qotib-qotib" ko'rinardi. Endi server bitta uzun javobda
 * kadrlarni yangi kelishi bilan yuboradi (MJPEG, ~10-12 kadr/s,
 * `cameras/{id}/live/`), panel esa ularni `fetch` bilan o'qiydi.
 *
 * FAQAT ENG YANGI KADR CHIZILADI. Kadr `createImageBitmap` bilan
 * (asosiy thread'dan tashqarida) dekodlanadi va canvas'ga chiziladi;
 * dekodlash band bo'lsa, oraliqdagi kadrlar tashlanadi - kechikish
 * brauzerda ham to'planmaydi. `<img>` ni har kadrda almashtirish esa
 * miltillash va xotira sizishini berardi.
 *
 * Statistika soniyada BIR MARTA yangilanadi: har kadrda React holatini
 * o'zgartirish butun oynani sekundiga 10 marta qayta chizardi.
 */
export default function CameraLiveDialog({ camera, open, onClose, onChecked }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('md'))
  const [phase, setPhase] = useState('connecting')   // connecting | live | paused | error
  const [error, setError] = useState('')
  const [stats, setStats] = useState({ fps: 0, serverMs: null, size: null, stale: false })
  const [hasFrame, setHasFrame] = useState(false)
  const [checking, setChecking] = useState(false)

  const canvasRef = useRef(null)
  const pendingRef = useRef(null)
  const decodingRef = useRef(false)
  const arrivalsRef = useRef([])
  const delaysRef = useRef([])
  const lastFrameAtRef = useRef(0)
  const sizeRef = useRef(null)
  const phaseRef = useRef(phase)
  phaseRef.current = phase

  const cameraId = camera?.id
  const halted = phase === 'paused' || phase === 'error'

  // Ochilganda / kamera almashganda holat NOLDAN.
  useEffect(() => {
    if (!open) return
    setPhase('connecting')
    setError('')
    setHasFrame(false)
    setStats({ fps: 0, serverMs: null, size: null, stale: false })
    arrivalsRef.current = []
    delaysRef.current = []
    lastFrameAtRef.current = 0
    sizeRef.current = null
  }, [open, cameraId])

  /** Eng yangi kadrni dekodlab chizadi; band bo'lsa faqat oxirgisini saqlaydi. */
  const pump = useCallback(async () => {
    if (decodingRef.current) return
    decodingRef.current = true
    try {
      while (pendingRef.current) {
        const frame = pendingRef.current
        pendingRef.current = null
        let bitmap
        try {
          bitmap = await createImageBitmap(new Blob([frame.jpeg], { type: 'image/jpeg' }))
        } catch {
          continue   // buzilgan kadr - keyingisini kutamiz
        }
        const canvas = canvasRef.current
        if (canvas) {
          if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
            canvas.width = bitmap.width
            canvas.height = bitmap.height
            sizeRef.current = { w: bitmap.width, h: bitmap.height }
          }
          canvas.getContext('2d').drawImage(bitmap, 0, 0)
        }
        bitmap.close()
      }
    } finally {
      decodingRef.current = false
    }
  }, [])

  const onFrame = useCallback((frame) => {
    const now = Date.now()
    lastFrameAtRef.current = now
    arrivalsRef.current.push(now)
    if (frame.takenAt && frame.sentAt) {
      delaysRef.current.push((frame.sentAt - frame.takenAt) * 1000)
      if (delaysRef.current.length > 30) delaysRef.current.shift()
    }
    pendingRef.current = frame
    pump()
    if (phaseRef.current !== 'live') {
      setPhase('live')
      setHasFrame(true)
    }
  }, [pump])

  // Oqim sikli: server javobni yopsa (60 s) - DARHOL qayta ulanadi.
  useEffect(() => {
    if (!open || !cameraId || halted) return undefined
    const controller = new AbortController()
    let stopped = false
    const stopTimer = setTimeout(() => {
      stopped = true
      controller.abort()
      setPhase('paused')
    }, AUTO_STOP_MS)

    const url = `${api.defaults.baseURL}/cameras/${cameraId}/live/`
    const run = async () => {
      let failures = 0
      let refreshed = false
      while (!stopped) {
        try {
          await readMjpeg(url, { token: tokens.access(), signal: controller.signal, onFrame })
          failures = 0   // javob navbatdagidek tugadi - qayta ulanamiz
        } catch (err) {
          if (stopped || controller.signal.aborted) return
          if (err.status === 401 && !refreshed) {
            // Token eskirgan: axios interceptor'i uni yangilaydi.
            refreshed = true
            try { await camerasApi.detail(cameraId) } catch { /* xabar pastda */ }
            continue
          }
          failures += 1
          // Server xatosi (4xx/5xx) - qayta urinishning ma'nosi yo'q;
          // tarmoq uzilishi (status yo'q) - bir necha marta urinib ko'ramiz.
          if (err.status || failures > MAX_RETRIES) {
            setError(err.message || 'Kamera tasvirini olib bo‘lmadi')
            setPhase('error')
            return
          }
          await new Promise((resolve) => setTimeout(resolve, 1000))
        }
      }
    }
    run()
    return () => {
      stopped = true
      clearTimeout(stopTimer)
      controller.abort()
    }
  }, [open, cameraId, halted, onFrame])

  // Statistika - soniyada bir marta.
  useEffect(() => {
    if (!open) return undefined
    const timer = setInterval(() => {
      const now = Date.now()
      arrivalsRef.current = arrivalsRef.current.filter((at) => now - at <= 2000)
      const arrivals = arrivalsRef.current
      const fps = arrivals.length > 1
        ? (arrivals.length - 1) / ((arrivals[arrivals.length - 1] - arrivals[0]) / 1000 || 1)
        : 0
      setStats({
        fps,
        serverMs: median(delaysRef.current),
        size: sizeRef.current,
        stale: Boolean(lastFrameAtRef.current) && now - lastFrameAtRef.current > STALE_MS,
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [open])

  const retry = () => {
    setError('')
    setPhase('connecting')
  }

  const runCheck = useCallback(async () => {
    if (!camera) return
    setChecking(true)
    try {
      const updated = await camerasApi.check(camera.id)
      onChecked?.(updated)
    } catch {
      // Xabar ro'yxatdagi holat ustunida ko'rinadi.
    } finally {
      setChecking(false)
    }
  }, [camera, onChecked])

  if (!camera) return null

  const stale = phase === 'live' && stats.stale
  const badge = {
    connecting: { label: 'Ulanmoqda…', color: alpha('#ffffff', 0.16) },
    live: stale
      ? { label: 'Oqim to‘xtadi', color: theme.palette.warning.main }
      : { label: 'JONLI', color: theme.palette.error.main, dot: true },
    paused: { label: 'To‘xtatildi', color: alpha('#ffffff', 0.16) },
    error: { label: 'Xatolik', color: theme.palette.error.dark },
  }[phase]

  const toolbarButton = { color: onSurface, '&:hover': { bgcolor: alpha('#ffffff', 0.08) } }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      maxWidth={false}
      PaperProps={{
        sx: {
          bgcolor: surface,
          color: onSurface,
          backgroundImage: 'none',
          borderRadius: fullScreen ? 0 : '28px',
          width: fullScreen ? '100%' : 'min(1180px, 94vw)',
          overflow: 'hidden',
        },
      }}
      slotProps={{ backdrop: { sx: { bgcolor: alpha('#000000', 0.72) } } }}
    >
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 3, py: 2 }}>
        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Typography variant="h6" fontWeight={600} noWrap>{camera.name}</Typography>
          <Typography variant="body2" sx={{ color: alpha('#ffffff', 0.64) }} noWrap>
            {[camera.zone_name, `${camera.ip_address}:${camera.port || 554}`, camera.rtsp_path].filter(Boolean).join(' · ')}
          </Typography>
        </Box>
        <Tooltip title="Holatni hozir tekshirish (RTSP)">
          <span>
            <IconButton sx={toolbarButton} onClick={runCheck} disabled={checking} aria-label="Holatni hozir tekshirish">
              {checking ? <CircularProgress size={20} sx={{ color: onSurface }} /> : <NetworkCheckIcon />}
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={phase === 'paused' ? 'Davom ettirish' : 'To‘xtatish'}>
          <span>
            <IconButton
              sx={toolbarButton}
              aria-label={phase === 'paused' ? 'Davom ettirish' : 'To‘xtatish'}
              disabled={phase === 'error' || phase === 'connecting'}
              onClick={() => setPhase(phase === 'paused' ? 'connecting' : 'paused')}
            >
              {phase === 'paused' ? <PlayIcon /> : <PauseIcon />}
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Yopish">
          <IconButton sx={toolbarButton} onClick={onClose} aria-label="Yopish">
            <CloseIcon />
          </IconButton>
        </Tooltip>
      </Stack>

      <Box
        sx={{
          position: 'relative',
          mx: { xs: 0, md: 3 },
          mb: 1.5,
          aspectRatio: '16 / 9',
          borderRadius: { xs: 0, md: 3 },
          overflow: 'hidden',
          bgcolor: '#000',
          display: 'grid',
          placeItems: 'center',
        }}
      >
        <canvas
          ref={canvasRef}
          aria-label={`${camera.name} — jonli tasvir`}
          style={{
            width: '100%', height: '100%', objectFit: 'contain',
            display: hasFrame && phase !== 'error' ? 'block' : 'none',
            filter: phase === 'paused' || stale ? 'grayscale(0.6) brightness(0.7)' : 'none',
            transition: 'filter 200ms',
          }}
        />

        {phase === 'connecting' && !hasFrame && (
          <Stack alignItems="center" spacing={1.5} sx={{ position: 'absolute' }}>
            <CircularProgress sx={{ color: onSurface }} />
            <Typography variant="body2" sx={{ color: alpha('#ffffff', 0.72) }}>
              Kameraga ulanilmoqda…
            </Typography>
          </Stack>
        )}

        {phase === 'error' && (
          <Stack alignItems="center" spacing={1.5} sx={{ position: 'absolute', px: 3, textAlign: 'center' }}>
            <VideocamOffIcon sx={{ fontSize: 48, color: alpha('#ffffff', 0.5) }} />
            <Typography variant="subtitle1" fontWeight={600}>Tasvir olinmadi</Typography>
            <Typography variant="body2" sx={{ color: alpha('#ffffff', 0.72), maxWidth: 520 }}>
              {error}
            </Typography>
            <Button variant="contained" onClick={retry} sx={{ borderRadius: 5, px: 3 }}>
              Qayta urinish
            </Button>
          </Stack>
        )}

        {phase === 'paused' && hasFrame && (
          <Button
            variant="contained"
            startIcon={<PlayIcon />}
            onClick={() => setPhase('connecting')}
            sx={{ position: 'absolute', borderRadius: 5, px: 3 }}
          >
            Ko‘rishni davom ettirish
          </Button>
        )}

        {/* Holat belgisi - chap yuqori */}
        <Chip
          size="small"
          label={badge.label}
          icon={badge.dot ? (
            <Box
              component="span"
              sx={{
                width: 8, height: 8, borderRadius: '50%', bgcolor: '#fff', ml: '8px !important',
                animation: `${pulse} 1.4s ease-in-out infinite`,
              }}
            />
          ) : undefined}
          sx={{
            position: 'absolute', top: 12, left: 12,
            bgcolor: badge.color, color: '#fff', fontWeight: 700, letterSpacing: 0.4,
            '& .MuiChip-icon': { color: '#fff' },
          }}
        />
      </Box>

      <Stack
        direction="row"
        spacing={2}
        alignItems="center"
        sx={{ px: 3, pb: 2.5, color: alpha('#ffffff', 0.64) }}
      >
        <Typography variant="caption">
          {phase === 'live' ? `${stats.fps.toFixed(1)} kadr/s` : '— kadr/s'}
        </Typography>
        <Tooltip title="Kadr serverga kelgandan panelga yuborilgunicha o‘tgan vaqt">
          <Typography variant="caption">
            {stats.serverMs != null ? `Server: ${Math.round(stats.serverMs)} ms` : 'Server: —'}
          </Typography>
        </Tooltip>
        <Typography variant="caption">{stats.size ? `${stats.size.w}×${stats.size.h}` : ''}</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="caption">
          Tasvir server orqali keladi · ko‘rish 5 daqiqadan keyin o‘zi to‘xtaydi
        </Typography>
      </Stack>
    </Dialog>
  )
}
