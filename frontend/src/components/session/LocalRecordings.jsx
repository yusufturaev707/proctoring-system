import { useState } from 'react'
import {
  Avatar, Box, Chip, IconButton, Paper, Stack, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import ContentCopyIcon from '@mui/icons-material/ContentCopyOutlined'
import CheckIcon from '@mui/icons-material/Check'
import FolderIcon from '@mui/icons-material/FolderOutlined'
import DesktopIcon from '@mui/icons-material/DesktopWindowsOutlined'
import VideocamIcon from '@mui/icons-material/VideocamOutlined'
import ComputerIcon from '@mui/icons-material/ComputerOutlined'
import VideoOffIcon from '@mui/icons-material/VideocamOffOutlined'

import { EmptyState } from '../feedback/States'
import { TablePager } from '../data/DataTable'
import { computerLabel, EVENT_LABEL, formatDateTime } from '../../utils/labels'

const CAMERA_ROLE_LABEL = {
  primary: 'Yuz kamerasi',
  secondary: 'Xona kamerasi',
}

/**
 * Davomiylik - to'liq so'z bilan ("2 soat 58 daqiqa", "16 soniya").
 *
 * `utils/labels.js:formatDuration` bu yerda YARAMAYDI: u "1s 24d"
 * qisqartmasini beradi va 16 soniyalik klip uchun "16s" chiqaradi -
 * u yerda "s" SOAT degani, ya'ni "16 soat" deb o'qilardi.
 */
const formatLength = (ms) => {
  const total = Math.round((ms || 0) / 1000)
  if (!total) return ''
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours) return minutes ? `${hours} soat ${minutes} daqiqa` : `${hours} soat`
  if (minutes) return seconds ? `${minutes} daqiqa ${seconds} soniya` : `${minutes} daqiqa`
  return `${seconds} soniya`
}

/** Windows ham, POSIX ham: `D:\a\b\screen.mp4` -> `D:\a\b`. */
const dirname = (path) => {
  const value = String(path || '')
  const cut = Math.max(value.lastIndexOf('\\'), value.lastIndexOf('/'))
  return cut > 0 ? value.slice(0, cut) : ''
}

/**
 * Sessiya papkasi - barcha yozuvlarning UMUMIY katalogi.
 *
 * Client bitta imtihonning hamma dalilini bitta papkaga yozadi
 * (`<sana>/<sessiya>_<jshshir>_<mac>/`, `CLAUDE.md` "Mahalliy
 * arxiv"). Proktor mashinaga borganda aynan shu papkani ochadi -
 * alohida fayllarni bittalab qidirmaydi. Papkalar farq qilsa
 * (disk almashgan) umumiy papka ko'rsatilmaydi: noto'g'ri manzil
 * yo'q manzildan yomonroq.
 */
const sessionFolder = (recordings) => {
  const folders = [...new Set(recordings.map((item) => dirname(item.local_path)).filter(Boolean))]
  return folders.length === 1 ? folders[0] : ''
}

function useCopy() {
  const [copied, setCopied] = useState('')
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(text)
      setTimeout(() => setCopied(''), 2000)
    } catch {
      // Clipboard API HTTPS siz ishlamaydi (panel ichki tarmoqda
      // bo'lishi mumkin). Yo'lning o'zi ekranda va uni qo'lda
      // belgilab olish mumkin - shuning uchun u matn, rasm emas.
      setCopied('')
    }
  }
  return [copied, copy]
}

/**
 * Qurilmadagi yo'l - bo'limning ASOSIY ma'lumoti.
 *
 * Fayl panelda OCHILMAYDI va ochila olmaydi: u imtihon mashinasining
 * diskida. Brauzer `file://` ni xavfsizlik sababli ochmaydi, havola
 * qo'yish esa "bosdim, ochilmadi" degan savol tug'dirardi. Shuning
 * uchun yo'l monospace, to'liq (qisqartirilmagan) va nusxalanadigan.
 */
function PathField({ path, copied, onCopy, label = 'Qurilmadagi yo‘l' }) {
  const done = copied === path
  return (
    <Box
      sx={(theme) => ({
        mt: 1.25,
        pl: 1.5,
        pr: 0.5,
        py: 0.75,
        borderRadius: 1,
        bgcolor: alpha(theme.palette.text.primary, 0.05),
        display: 'flex',
        alignItems: 'center',
        gap: 1,
      })}
    >
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>
          {label}
        </Typography>
        <Typography
          variant="body2"
          sx={{ fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace', wordBreak: 'break-all' }}
        >
          {path}
        </Typography>
      </Box>
      <Tooltip title={done ? 'Nusxalandi' : 'Yo‘lni nusxalash'}>
        <IconButton size="small" onClick={() => onCopy(path)} aria-label="Yo‘lni nusxalash">
          {done ? <CheckIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
        </IconButton>
      </Tooltip>
    </Box>
  )
}

function RecordingItem({ item, copied, onCopy }) {
  const isScreen = item.kind === 'screen'
  const Icon = isScreen ? DesktopIcon : VideocamIcon
  const length = formatLength(item.duration_ms)
  const meta = [
    formatDateTime(item.captured_at),
    length,
    item.size_mb ? `${item.size_mb} MB` : '',
    item.width > 0 ? `${item.width}×${item.height}` : '',
  ].filter(Boolean)

  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5 }}>
      <Stack direction="row" spacing={1.5} alignItems="flex-start">
        <Avatar
          variant="rounded"
          sx={(theme) => ({
            width: 40,
            height: 40,
            borderRadius: 1,
            color: isScreen ? 'primary.main' : 'secondary.main',
            bgcolor: alpha(isScreen ? theme.palette.primary.main : theme.palette.secondary.main, 0.12),
          })}
        >
          <Icon fontSize="small" />
        </Avatar>

        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle2" fontWeight={700}>
              {isScreen ? 'Ekran yozuvi' : (EVENT_LABEL[item.event_type] || item.event_type || 'Kamera klipi')}
            </Typography>
            {!isScreen && item.camera_role && (
              <Chip size="small" variant="outlined" label={CAMERA_ROLE_LABEL[item.camera_role] || item.camera_role} />
            )}
            {!isScreen && item.confidence > 0 && (
              <Chip size="small" variant="outlined" label={`Ishonch ${item.confidence}%`} />
            )}
            {item.frames_dropped > 0 && (
              <Chip
                size="small"
                color="warning"
                variant="outlined"
                label={`${item.frames_dropped} kadr tushib qolgan`}
              />
            )}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            {meta.join(' · ')}
          </Typography>

          <PathField path={item.local_path} copied={copied} onCopy={onCopy} />
        </Box>
      </Stack>
    </Paper>
  )
}

function Group({ title, count, children }) {
  return (
    <Box>
      <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="overline" sx={{ fontWeight: 700, letterSpacing: 0.8, lineHeight: 2 }}>
          {title}
        </Typography>
        <Typography variant="caption" color="text.secondary">{count}</Typography>
      </Stack>
      <Stack spacing={1.25}>{children}</Stack>
    </Box>
  )
}

/**
 * «Mashinadagi yozuvlar» - ekran yozuvi va kamera kliplari.
 *
 * Ikkalasi ham FAQAT client qurilmasida yotadi va serverga faqat
 * manzili keladi (`LocalRecording`). Bo'lim shuning uchun "fayl
 * ko'rsatgich" emas, "qayerdan topaman?" degan savolga javob:
 * yuqorida mashina va sessiya papkasi, pastda har bir faylning
 * to'liq yo'li.
 *
 * Guruhlar ALOHIDA: ekran yozuvi imtihonga bitta, kliplar esa hodisa
 * sayin va ular o'nlab bo'lishi mumkin - aralash ro'yxatda yagona
 * ekran yozuvi kliplar orasida yo'qolib qolardi.
 */
export default function LocalRecordings({ session }) {
  const recordings = session?.local_recordings || []
  const [copied, copy] = useCopy()
  // Kliplar hodisa sayin va o'nlab-yuzlab bo'lishi mumkin — sahifalanadi
  // (standart 50, boshqa tab'lar bilan bir xil). Ma'lumot sessiya bilan
  // birga keladi, shuning uchun sahifalash BRAUZERDA: alohida so'rov
  // kerak emas, faqat bir vaqtda chiziladigan kartalar soni cheklanadi.
  const [clipPage, setClipPage] = useState({ page: 0, pageSize: 50 })

  if (!recordings.length) {
    return (
      <EmptyState
        icon={VideoOffIcon}
        title="Mashinadagi yozuv qayd etilmagan"
        description={
          'Ekran yozuvi imtihon yakunlanganda qayd etiladi. Kamera kliplari esa '
          + 'faqat AI kuzatuv yoqilgan imtihonda, tasdiqlangan hodisadan tug‘iladi. '
          + 'Fayllarning o‘zi imtihon mashinasida qoladi — bu yerda faqat ularning manzili ko‘rinadi.'
        }
      />
    )
  }

  const screens = recordings.filter((item) => item.kind === 'screen')
  const clips = recordings.filter((item) => item.kind !== 'screen')
  const folder = sessionFolder(recordings)
  const machine = computerLabel(session.computer_number, session.computer_code)
  const mac = recordings.find((item) => item.machine_mac)?.machine_mac

  return (
    <Stack spacing={2.5}>
      <Paper
        elevation={0}
        sx={(theme) => ({
          p: 2,
          borderRadius: 1.5,
          bgcolor: alpha(theme.palette.primary.main, 0.06),
          border: `1px solid ${alpha(theme.palette.primary.main, 0.16)}`,
        })}
      >
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          <Avatar
            variant="rounded"
            sx={(theme) => ({
              width: 40,
              height: 40,
              borderRadius: 1,
              color: 'primary.main',
              bgcolor: alpha(theme.palette.primary.main, 0.14),
            })}
          >
            <FolderIcon fontSize="small" />
          </Avatar>
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            <Typography variant="subtitle2" fontWeight={700}>
              Client qurilmasidagi sessiya papkasi
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
              {machine && <Chip size="small" icon={<ComputerIcon />} label={machine} />}
              {mac && <Chip size="small" variant="outlined" label={`MAC ${mac}`} />}
            </Stack>
            {folder && (
              <PathField path={folder} copied={copied} onCopy={copy} label="Papka" />
            )}
          </Box>
        </Stack>
      </Paper>

      {screens.length > 0 && (
        <Group title="Ekran yozuvi" count={screens.length}>
          {screens.map((item) => (
            <RecordingItem key={item.id} item={item} copied={copied} onCopy={copy} />
          ))}
        </Group>
      )}

      {clips.length > 0 && (
        <Group title="Kamera kliplari" count={clips.length}>
          {clips
            .slice(clipPage.page * clipPage.pageSize, (clipPage.page + 1) * clipPage.pageSize)
            .map((item) => (
              <RecordingItem key={item.id} item={item} copied={copied} onCopy={copy} />
            ))}
          {clips.length > 25 && (
            <Box sx={{ borderRadius: '12px', overflow: 'hidden', border: 1, borderColor: 'divider' }}>
              <TablePager
                rowCount={clips.length}
                rowsOnPage={Math.min(clipPage.pageSize, clips.length - clipPage.page * clipPage.pageSize)}
                paginationModel={clipPage}
                onPaginationModelChange={setClipPage}
              />
            </Box>
          )}
        </Group>
      )}
    </Stack>
  )
}
