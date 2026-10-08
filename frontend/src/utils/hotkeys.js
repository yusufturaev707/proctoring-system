/**
 * Tezkor tugma kodi — client qulfi bilan AYNAN bir xil lug'at.
 *
 * Manba: `client/services/lockdown.py` (`_KEY_ALIASES`, `_MODIFIER_VKS`,
 * `_NAMED_VKS`, `_NEVER_BLOCKED`); server nusxasi
 * `backend/src/apps/controls/hotkeys.py` (testda client bilan
 * solishtiriladi). Client tanimagan kodni BLOKLAMAYDI — shuning uchun
 * forma kodni yozilayotgan paytda tekshiradi va tugmalar ko'rinishida
 * ko'rsatadi. Yakuniy qaror baribir serverda.
 */

export const KEY_ALIASES = {
  printscreen: 'print screen',
  prtsc: 'print screen',
  'prt sc': 'print screen',
  prtscr: 'print screen',
  'prnt scrn': 'print screen',
  escape: 'esc',
  windows: 'win',
  meta: 'win',
  super: 'win',
  cmd: 'win',
  del: 'delete',
  ins: 'insert',
  pgup: 'page up',
  pgdn: 'page down',
  return: 'enter',
  capslock: 'caps lock',
  numlock: 'num lock',
  scrolllock: 'scroll lock',
  spacebar: 'space',
  'arrow up': 'up',
  'arrow down': 'down',
  'arrow left': 'left',
  'arrow right': 'right',
  plus: '=',
  minus: '-',
}

export const NEVER_BLOCKED = new Set(['ctrl+q'])

const MODIFIERS = new Set([
  'alt', 'left alt', 'right alt', 'alt gr',
  'ctrl', 'control', 'left ctrl', 'right ctrl',
  'shift', 'left shift', 'right shift',
  'win', 'left windows', 'right windows',
])

const NAMED_KEYS = new Set([
  'backspace', 'tab', 'enter', 'pause', 'caps lock', 'esc', 'space',
  'page up', 'page down', 'end', 'home', 'left', 'up', 'right', 'down',
  'print screen', 'insert', 'delete', 'apps', 'menu',
  'num *', 'num +', 'num -', 'num .', 'num /', 'num lock', 'scroll lock',
  ';', '=', ',', '-', '.', '/', '`', '[', '\\', ']', "'",
  ...Array.from({ length: 10 }, (_, i) => `num ${i}`),
  ...Array.from({ length: 24 }, (_, i) => `f${i + 1}`),
])

/** Tugmachada ko'rinadigan yozuv (kodda — kichik harf). */
const CAP_LABEL = {
  ctrl: 'Ctrl', control: 'Ctrl', 'left ctrl': 'Chap Ctrl', 'right ctrl': 'O‘ng Ctrl',
  alt: 'Alt', 'left alt': 'Chap Alt', 'right alt': 'O‘ng Alt', 'alt gr': 'AltGr',
  shift: 'Shift', 'left shift': 'Chap Shift', 'right shift': 'O‘ng Shift',
  win: 'Win', 'left windows': 'Chap Win', 'right windows': 'O‘ng Win',
  esc: 'Esc', tab: 'Tab', enter: 'Enter', space: 'Probel', backspace: 'Backspace',
  'print screen': 'PrtSc', delete: 'Delete', insert: 'Insert', home: 'Home', end: 'End',
  'page up': 'PgUp', 'page down': 'PgDn', 'caps lock': 'CapsLock', 'num lock': 'NumLock',
  'scroll lock': 'ScrollLock', pause: 'Pause', apps: 'Menyu', menu: 'Menyu',
  up: '↑', down: '↓', left: '←', right: '→',
}

export const isModifier = (part) => MODIFIERS.has(part)

/** `Ctrl + Shift+I` -> `ctrl+shift+i` (client `_normalize`). */
export function normalizeHotkey(code) {
  return String(code ?? '')
    .split('+')
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .map((part) => KEY_ALIASES[part] || part)
    .join('+')
}

const isKey = (name) =>
  MODIFIERS.has(name) || NAMED_KEYS.has(name) || /^[a-z0-9]$/.test(name)

/**
 * Kodni client qoidasi bilan tekshiradi.
 * Qaytaradi: `{ code, parts, error }` — `error` bo'sh bo'lsa client
 * kombinatsiyani taniydi va bloklaydi.
 */
export function parseHotkey(raw) {
  const code = normalizeHotkey(raw)
  const parts = code ? code.split('+') : []
  let error = ''
  if (!parts.length) error = 'Kombinatsiyani kiriting, masalan: alt+tab'
  else {
    const unknown = parts.filter((part) => !isKey(part))
    if (unknown.length) error = `Client bu tugmani tanimaydi: ${unknown.map((part) => `«${part}»`).join(', ')}`
    else if (new Set(parts).size !== parts.length) error = 'Bir tugma ikki marta yozilgan'
    else if (parts.filter((part) => !MODIFIERS.has(part)).length > 1) {
      error = 'Faqat bitta asosiy tugma bo‘lishi mumkin (qolganlari Ctrl/Alt/Shift/Win)'
    } else if (NEVER_BLOCKED.has(code)) {
      error = 'Ctrl+Q bloklanmaydi — bu dasturdan chiqishning yagona yo‘li'
    }
  }
  return { code, parts, error }
}

export const capLabel = (part) =>
  CAP_LABEL[part] || (/^f\d+$/.test(part) ? part.toUpperCase() : part.length === 1 ? part.toUpperCase() : part)

/** Odam o'qiydigan nom: `ctrl+shift+i` -> `Ctrl+Shift+I`. */
export const hotkeyLabel = (code) => normalizeHotkey(code).split('+').filter(Boolean).map(capLabel).join('+')
