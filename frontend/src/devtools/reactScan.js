/**
 * React Scan — ortiqcha renderlarni ko'rsatadi (FAQAT dev).
 *
 * Ishga tushirish: `npm run dev:scan`. Oddiy `npm run dev` va production
 * build'ga bu fayl UMUMAN kirmaydi: uni `vite.config.js` dagi
 * `reactScanPlugin` faqat `--mode scan` da `index.html` ga ilova
 * kodidan OLDIN qo'shadi. React Scan React'dan oldin yuklanishi SHART —
 * u React DevTools hook'iga ulanadi va keyin yuklansa renderlarni ko'rmaydi.
 *
 * Ekranda: render bo'lgan komponent ramka bilan yonadi, pastdagi
 * panelda — FPS va komponent tafsiloti (nima o'zgargani).
 *
 * Konsoldan (yoki Playwright'dan) yig'ma:
 *   __renderStats.top(20)      — eng ko'p render bo'lganlar
 *   __renderStats.reset()      — hisobni nolga (amaldan oldin)
 * `reasons` — nima o'zgargani: props/state/context nomi bo'yicha. Ko'p
 * render + bo'sh `reasons` — ota render bo'lgani uchun (memo yo'q).
 */
import { scan } from 'react-scan'

const REASON = { 1: 'props', 2: 'state', 3: 'state', 4: 'context' }
const stats = new Map()

function record(renders) {
  for (const render of renders) {
    const name = render.componentName || 'Anonymous'
    let row = stats.get(name)
    if (!row) {
      row = { name, renders: 0, time: 0, reasons: {} }
      stats.set(name, row)
    }
    const count = render.count || 1
    row.renders += count
    row.time += render.time || 0
    for (const change of render.changes || []) {
      const key = `${REASON[change.type] || '?'}:${change.name}`
      row.reasons[key] = (row.reasons[key] || 0) + 1
    }
  }
}

window.__renderStats = {
  reset: () => stats.clear(),
  top: (limit = 25) =>
    [...stats.values()]
      .sort((a, b) => b.renders - a.renders)
      .slice(0, limit)
      .map((row) => ({
        ...row,
        time: Math.round(row.time * 10) / 10,
        reasons: Object.entries(row.reasons)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 6)
          .map(([key, count]) => `${key}×${count}`)
          .join(', '),
      })),
}

scan({
  enabled: true,
  showToolbar: true,
  animationSpeed: 'fast',
  log: false,
  onRender: (_fiber, renders) => record(renders),
})
