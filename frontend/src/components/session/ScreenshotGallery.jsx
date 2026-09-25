import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Box, ButtonBase, CircularProgress, Dialog, IconButton, Stack, Tooltip, Typography,
  useMediaQuery,
} from '@mui/material'
import { alpha, useTheme } from '@mui/material/styles'
import CloseIcon from '@mui/icons-material/Close'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import DownloadIcon from '@mui/icons-material/FileDownloadOutlined'
import ZoomInIcon from '@mui/icons-material/ZoomInOutlined'
import ZoomOutIcon from '@mui/icons-material/ZoomOutOutlined'
import BrokenImageIcon from '@mui/icons-material/BrokenImageOutlined'

import { screenshotFile } from '../../api/endpoints'
import { formatBytes, formatDateTime, formatTime } from '../../utils/labels'

const FAILED = 'failed'

/**
 * Har bir skrinshotning ko'rsatiladigan URL'i - BITTA JOYDA.
 *
 * Galereya kartasi ham, ko'rish oynasi ham, pastdagi lenta ham bir xil
 * rasmni ko'rsatadi. Har biri o'zi yuklasa, bitta rasm uch marta
 * so'ralardi va har so'rov serverda fayl berish yo'lidan o'tadi.
 *
 * Obyekt storage'dagisi tayyor presigned URL bilan keladi. Fayl
 * tizimidagisi esa blob sifatida olinadi: brauzer `<img>` so'roviga
 * `Authorization` qo'shmaydi, tokenni URL'ga qo'yish esa uni tarixga
 * va nginx log'iga chiqaradi (`api/endpoints.js:screenshotFile`).
 *
 * Blob'lar komponent yopilganda BO'SHATILADI - aks holda galereyani
 * bir necha marta ochgan proktorning brauzeri o'nlab megabaytni
 * ushlab qolardi.
 */
function useShotUrls(shots) {
  const [urls, setUrls] = useState({})

  useEffect(() => {
    let cancelled = false
    const created = []
    const initial = {}
    shots.forEach((shot) => {
      if (shot.source === 'object' && shot.url) initial[shot.key] = shot.url
    })
    setUrls(initial)

    shots
      .filter((shot) => shot.source === 'file')
      .forEach((shot) => {
        screenshotFile
          .objectUrl(shot.id)
          .then((url) => {
            if (cancelled) {
              URL.revokeObjectURL(url)
              return
            }
            created.push(url)
            setUrls((prev) => ({ ...prev, [shot.key]: url }))
          })
          .catch(() => {
            if (!cancelled) setUrls((prev) => ({ ...prev, [shot.key]: FAILED }))
          })
      })

    return () => {
      cancelled = true
      created.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [shots])

  return urls
}

/** Ikki manba ikki xil maydon nomi beradi (`size_bytes` / `file_size`). */
const shotSize = (shot) => shot.size_bytes ?? shot.file_size

/** Yuklab olinadigan fayl nomi - vaqt bo'yicha, tartiblanadigan. */
const downloadName = (shot) => {
  const stamp = String(shot.captured_at || '').replace(/[^0-9]/g, '').slice(0, 14)
  return `skrinshot_${stamp || shot.id}.jpg`
}

/**
 * Sessiya skrinshotlari: to'r (grid) + to'liq ekranli ko'rish oynasi.
 *
 * `shots` - `SessionDetail` birlashtirgan ro'yxat (obyekt storage +
 * fayl tizimi), vaqt bo'yicha kamayish tartibida.
 */
export default function ScreenshotGallery({ shots }) {
  const items = useMemo(
    () => (shots || []).map((shot) => ({ ...shot, key: `${shot.source}-${shot.id}` })),
    [shots],
  )
  const urls = useShotUrls(items)
  const [index, setIndex] = useState(null)

  return (
    <>
      <Box
        sx={{
          display: 'grid',
          gap: 1.5,
          // Qat'iy ustun soni EMAS: keng monitorda kartalar juda
          // katta, tor ekranda esa o'qib bo'lmas darajada kichik
          // bo'lardi.
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
        }}
      >
        {items.map((shot, position) => (
          <ShotTile
            key={shot.key}
            shot={shot}
            url={urls[shot.key]}
            onOpen={() => setIndex(position)}
          />
        ))}
      </Box>

      <ScreenshotViewer
        items={items}
        urls={urls}
        index={index}
        onIndex={setIndex}
        onClose={() => setIndex(null)}
      />
    </>
  )
}

function ShotImage({ url, alt, fit = 'cover', onLoad, style }) {
  if (url === FAILED) {
    return (
      <Stack alignItems="center" justifyContent="center" spacing={0.5} sx={{ height: '100%', color: 'text.disabled' }}>
        <BrokenImageIcon />
        <Typography variant="caption">Faylni ochib bo‘lmadi</Typography>
      </Stack>
    )
  }
  if (!url) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ height: '100%' }}>
        <CircularProgress size={22} />
      </Stack>
    )
  }
  return (
    <img
      src={url}
      alt={alt}
      loading="lazy"
      onLoad={onLoad}
      style={{ width: '100%', height: '100%', objectFit: fit, display: 'block', ...style }}
    />
  )
}

/**
 * Galereya kartasi. Butun karta TUGMA (`ButtonBase`): sichqoncha bilan
 * ham, klaviatura bilan ham (Tab + Enter) ochiladi va fokus halqasi
 * ko'rinadi - proktor ko'pincha klaviatura bilan ishlaydi.
 */
function ShotTile({ shot, url, onOpen }) {
  const size = shotSize(shot)
  return (
    <ButtonBase
      onClick={onOpen}
      focusRipple
      aria-label={`Skrinshot ${formatTime(shot.captured_at)} — kattalashtirish`}
      sx={(theme) => ({
        display: 'block',
        textAlign: 'left',
        borderRadius: 1,
        overflow: 'hidden',
        border: `1px solid ${theme.palette.divider}`,
        bgcolor: 'background.paper',
        transition: theme.transitions.create(['box-shadow', 'border-color']),
        '&:hover': { boxShadow: theme.shadows[4], borderColor: 'transparent' },
        '&:hover .shot-zoom, &.Mui-focusVisible .shot-zoom': { opacity: 1 },
        '&.Mui-focusVisible': {
          outline: `2px solid ${theme.palette.primary.main}`,
          outlineOffset: 2,
        },
      })}
    >
      <Box sx={{ position: 'relative', aspectRatio: '16 / 10', bgcolor: 'action.hover' }}>
        {/* `contain`, `cover` EMAS: ikki monitorli skrinshot juda keng
            va kesilsa, ekranning bir qismi kartada umuman ko'rinmasdi -
            dalilda "yashirin" qism bo'lmasligi kerak. */}
        <ShotImage url={url} fit="contain" alt={`Skrinshot ${formatTime(shot.captured_at)}`} />
        <Box
          className="shot-zoom"
          sx={(theme) => ({
            position: 'absolute',
            inset: 0,
            display: 'grid',
            placeItems: 'center',
            opacity: 0,
            transition: theme.transitions.create('opacity'),
            bgcolor: alpha(theme.palette.common.black, 0.28),
            color: 'common.white',
          })}
        >
          <ZoomInIcon fontSize="large" />
        </Box>
      </Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 1.5, py: 1 }}>
        <Typography variant="body2" fontWeight={600}>
          {formatTime(shot.captured_at)}
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        {size ? (
          <Typography variant="caption" color="text.secondary">{formatBytes(size)}</Typography>
        ) : null}
      </Stack>
    </ButtonBase>
  )
}

/**
 * To'liq ekranli ko'rish oynasi.
 *
 * QORONG'I YUZA mavzudan qat'i nazar: rasm ko'rish - "immersiv"
 * rejim (Material Design media viewer). Yorug' fonda skrinshotning
 * oq sahifasi atrofi bilan qo'shilib ketib, rasm chegarasi
 * ko'rinmasdi.
 *
 * Klaviatura: ← → (oldingi/keyingi), Home/End, Esc (yopish),
 * "+" / "-" (kattalashtirish). Proktor o'nlab skrinshotni ketma-ket
 * ko'radi va har biri uchun sichqonchani tugmaga olib borish
 * charchatadi.
 */
function ScreenshotViewer({ items, urls, index, onIndex, onClose }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('md'))
  const [zoomed, setZoomed] = useState(false)
  const [natural, setNatural] = useState(null)
  const stripRef = useRef(null)

  const open = index != null && index >= 0 && index < items.length
  const shot = open ? items[index] : null
  const url = shot ? urls[shot.key] : null
  const count = items.length

  // Rasm almashganda holat NOLGA qaytadi: kattalashtirilgan holat
  // keyingi rasmga o'tib, uning chetini ko'rsatib qolmasligi kerak.
  useEffect(() => {
    setZoomed(false)
    setNatural(null)
  }, [index])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'ArrowLeft' && index > 0) onIndex(index - 1)
      else if (event.key === 'ArrowRight' && index < count - 1) onIndex(index + 1)
      else if (event.key === 'Home') onIndex(0)
      else if (event.key === 'End') onIndex(count - 1)
      else if (event.key === '+' || event.key === '=') setZoomed(true)
      else if (event.key === '-') setZoomed(false)
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, index, count, onIndex])

  // Tanlangan kichik rasm lentada har doim KO'RINADI.
  useEffect(() => {
    if (!open || !stripRef.current) return
    const node = stripRef.current.querySelector(`[data-index="${index}"]`)
    node?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' })
  }, [open, index])

  if (!open) return null

  const size = shotSize(shot)
  const details = [
    `${index + 1} / ${count}`,
    natural ? `${natural.width}×${natural.height}` : null,
    size ? formatBytes(size) : null,
  ].filter(Boolean).join(' · ')

  const surface = '#121316'
  const onSurface = alpha('#ffffff', 0.92)
  const navButton = {
    position: 'absolute',
    top: '50%',
    transform: 'translateY(-50%)',
    color: 'common.white',
    bgcolor: alpha('#000000', 0.45),
    backdropFilter: 'blur(4px)',
    '&:hover': { bgcolor: alpha('#000000', 0.65) },
    '&.Mui-disabled': { color: alpha('#ffffff', 0.25), bgcolor: alpha('#000000', 0.2) },
  }
  const toolbarButton = { color: onSurface, '&:hover': { bgcolor: alpha('#ffffff', 0.08) } }

  return (
    <Dialog
      open
      onClose={onClose}
      fullScreen={fullScreen}
      maxWidth={false}
      aria-label="Skrinshotni ko‘rish"
      PaperProps={{
        sx: {
          bgcolor: surface,
          color: onSurface,
          backgroundImage: 'none',
          // MD3 "extra-large" shakl - modal yuza uchun.
          borderRadius: fullScreen ? 0 : '28px',
          width: fullScreen ? '100%' : 'min(1480px, 94vw)',
          height: fullScreen ? '100%' : '92vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
      slotProps={{ backdrop: { sx: { bgcolor: alpha('#000000', 0.72) } } }}
    >
      {/* Yuqori panel: vaqt, tartib, o'lcham + amallar */}
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2.5, py: 1.5 }}>
        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Typography variant="subtitle1" fontWeight={600} noWrap>
            {formatDateTime(shot.captured_at)}
          </Typography>
          <Typography variant="caption" sx={{ color: alpha('#ffffff', 0.64) }}>
            {details}
          </Typography>
        </Box>
        <Tooltip title={zoomed ? 'Ekranga moslash (−)' : 'Kattalashtirish 2× (+)'}>
          <span>
            <IconButton sx={toolbarButton} onClick={() => setZoomed((value) => !value)} disabled={!url || url === FAILED}>
              {zoomed ? <ZoomOutIcon /> : <ZoomInIcon />}
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Yuklab olish">
          <span>
            <IconButton
              sx={toolbarButton}
              component="a"
              href={url && url !== FAILED ? url : undefined}
              download={downloadName(shot)}
              disabled={!url || url === FAILED}
            >
              <DownloadIcon />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Yopish (Esc)">
          <IconButton sx={toolbarButton} onClick={onClose} aria-label="Yopish">
            <CloseIcon />
          </IconButton>
        </Tooltip>
      </Stack>

      {/* Asosiy maydon */}
      <Box
        sx={{
          position: 'relative',
          flexGrow: 1,
          minHeight: 0,
          mx: { xs: 0, md: 2 },
          borderRadius: { xs: 0, md: 2 },
          bgcolor: alpha('#000000', 0.35),
          overflow: zoomed ? 'auto' : 'hidden',
          display: zoomed ? 'block' : 'grid',
          placeItems: 'center',
        }}
      >
        {url && url !== FAILED ? (
          <img
            src={url}
            alt={`Skrinshot ${formatDateTime(shot.captured_at)}`}
            onLoad={(event) =>
              setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
            }
            onClick={() => setZoomed((value) => !value)}
            // ODDIY REJIM MAYDONNI TO'LDIRADI (kichik rasm ham
            // kattalashadi): server skrinshotni ~960 px gacha
            // kichraytiradi va "asl o'lcham" oynaning uchdan birini
            // egallab, matnni o'qib bo'lmas qilardi. KATTALASHTIRISH
            // esa 2× - kichik shriftdagi savol matnini o'qish uchun.
            style={
              zoomed
                ? {
                  display: 'block',
                  maxWidth: 'none',
                  width: natural ? natural.width * 2 : '200%',
                  cursor: 'zoom-out',
                  margin: '0 auto',
                }
                : { width: '100%', height: '100%', objectFit: 'contain', cursor: 'zoom-in' }
            }
          />
        ) : (
          <Box sx={{ width: 220, height: 140 }}>
            <ShotImage url={url} alt="" />
          </Box>
        )}

        <IconButton
          aria-label="Oldingi"
          size="large"
          sx={{ ...navButton, left: 12 }}
          disabled={index === 0}
          onClick={() => onIndex(index - 1)}
        >
          <ChevronLeftIcon fontSize="large" />
        </IconButton>
        <IconButton
          aria-label="Keyingi"
          size="large"
          sx={{ ...navButton, right: 12 }}
          disabled={index >= count - 1}
          onClick={() => onIndex(index + 1)}
        >
          <ChevronRightIcon fontSize="large" />
        </IconButton>
      </Box>

      {/* Kichik rasmlar lentasi */}
      {count > 1 && (
        <Stack
          ref={stripRef}
          direction="row"
          spacing={1}
          sx={{
            px: 2.5,
            py: 1.5,
            overflowX: 'auto',
            flexShrink: 0,
            scrollbarWidth: 'thin',
          }}
        >
          {items.map((item, position) => {
            const active = position === index
            return (
              <ButtonBase
                key={item.key}
                data-index={position}
                onClick={() => onIndex(position)}
                aria-label={`Skrinshot ${formatTime(item.captured_at)}`}
                aria-current={active ? 'true' : undefined}
                sx={{
                  flexShrink: 0,
                  width: 96,
                  height: 60,
                  borderRadius: 1,
                  overflow: 'hidden',
                  outline: active ? `2px solid ${theme.palette.primary.light}` : '2px solid transparent',
                  outlineOffset: 2,
                  opacity: active ? 1 : 0.55,
                  transition: theme.transitions.create(['opacity', 'outline-color']),
                  '&:hover': { opacity: 1 },
                  bgcolor: alpha('#ffffff', 0.06),
                }}
              >
                <ShotImage url={urls[item.key]} alt="" />
              </ButtonBase>
            )
          })}
        </Stack>
      )}
    </Dialog>
  )
}
