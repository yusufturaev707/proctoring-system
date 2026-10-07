import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, AlertTitle, Autocomplete, Box, Button, Checkbox, Chip, CircularProgress,
  Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControlLabel,
  FormHelperText, Grid, IconButton, InputAdornment, MenuItem, Stack, Switch,
  TextField, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import VisibilityIcon from '@mui/icons-material/VisibilityOutlined'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOffOutlined'
import CheckBoxIcon from '@mui/icons-material/CheckBox'
import CheckBoxBlankIcon from '@mui/icons-material/CheckBoxOutlineBlank'

import ConfirmDialog from '../ConfirmDialog'
import {
  buildInitialValues, buildPayload, isSameValue, mapServerErrors,
  validateField, validateForm,
} from '../../utils/validation'

/**
 * Deklarativ forma.
 *
 * Xavfsizlik jihatlari:
 *   - Ikki marta yuborish bloklanadi (`pending` + `submitLock`);
 *   - Server xatolari aniq maydonlarga bog'lanadi, umumiy "xatolik" emas;
 *   - Yopishdan oldin saqlanmagan o'zgarishlar haqida ogohlantiriladi;
 *   - Yangilashda faqat O'ZGARGAN maydonlar yuboriladi (PATCH) — parallel
 *     tahrirlashda boshqa adminning o'zgarishlari qaytarilmaydi;
 *   - Parol maydonlari hech qachon oldindan to'ldirilmaydi.
 */
export default function ResourceForm({
  open,
  title,
  fields,
  row = null,
  defaults = {},
  submitting = false,
  serverError = null,
  onSubmit,
  onClose,
  maxWidth = 'sm',
  description,
  /**
   * Validator va `disabled` funksiyalariga uzatiladigan qo'shimcha
   * ma'lumot (masalan `isEdit`, `currentUserId`). `buildPayload` faqat
   * `fields` bo'yicha yuradi, shuning uchun bu kalitlar serverga ketmaydi.
   */
  context = {},
  /** Sarlavhadagi tonal belgi (MD3 "leading icon"). */
  icon,
  /**
   * MD3 bo'limlar: `{ [section]: { icon, description } }`. Berilsa har
   * bo'lim alohida karta (sarlavha belgisi + izoh), mantiqiy maydonlar
   * esa "switch qatori" bo'lib chiziladi. Berilmasa — eski ko'rinish,
   * ya'ni boshqa sahifalarning formalari o'zgarmaydi.
   */
  sections: sectionMeta,
}) {
  const isEdit = Boolean(row?.id)
  const m3 = Boolean(sectionMeta)
  const resolvedTitle = typeof title === 'function' ? title(isEdit, row) : title
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const fieldNames = useMemo(() => fields.map((field) => field.name), [fields])

  const [form, setForm] = useState({})
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState({})
  const [generalErrors, setGeneralErrors] = useState([])
  const [confirmClose, setConfirmClose] = useState(false)
  const [revealed, setRevealed] = useState({})

  const initialRef = useRef({})
  const submitLock = useRef(false)

  // Dialog ochilganda formani tiklaymiz.
  useEffect(() => {
    if (!open) return
    const initial = {
      ...buildInitialValues(fields, row, defaults),
      _meta: { isEdit: Boolean(row?.id), row, ...context },
    }
    initialRef.current = initial
    setForm(initial)
    setErrors({})
    setTouched({})
    setGeneralErrors([])
    setRevealed({})
    submitLock.current = false
  }, [open, row]) // eslint-disable-line react-hooks/exhaustive-deps

  // Serverdan kelgan xatolarni maydonlarga bog'laymiz.
  useEffect(() => {
    if (!serverError) return
    const mapped = mapServerErrors(serverError, fieldNames)
    setErrors((prev) => ({ ...prev, ...mapped.fields }))
    setTouched((prev) => ({ ...prev, ...Object.fromEntries(Object.keys(mapped.fields).map((k) => [k, true])) }))
    setGeneralErrors(mapped.general)
    submitLock.current = false
  }, [serverError, fieldNames])

  const isDirty = useMemo(
    () =>
      Object.keys(form).some(
        (key) => key !== '_meta' && !isSameValue(form[key], initialRef.current[key]),
      ),
    [form],
  )

  const setValue = useCallback((field, value) => {
    setForm((prev) => {
      const next = { ...prev, [field.name]: value }

      // Bog'liq maydonlarni tozalash.
      //
      // «Viloyat -> Bino -> Kamera» zanjirida viloyat o'zgarsa, avval
      // tanlangan bino boshqa viloyatga tegishli bo'lib qoladi. Uni
      // o'z holicha qoldirish eng yomon variant: forma to'g'ri
      // ko'rinadi, lekin saqlangan yozuv noto'g'ri binoga bog'lanadi.
      // Shuning uchun zanjirdagi quyi maydonlar aniq tozalanadi.
      ;(field.resets || []).forEach((name) => {
        next[name] = Array.isArray(prev[name]) ? [] : ''
      })

      setErrors((prevErrors) => {
        const cleared = { ...prevErrors }
        ;(field.resets || []).forEach((name) => { cleared[name] = undefined })
        // Maydon allaqachon "tegilgan" bo'lsa, yozayotganda xatoni jonli
        // yangilaymiz. Aks holda birinchi yozuvda xato chiqib,
        // foydalanuvchini chalg'itadi.
        if (!touched[field.name] && !prevErrors[field.name]) return cleared
        cleared[field.name] = validateField(field, value, next) || undefined
        return cleared
      })
      return next
    })
  }, [touched])

  const handleBlur = useCallback((field) => {
    setTouched((prev) => ({ ...prev, [field.name]: true }))
    setErrors((prev) => ({ ...prev, [field.name]: validateField(field, form[field.name], form) || undefined }))
  }, [form])

  const handleSubmit = (event) => {
    event.preventDefault()
    if (submitLock.current || submitting) return

    const validationErrors = validateForm(fields, form)
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      setTouched(Object.fromEntries(fields.map((field) => [field.name, true])))
      // Birinchi xato maydonga sakraymiz — uzun formada qidirish shart emas.
      const firstError = fields.find((field) => validationErrors[field.name])
      document.getElementById(`field-${firstError?.name}`)?.focus()
      return
    }

    const payload = buildPayload(fields, form, isEdit ? initialRef.current : null)

    if (isEdit && Object.keys(payload).length === 0) {
      onClose?.()
      return
    }

    submitLock.current = true
    setGeneralErrors([])
    onSubmit?.(isEdit ? { id: row.id, ...payload } : payload)
  }

  const requestClose = () => {
    if (isDirty && !submitting) {
      setConfirmClose(true)
      return
    }
    onClose?.()
  }

  const visibleFields = fields.filter((field) => !field.hidden?.(form))
  const sections = groupBySection(visibleFields)

  return (
    <>
      <Dialog
        open={open}
        onClose={(_, reason) => {
          // Tasodifan tashqariga bosib, to'ldirilgan formani yo'qotmaslik.
          if (reason === 'backdropClick' && isDirty) return
          requestClose()
        }}
        maxWidth={maxWidth}
        fullWidth
        // Telefonda forma TO'LIQ EKRAN (M3 "full-screen dialog"): o'nta
        // maydonli forma 16 px chetli oynada klaviatura ochilganda ikki
        // qatorga tushib qolardi.
        fullScreen={fullScreen}
        keepMounted={false}
        // MD3: dialog sirti "low", bo'lim kartalari undan ochroq — kartalar
        // fon ustida "ko'tarilgan" bo'lib o'qiladi (`ComputerDetailDialog`
        // bilan bir xil yechim).
        PaperProps={m3 ? { sx: { bgcolor: 'm3.surfaceContainerLow' } } : undefined}
      >
        {/* Forma paper'ning FLEX bolasi: sarlavha va tugmalar joyida qoladi,
            faqat maydonlar suriladi. Ilgari butun oyna surilardi va uzun
            formada «Saqlash» tugmasi pastda, ko'rinmay qolardi. */}
        <Box
          component="form"
          onSubmit={handleSubmit}
          noValidate
          sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: '1 1 auto' }}
        >
          <DialogTitle component="div" sx={{ pr: 7, ...(m3 ? { pt: 3, pb: 2 } : {}) }}>
            <Stack direction="row" spacing={2} alignItems="center">
              {icon && (
                <Box
                  sx={{
                    width: 48, height: 48, borderRadius: '16px', flexShrink: 0,
                    display: 'grid', placeItems: 'center',
                    bgcolor: 'm3.primaryContainer', color: 'm3.onPrimaryContainer',
                  }}
                >
                  {icon}
                </Box>
              )}
              <Box sx={{ minWidth: 0 }}>
                <Typography component="h2" sx={{ font: 'inherit' }}>
                  {resolvedTitle || (isEdit ? 'Tahrirlash' : 'Yangi yozuv')}
                </Typography>
                {description && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
                    {description}
                  </Typography>
                )}
              </Box>
            </Stack>
            <IconButton
              onClick={requestClose}
              sx={{ position: 'absolute', right: 12, top: 12 }}
              aria-label="Yopish"
            >
              <CloseIcon />
            </IconButton>
          </DialogTitle>

          <DialogContent dividers={!m3} sx={m3 ? { px: { xs: 2, sm: 3 }, pt: '4px !important' } : undefined}>
            {generalErrors.length > 0 && (
              <Alert severity="error" sx={{ mb: 2.5 }}>
                <AlertTitle>Saqlab bo‘lmadi</AlertTitle>
                {generalErrors.map((message, index) => (
                  <Typography key={index} variant="body2">{message}</Typography>
                ))}
              </Alert>
            )}

            {m3 && sections.map(({ section, items }, sectionIndex) => (
              <SectionCard key={section || sectionIndex} title={section} meta={sectionMeta[section]}>
                <Grid container spacing={{ xs: 2, sm: 2.5 }}>
                  {items.map((field) => (
                    <Grid item xs={12} sm={field.colSpan || 12} key={field.name}>
                      <FieldControl
                        field={field}
                        form={form}
                        value={form[field.name]}
                        error={touched[field.name] ? errors[field.name] : undefined}
                        disabled={submitting || field.disabled?.(form, isEdit)}
                        revealed={revealed[field.name]}
                        onReveal={() =>
                          setRevealed((prev) => ({ ...prev, [field.name]: !prev[field.name] }))
                        }
                        onChange={(value) => setValue(field, value)}
                        onBlur={() => handleBlur(field)}
                        isEdit={isEdit}
                        m3
                      />
                    </Grid>
                  ))}
                </Grid>
              </SectionCard>
            ))}

            {!m3 && sections.map(({ section, items }, sectionIndex) => (
              <Box key={section || sectionIndex} sx={{ mb: sectionIndex < sections.length - 1 ? 3 : 0 }}>
                {section && (
                  <>
                    <Typography variant="overline" color="text.secondary">{section}</Typography>
                    <Divider sx={{ mb: 2, mt: 0.5 }} />
                  </>
                )}
                <Grid container spacing={{ xs: 2, sm: 2.5 }}>
                  {items.map((field) => (
                    <Grid item xs={12} sm={field.colSpan || 12} key={field.name}>
                      <FieldControl
                        field={field}
                        form={form}
                        value={form[field.name]}
                        error={touched[field.name] ? errors[field.name] : undefined}
                        disabled={submitting || field.disabled?.(form, isEdit)}
                        revealed={revealed[field.name]}
                        onReveal={() =>
                          setRevealed((prev) => ({ ...prev, [field.name]: !prev[field.name] }))
                        }
                        onChange={(value) => setValue(field, value)}
                        onBlur={() => handleBlur(field)}
                        isEdit={isEdit}
                      />
                    </Grid>
                  ))}
                </Grid>
              </Box>
            ))}
          </DialogContent>

          <DialogActions
            sx={{
              px: { xs: 2, sm: 3 }, py: 2, pb: { xs: 'calc(16px + env(safe-area-inset-bottom))', sm: 2 },
              ...(m3 ? { bgcolor: 'm3.surfaceContainer', borderTop: 1, borderColor: 'divider' } : {}),
            }}
          >
            {isDirty && (
              <Typography variant="caption" color="text.secondary" sx={{ mr: 'auto' }}>
                Saqlanmagan o‘zgarishlar bor
              </Typography>
            )}
            <Button onClick={requestClose} color="inherit" disabled={submitting}>
              Bekor qilish
            </Button>
            <Button
              type="submit"
              variant="contained"
              disabled={submitting || (isEdit && !isDirty)}
              startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : null}
            >
              {submitting ? 'Saqlanmoqda…' : 'Saqlash'}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>

      <ConfirmDialog
        open={confirmClose}
        title="O‘zgarishlarni bekor qilasizmi?"
        description="Kiritilgan ma’lumotlar saqlanmaydi."
        confirmLabel="Ha, yopilsin"
        color="warning"
        onConfirm={() => {
          setConfirmClose(false)
          onClose?.()
        }}
        onClose={() => setConfirmClose(false)}
      />
    </>
  )
}

// --------------------------------------------------------------------------
function FieldControl({ field, form, value, error, disabled, onChange, onBlur, isEdit, revealed, onReveal, m3 }) {
  const id = `field-${field.name}`
  // `helperText` matn yoki funksiya bo'lishi mumkin — string'ni funksiya
  // sifatida chaqirish TypeError beradi, shuning uchun turini tekshiramiz.
  // Ikkinchi argument — forma: izoh boshqa maydonga bog'liq bo'lishi
  // mumkin ("respublika roli tanlangan — viloyat shart emas").
  const helper =
    error ||
    (typeof field.helperText === 'function' ? field.helperText(isEdit, form) : field.helperText)

  /**
   * O'ziga xos boshqaruv (masalan rol ruxsatlari matritsasi).
   *
   * Bunday elementni sahifaning o'zida yasash oson, lekin shunda u
   * formaning barcha kafolatlarini yo'qotadi: saqlanmagan o'zgarish
   * ogohlantirishi, ikki marta yuborishdan himoya, server xatosini
   * maydonga bog'lash. Shu slot orqali u dvigatel ICHIDA qoladi.
   */
  if (field.type === 'custom') {
    return (
      <Box>
        {field.label && (
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{field.label}</Typography>
        )}
        {field.render({ value, onChange, disabled, error, form, isEdit })}
        {helper && (
          <FormHelperText error={Boolean(error)} sx={{ ml: 0, mt: 1 }}>{helper}</FormHelperText>
        )}
      </Box>
    )
  }

  // MD3 "switch list item": sarlavha + izoh chapda, kalit o'ngda, butun
  // qator bosiladi. Oddiy `FormControlLabel` da izoh kalit ostida osilib
  // qolardi va ikki ustunli bo'limda qatorlar tekislanmasdi.
  if (field.type === 'boolean' && m3) {
    return (
      <Box
        component="label"
        htmlFor={id}
        sx={{
          display: 'flex', alignItems: 'center', gap: 2, height: '100%',
          px: 2, py: 1.5, borderRadius: '12px', cursor: disabled ? 'default' : 'pointer',
          border: 1, borderColor: error ? 'error.main' : 'm3.outlineVariant',
          bgcolor: value ? 'm3.secondaryContainer' : 'transparent',
          transition: 'background-color 150ms',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" fontWeight={600}>{field.label}</Typography>
          {helper && (
            <Typography variant="caption" color={error ? 'error' : 'text.secondary'} display="block" sx={{ mt: 0.25 }}>
              {helper}
            </Typography>
          )}
        </Box>
        <Switch
          id={id}
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          disabled={disabled}
        />
      </Box>
    )
  }

  if (field.type === 'boolean') {
    return (
      <Box>
        <FormControlLabel
          control={
            <Switch
              id={id}
              checked={Boolean(value)}
              onChange={(event) => onChange(event.target.checked)}
              disabled={disabled}
            />
          }
          label={field.label}
        />
        {helper && (
          <FormHelperText error={Boolean(error)} sx={{ ml: 0 }}>{helper}</FormHelperText>
        )}
      </Box>
    )
  }

  // Variantlar formaga BOG'LIQ bo'lishi mumkin: «shu viloyatning
  // binolari», «shu binodagi kameralar». Shuning uchun `options` massiv
  // ham, funksiya ham bo'la oladi.
  const options = (typeof field.options === 'function' ? field.options(form) : field.options) || []

  // Zanjirdagi yuqori maydon tanlanmaguncha quyisi ma'noga ega emas:
  // "barcha binolar" ro'yxatini ko'rsatish foydalanuvchini boshqa
  // viloyatning binosini tanlashga undaydi. Shuning uchun u to'siladi
  // va nima qilish kerakligi aniq aytiladi.
  const blockedBy = field.dependsOn && !form?.[field.dependsOn]

  // Ro'yxat uzun bo'lsa `select` yaroqsiz: 400 ta binoni ochiladigan
  // ro'yxatdan sichqoncha bilan qidirish — bir necha soniyalik ish.
  // Shu chegaradan keyin avtomatik terib-qidiriladigan variantga o'tamiz.
  const AUTOCOMPLETE_THRESHOLD = 12
  const useAutocomplete =
    field.type === 'autocomplete' ||
    (field.type === 'select' && options.length > AUTOCOMPLETE_THRESHOLD)

  if (field.type === 'multiselect') {
    const selected = Array.isArray(value) ? value : []
    return (
      <Autocomplete
        multiple
        disableCloseOnSelect
        id={id}
        options={options}
        value={options.filter((option) => selected.includes(option.value))}
        onChange={(_, picked) => onChange(picked.map((option) => option.value))}
        onBlur={onBlur}
        disabled={disabled || blockedBy}
        getOptionLabel={(option) => option.label ?? ''}
        isOptionEqualToValue={(option, item) => option.value === item.value}
        limitTags={4}
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
              {option.label}
            </li>
          )
        }}
        renderTags={(picked, getTagProps) =>
          picked.map((option, index) => {
            const { key, ...rest } = getTagProps({ index })
            return <Chip key={key} {...rest} size="small" label={option.label} />
          })
        }
        renderInput={(params) => (
          <TextField
            {...params}
            label={field.label}
            required={field.required}
            error={Boolean(error)}
            helperText={
              (blockedBy && field.blockedText) ||
              helper ||
              (selected.length ? `${selected.length} ta tanlangan` : undefined)
            }
          />
        )}
      />
    )
  }

  if (useAutocomplete) {
    const current = options.find((option) => String(option.value) === String(value ?? '')) || null
    return (
      <Autocomplete
        id={id}
        options={options}
        value={current}
        onChange={(_, picked) => onChange(picked ? picked.value : '')}
        onBlur={onBlur}
        disabled={disabled || blockedBy || !options.length}
        disableClearable={Boolean(field.required)}
        getOptionLabel={(option) => option.label ?? ''}
        isOptionEqualToValue={(option, item) => option.value === item.value}
        noOptionsText="Mos variant yo‘q"
        renderInput={(params) => (
          <TextField
            {...params}
            label={field.label}
            required={field.required}
            error={Boolean(error)}
            helperText={
              (blockedBy && field.blockedText) ||
              helper ||
              (!options.length ? emptyOptionsText(field, blockedBy) : undefined)
            }
          />
        )}
      />
    )
  }

  if (field.type === 'select') {
    return (
      <TextField
        id={id}
        select
        label={field.label}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        required={field.required}
        disabled={disabled || blockedBy || !options.length}
        error={Boolean(error)}
        helperText={
          (blockedBy && field.blockedText) ||
          helper ||
          (!options.length ? emptyOptionsText(field, blockedBy) : undefined)
        }
      >
        {!field.required && <MenuItem value=""><em>Tanlanmagan</em></MenuItem>}
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
        ))}
      </TextField>
    )
  }

  const isPassword = field.type === 'password'
  const inputType = isPassword ? (revealed ? 'text' : 'password') : (field.type || 'text')

  return (
    <TextField
      id={id}
      label={field.label}
      type={field.type === 'datetime' ? 'datetime-local' : inputType}
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onBlur}
      required={field.required}
      disabled={disabled}
      error={Boolean(error)}
      helperText={helper}
      multiline={field.type === 'textarea' || field.type === 'json'}
      minRows={field.type === 'json' ? 4 : field.type === 'textarea' ? 2 : undefined}
      autoComplete={isPassword ? 'new-password' : field.autoComplete || 'off'}
      inputProps={{
        maxLength: field.maxLength,
        min: field.min,
        max: field.max,
        step: field.step,
        // Parol menejerlari va brauzer avtoto'ldirishini o'chiramiz —
        // admin panelida boshqa foydalanuvchi ma'lumoti tasodifan
        // to'ldirilib qolmasligi kerak.
        ...(isPassword ? { 'data-lpignore': 'true' } : {}),
        ...(field.type === 'json' ? { style: { fontFamily: 'monospace', fontSize: 13 } } : {}),
      }}
      InputLabelProps={
        ['date', 'datetime', 'time'].includes(field.type) ? { shrink: true } : undefined
      }
      InputProps={
        isPassword
          ? {
              endAdornment: (
                <InputAdornment position="end">
                  <Tooltip title={revealed ? 'Yashirish' : 'Ko‘rsatish'}>
                    <IconButton size="small" onClick={onReveal} edge="end" tabIndex={-1}>
                      {revealed ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                    </IconButton>
                  </Tooltip>
                </InputAdornment>
              ),
            }
          : undefined
      }
    />
  )
}

/**
 * Ro'yxat bo'sh bo'lganda nima deyish kerak.
 *
 * "Variantlar yuklanmoqda…" ni har doim ko'rsatish yolg'on bo'ladi:
 * zanjirli maydonda ro'yxat bo'sh bo'lishining sababi yuklanish emas,
 * balki tanlangan viloyatda umuman bino yo'qligi bo'lishi mumkin —
 * bunda foydalanuvchi bekorga kutadi.
 */
function emptyOptionsText(field, blockedBy) {
  if (blockedBy) return field.blockedText
  return field.emptyOptionsText || 'Variantlar yuklanmoqda…'
}

/**
 * MD3 bo'lim kartasi: tonal belgi + sarlavha + izoh, ostida maydonlar.
 * Karta dialog sirtidan ochroq (`background.paper`) — guruh chegarasini
 * chiziq emas, sirt rangi beradi.
 */
function SectionCard({ title, meta = {}, children }) {
  const Icon = meta.icon
  return (
    <Box sx={{ bgcolor: 'background.paper', borderRadius: '16px', p: { xs: 2, sm: 2.5 }, mb: 1.5 }}>
      {title && (
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
          {Icon && (
            <Box
              sx={{
                width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
                display: 'grid', placeItems: 'center',
                bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer',
              }}
            >
              <Icon fontSize="small" />
            </Box>
          )}
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ lineHeight: 1.3 }}>{title}</Typography>
            {meta.description && (
              <Typography variant="caption" color="text.secondary" display="block">
                {meta.description}
              </Typography>
            )}
          </Box>
        </Stack>
      )}
      {children}
    </Box>
  )
}

function groupBySection(fields) {
  const map = new Map()
  fields.forEach((field) => {
    const key = field.section || ''
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(field)
  })
  return Array.from(map, ([section, items]) => ({ section, items }))
}
