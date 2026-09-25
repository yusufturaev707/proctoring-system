/**
 * Filtr maydonining o'lchami — telefonda TO'LIQ kenglik, kattaroq
 * ekranda esa qat'iy oraliq.
 *
 * Ilgari har sahifa `sx={{ minWidth: 230, maxWidth: 280 }}` yozardi va
 * 390 px ekranda maydonlar har xil kenglikda, tartibsiz "zinapoya"
 * bo'lib chiqardi (bittasi 280, keyingisi 180). Qoida bitta joyda:
 * yangi filtr qo'shganda shu funksiyani ishlating.
 */
export const filterFieldSx = (minWidth = 200, maxWidth = 260, { half = false } = {}) => ({
  // `half` — telefonda ikki ustun (qator oralig'i 12 px bo'lgan
  // konteynerda). Filtrlar doim ochiq turadigan sahifalar uchun: to'rtta
  // to'liq kenglikdagi maydon jadvalni ekrandan pastga surib yuborardi.
  width: { xs: half ? 'calc(50% - 6px)' : '100%', sm: 'auto' },
  minWidth: { sm: minWidth },
  maxWidth: { sm: maxWidth },
})

export const FILTER_FIELD_SX = filterFieldSx()
