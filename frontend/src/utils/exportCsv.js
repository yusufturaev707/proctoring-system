/**
 * Jadval qatorlarini CSV ga saqlaydi.
 *
 * Ajratgich sifatida `;` ishlatiladi va fayl BOM bilan boshlanadi:
 * bularsiz Excel (RU/UZ lokalida) faylni bitta ustunga yig'ib qo'yadi va
 * kirill/lotin harflarini buzib ko'rsatadi.
 *
 * Modul `ResourcePage` ichidan chiqarildi, chunki uni endi `Sessions`
 * sahifasi ham ishlatadi. Ikkita nusxa bo'lsa, biri o'zgarganda
 * eksport fayllari bir-biriga mos kelmay qolardi.
 */
export function exportCsv(columns, rows, name) {
  const usable = columns.filter((column) => !column.field.startsWith('__'))
  const escape = (value) => {
    const text = value == null ? '' : String(value)
    return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }

  const header = usable.map((column) => escape(column.headerName || column.field)).join(';')
  const body = rows.map((row) =>
    usable
      .map((column) => {
        const raw = row[column.field]

        // Ustun qiymatini uchta manbadan olamiz, shu tartibda:
        //
        //   1. `exportValue` — ustun faqat `renderCell` bilan chizilgan
        //      bo'lsa (chip, switch, ikonka), xom qiymat odamga hech
        //      narsa aytmaydi: `in_exam`, `true`, `[{...}]`. Shu funksiya
        //      o'sha ustun uchun o'qiladigan matnni beradi.
        //   2. `valueGetter` — jadvalda ko'rinadigan qiymat.
        //   3. xom qiymat.
        //
        // Maqsad bitta: eksport fayli ekranda ko'ringan narsaga mos
        // kelsin, aks holda hisobotni tekshirib bo'lmaydi.
        let value
        if (typeof column.exportValue === 'function') value = column.exportValue(raw, row)
        else if (typeof column.valueGetter === 'function') value = column.valueGetter(raw, row, column)
        else value = raw

        if (typeof value === 'boolean') value = value ? 'ha' : 'yo‘q'
        if (typeof value === 'object' && value !== null) value = JSON.stringify(value)
        return escape(value)
      })
      .join(';'),
  )

  const csv = `﻿${[header, ...body].join('\r\n')}`
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${name}-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

export default exportCsv
