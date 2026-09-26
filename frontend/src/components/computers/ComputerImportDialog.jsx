import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, LinearProgress, Stack, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Typography, useMediaQuery,
} from '@mui/material'
import { alpha, useTheme } from '@mui/material/styles'
import CloseIcon from '@mui/icons-material/Close'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined'

import { computers as computersApi } from '../../api/endpoints'
import { useUi } from '../../context/UiContext'

const COLUMN_LABEL = {
  dtm_id: 'Viloyat (dtm_id)',
  zone_number: 'Bino (zone_number)',
  machine_uuid: 'Machine UUID',
  mac_address: 'MAC',
  number: 'Raqam',
  inventory_code: 'Inventar',
}

function Stat({ label, value, tone }) {
  const theme = useTheme()
  const color = tone ? theme.palette[tone].main : theme.palette.text.primary
  return (
    <Box
      sx={{
        flex: 1, minWidth: 104, px: 2, py: 1.5, borderRadius: '16px',
        bgcolor: tone ? alpha(color, 0.1) : 'm3.surfaceContainerHigh',
      }}
    >
      <Typography variant="h5" sx={{ fontWeight: 600, color }}>{value}</Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Box>
  )
}

/**
 * Kompyuterlarni Excel'dan ommaviy qo'shish.
 *
 * IKKI BOSQICH va ikkalasi bitta server funksiyasi
 * (`devices/computer_import.py`): fayl tanlanishi bilan TEKSHIRUV
 * (`dry_run`) ketadi va natija ko'rsatiladi, «Import qilish» esa faqat
 * xatosiz faylda ochiladi. Server hammasini yoki hech narsani yozadi —
 * ya'ni jadvaldagi xatolar tuzatilib, O'SHA fayl qayta yuklanadi.
 */
export default function ComputerImportDialog({ open, onClose }) {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('md'))
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [showSkipped, setShowSkipped] = useState(false)
  const [showBinds, setShowBinds] = useState(false)

  const check = useMutation({ mutationFn: (value) => computersApi.importExcel(value, true) })
  const commit = useMutation({
    mutationFn: () => computersApi.importExcel(file, false),
    onSuccess: (report) => {
      if (report.errors?.length) return // tekshiruvdan keyin baza o'zgargan
      queryClient.invalidateQueries({ queryKey: ['computers'] })
      notify(
        [
          report.created ? `${report.created} ta kompyuter qo‘shildi` : '',
          report.bound ? `${report.bound} tasiga UUID yozildi` : '',
        ].filter(Boolean).join(' · ') || 'O‘zgarish yo‘q',
      )
      handleClose()
    },
    onError: notifyError,
  })
  const template = useMutation({
    mutationFn: computersApi.importTemplate,
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'kompyuterlar_shablon.xlsx'
      link.click()
      URL.revokeObjectURL(url)
    },
    onError: notifyError,
  })

  const report = commit.data?.errors?.length ? commit.data : check.data
  const errors = report?.errors || []
  const skipped = report?.skipped || []
  const binds = report?.binds || []
  // Yozadigan ish: yangi kompyuterlar + UUID'si to'ldiriladigan eski yozuvlar.
  const pending = errors.length ? 0 : (report?.to_create || 0) + (report?.to_bind || 0)
  const busy = check.isPending || commit.isPending
  const canImport = !!report && pending > 0 && !busy

  const pick = (value) => {
    if (!value) return
    setFile(value)
    setShowSkipped(false)
    setShowBinds(false)
    commit.reset()
    check.mutate(value)
  }

  function handleClose() {
    setFile(null)
    check.reset()
    commit.reset()
    onClose()
  }

  return (
    <Dialog open={open} onClose={busy ? undefined : handleClose} fullWidth maxWidth="md" fullScreen={fullScreen}>
      <DialogTitle sx={{ pr: 6 }}>
        Excel'dan kompyuter qo‘shish
        <Typography variant="body2" color="text.secondary">
          Ustunlar: dtm_id, zone_number, machine_uuid, number; mac_address va inventory_code — ixtiyoriy
        </Typography>
        <IconButton onClick={handleClose} disabled={busy} sx={{ position: 'absolute', right: 12, top: 12 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        <Stack spacing={2.5}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
            <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
              Shablonni yuklab oling, to‘ldiring va shu yerga tashlang. Mashinani Machine UUID
              belgilaydi; UUID’siz eski yozuvga shu MAC bo‘yicha faqat UUID yoziladi. Bitta xato
              bo‘lsa hech narsa yozilmaydi.
            </Typography>
            <Button
              variant="outlined"
              startIcon={<DownloadOutlinedIcon />}
              onClick={() => template.mutate()}
              disabled={template.isPending}
              sx={{ borderRadius: 999, flexShrink: 0 }}
            >
              Shablon (.xlsx)
            </Button>
          </Stack>

          <Box
            role="button"
            tabIndex={0}
            onClick={() => !busy && inputRef.current?.click()}
            onKeyDown={(event) => event.key === 'Enter' && inputRef.current?.click()}
            onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              if (!busy) pick(event.dataTransfer.files?.[0])
            }}
            sx={{
              p: 3, textAlign: 'center', cursor: busy ? 'default' : 'pointer',
              borderRadius: '16px', border: '2px dashed',
              borderColor: dragging ? 'primary.main' : 'm3.outlineVariant',
              bgcolor: dragging ? 'm3.primaryContainer' : 'm3.surfaceContainerLow',
              transition: 'background-color .15s, border-color .15s',
              '&:hover': { borderColor: 'primary.main' },
            }}
          >
            <input
              ref={inputRef}
              type="file"
              hidden
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(event) => { pick(event.target.files?.[0]); event.target.value = '' }}
            />
            {file ? (
              <Stack direction="row" spacing={1} justifyContent="center" alignItems="center">
                <InsertDriveFileOutlinedIcon color="primary" />
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }} noWrap>{file.name}</Typography>
                <Typography variant="body2" color="text.secondary">· boshqa fayl tanlash</Typography>
              </Stack>
            ) : (
              <Stack spacing={0.5} alignItems="center">
                <UploadFileOutlinedIcon color="primary" sx={{ fontSize: 40 }} />
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  Excel faylni shu yerga tashlang yoki tanlang
                </Typography>
                <Typography variant="body2" color="text.secondary">.xlsx, 5 MB gacha, 5000 qatorgacha</Typography>
              </Stack>
            )}
          </Box>

          {busy && <LinearProgress sx={{ borderRadius: 999 }} />}
          {check.isError && <Alert severity="error">{check.error?.userMessage || 'Fayl tekshirilmadi'}</Alert>}

          {report && (
            <>
              <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap">
                <Stat label="Jami qator" value={report.total} />
                <Stat label="Qo‘shiladi" value={errors.length ? 0 : report.to_create} tone="success" />
                {report.to_bind > 0 && (
                  <Stat label="UUID yoziladi" value={errors.length ? 0 : report.to_bind} tone="primary" />
                )}
                <Stat label="Ro‘yxatda bor" value={skipped.length} tone="info" />
                <Stat label="Xato" value={errors.length} tone={errors.length ? 'error' : undefined} />
              </Stack>

              {errors.length > 0 ? (
                <Alert severity="error" variant="outlined" sx={{ borderRadius: '12px' }}>
                  Faylda {errors.length} ta xato — tuzatib, qaytadan yuklang. Hech narsa yozilmadi.
                </Alert>
              ) : pending === 0 ? (
                <Alert severity="info" sx={{ borderRadius: '12px' }}>Yangi kompyuter yo‘q — hammasi ro‘yxatda.</Alert>
              ) : (
                <Alert severity="success" sx={{ borderRadius: '12px' }}>
                  Fayl tekshiruvdan o‘tdi: {report.to_create} ta kompyuter qo‘shiladi
                  {report.to_bind ? `, ${report.to_bind} tasiga UUID yoziladi` : ''}.
                </Alert>
              )}

              {errors.length > 0 && (
                <TableContainer sx={{ maxHeight: 300, borderRadius: '12px', border: 1, borderColor: 'm3.outlineVariant' }}>
                  <Table size="small" stickyHeader sx={{ minWidth: 520 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell width={70}>Qator</TableCell>
                        <TableCell width={170}>Ustun</TableCell>
                        <TableCell>Xato</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {errors.map((item, index) => (
                        <TableRow key={`${item.row}-${item.column}-${index}`} hover>
                          <TableCell sx={{ fontWeight: 600 }}>{item.row}</TableCell>
                          <TableCell>
                            <Chip size="small" label={COLUMN_LABEL[item.column] || item.column} />
                          </TableCell>
                          <TableCell>{item.message}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}

              {binds.length > 0 && !errors.length && (
                <Box>
                  <Button
                    size="small"
                    onClick={() => setShowBinds((value) => !value)}
                    endIcon={<ExpandMoreIcon sx={{ transform: showBinds ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />}
                  >
                    UUID yoziladi: {binds.length} ta (MAC bo‘yicha topilgan eski yozuvlar)
                  </Button>
                  <Collapse in={showBinds}>
                    <Stack spacing={0.5} sx={{ mt: 1, maxHeight: 180, overflowY: 'auto' }}>
                      {binds.map((item) => (
                        <Typography key={item.row} variant="body2" color="text.secondary">
                          {item.row}-qator · {item.machine_uuid} — {item.message}
                        </Typography>
                      ))}
                    </Stack>
                  </Collapse>
                </Box>
              )}

              {skipped.length > 0 && (
                <Box>
                  <Button
                    size="small"
                    onClick={() => setShowSkipped((value) => !value)}
                    endIcon={<ExpandMoreIcon sx={{ transform: showSkipped ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />}
                  >
                    O‘tkazib yuboriladi: {skipped.length} ta (UUID ro‘yxatda bor)
                  </Button>
                  <Collapse in={showSkipped}>
                    <Stack spacing={0.5} sx={{ mt: 1, maxHeight: 180, overflowY: 'auto' }}>
                      {skipped.map((item) => (
                        <Typography key={item.row} variant="body2" color="text.secondary">
                          {item.row}-qator · {item.machine_uuid} — {item.message}
                        </Typography>
                      ))}
                    </Stack>
                  </Collapse>
                </Box>
              )}
            </>
          )}
        </Stack>
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={handleClose} disabled={busy}>Bekor qilish</Button>
        <Button
          variant="contained"
          disableElevation
          onClick={() => commit.mutate()}
          disabled={!canImport}
          sx={{ borderRadius: 999, px: 3 }}
        >
          {pending ? `Import qilish (${pending})` : 'Import qilish'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
