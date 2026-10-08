import { useState } from 'react'
import { Autocomplete, Chip, TextField } from '@mui/material'

/**
 * Qiymatlar ro'yxati — chip'lar bilan (JSON matn o'rniga).
 *
 * Ilgari bu maydonlar `["AnyDesk.exe"]` ko'rinishidagi JSON matn edi:
 * bitta qo'shtirnoq yoki vergul xatosi butun formani to'xtatardi va
 * administrator JSON sintaksisini bilishi shart edi. Endi qiymat yoziladi
 * va Enter / vergul bilan qo'shiladi; bir nechta qiymat vergul bilan
 * birdan qo'yilishi mumkin. Maydondan chiqilganda yozib qo'yilgan matn
 * ham qo'shiladi — aks holda u jimgina yo'qolardi.
 *
 * `numeric` — portlar: faqat 1..65535 butun son; noto'g'ri qiymat
 * qo'shilmaydi va sababi maydon ostida aytiladi.
 */
export default function ChipListInput({
  value, onChange, label, placeholder, helperText, error, disabled, numeric = false,
}) {
  const items = Array.isArray(value) ? value : []
  const [input, setInput] = useState('')
  const [localError, setLocalError] = useState('')

  const add = (raw) => {
    const pieces = String(raw).split(',').map((piece) => piece.trim()).filter(Boolean)
    if (!pieces.length) return
    const next = [...items]
    const rejected = []
    for (const piece of pieces) {
      let item = piece
      if (numeric) {
        const port = Number(piece)
        if (!/^\d+$/.test(piece) || port < 1 || port > 65535) {
          rejected.push(piece)
          continue
        }
        item = port
      }
      // Takror qo'shilmaydi (katta-kichik harf farqsiz — client ham
      // qiymatlarni kichik harfga keltirib solishtiradi).
      const key = String(item).toLowerCase()
      if (!next.some((existing) => String(existing).toLowerCase() === key)) next.push(item)
    }
    setLocalError(rejected.length ? `Port 1–65535 oralig‘idagi butun son: ${rejected.join(', ')}` : '')
    if (next.length !== items.length) onChange(next)
    setInput('')
  }

  return (
    <Autocomplete
      multiple
      freeSolo
      options={[]}
      value={items}
      inputValue={input}
      disabled={disabled}
      onChange={(_, next, reason) => {
        // `createOption` — Enter bilan yozilgan matn: vergulli bo'lsa
        // bo'laklarga ajratamiz; o'chirishda ro'yxat o'zi keladi.
        if (reason === 'createOption') add(next[next.length - 1])
        else onChange(next)
      }}
      onInputChange={(_, text, reason) => {
        if (reason !== 'input') return
        if (text.includes(',')) add(text)
        else setInput(text)
      }}
      onBlur={() => input.trim() && add(input)}
      renderTags={(selected, getTagProps) =>
        selected.map((item, index) => {
          const { key, ...rest } = getTagProps({ index })
          return (
            <Chip
              key={key}
              {...rest}
              size="small"
              label={String(item)}
              sx={{ bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer', fontFamily: 'monospace' }}
            />
          )
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={items.length ? '' : placeholder}
          error={Boolean(error || localError)}
          // Forma xatosini `ResourceForm` maydon ostida o'zi chiqaradi —
          // bu yerda takrorlansa ikki marta ko'rinardi.
          helperText={localError || (error ? undefined : helperText)}
        />
      )}
    />
  )
}
