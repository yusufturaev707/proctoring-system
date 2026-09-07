/**
 * Forma validatsiyasi.
 *
 * Muhim tamoyil: bu qatlam faqat FOYDALANUVCHI QULAYLIGI uchun — noto'g'ri
 * ma'lumot serverga bormasligi va xato darhol ko'rinishi uchun. Haqiqiy
 * himoya har doim backendda (DRF serializer + DB constraint). Frontend
 * validatsiyasini xavfsizlik chorasi deb hisoblash mumkin emas: uni
 * DevTools orqali chetlab o'tish bir necha soniyalik ish.
 */

const MAC_RE = /^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$/
const IPV4_RE = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/
const PINFL_RE = /^\d{14}$/

export const PATTERNS = {
  mac: { re: MAC_RE, message: 'Format: AA:BB:CC:DD:EE:FF' },
  ipv4: { re: IPV4_RE, message: 'To‘g‘ri IPv4 manzil kiriting' },
  pinfl: { re: PINFL_RE, message: 'JSHSHIR 14 ta raqamdan iborat' },
  slug: { re: /^[A-Za-z0-9_-]+$/, message: 'Faqat harf, raqam, `-` va `_`' },
  url: { re: /^https?:\/\/.+/i, message: 'URL http:// yoki https:// bilan boshlanishi kerak' },
}

/**
 * Ikki forma qiymatini solishtiradi.
 *
 * Massivlar uchun `===` YARAMAYDI: `[1,2] !== [1,2]`. Buni hisobga
 * olmaslik ikkita ko'rinadigan nosozlik beradi — «saqlanmagan
 * o'zgarishlar bor» ogohlantirishi hech qachon o'chmaydi va PATCH
 * so'roviga tegilmagan M2M maydonlar ham qo'shilib ketadi.
 */
export function isSameValue(a, b) {
  if (a === b) return true
  if (a == null && b == null) return true
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false
    // M2M tanlovi uchun tartib ahamiyatsiz — foydalanuvchi bir xil
    // to'plamni boshqa tartibda tanlagani o'zgarish hisoblanmaydi.
    const left = [...a].map(String).sort()
    const right = [...b].map(String).sort()
    return left.every((item, index) => item === right[index])
  }
  return false
}

/** Bitta maydonni tekshiradi. Xato bo'lsa matn, aks holda `null`. */
export function validateField(field, value, form) {
  const isEmpty = value === '' || value === null || value === undefined ||
    (Array.isArray(value) && value.length === 0)

  if (field.required && isEmpty && field.type !== 'boolean') {
    return 'Bu maydon to‘ldirilishi shart'
  }

  // Bo'sh va majburiy bo'lmagan maydonga uzunlik/format qoidalari
  // tegishli emas — lekin MAXSUS validator baribir chaqiriladi.
  //
  // Sabab: aynan shartli majburiylik shu validator orqali ifodalanadi
  // («yangi foydalanuvchi uchun parol shart, tahrirlashda ixtiyoriy»,
  // «rolda kamida bitta ruxsat bo'lsin»). Ilgari bu yerda shartsiz
  // `return null` turardi va bunday qoidalar jimgina o'tkazib
  // yuborilardi — xato faqat serverdan qaytgach ko'rinardi.
  if (isEmpty) {
    return typeof field.validate === 'function' ? field.validate(value, form) || null : null
  }

  if (Array.isArray(value)) {
    if (field.minItems && value.length < field.minItems) {
      return `Kamida ${field.minItems} ta tanlang`
    }
    if (field.maxItems && value.length > field.maxItems) {
      return `Ko‘pi bilan ${field.maxItems} ta tanlash mumkin`
    }
  }

  if (field.type === 'number') {
    const numeric = Number(value)
    if (Number.isNaN(numeric)) return 'Raqam kiriting'
    if (field.min !== undefined && numeric < field.min) return `Eng kam qiymat: ${field.min}`
    if (field.max !== undefined && numeric > field.max) return `Eng katta qiymat: ${field.max}`
    if (field.integer && !Number.isInteger(numeric)) return 'Butun son kiriting'
  }

  if (typeof value === 'string') {
    if (field.minLength && value.length < field.minLength) {
      return `Kamida ${field.minLength} ta belgi`
    }
    if (field.maxLength && value.length > field.maxLength) {
      return `Ko‘pi bilan ${field.maxLength} ta belgi`
    }
    if (field.pattern) {
      const rule = typeof field.pattern === 'string' ? PATTERNS[field.pattern] : field.pattern
      if (rule && !rule.re.test(value)) return rule.message
    }
  }

  if (field.type === 'json' && typeof value === 'string') {
    try {
      JSON.parse(value)
    } catch {
      return 'JSON formati noto‘g‘ri'
    }
  }

  // Maydonga xos maxsus qoida (boshqa maydonlarga bog'liq bo'lishi mumkin).
  if (typeof field.validate === 'function') {
    return field.validate(value, form) || null
  }

  return null
}

/** Butun formani tekshiradi. `{fieldName: message}` qaytaradi. */
export function validateForm(fields, form) {
  const errors = {}
  fields.forEach((field) => {
    if (field.hidden?.(form)) return
    const message = validateField(field, form[field.name], form)
    if (message) errors[field.name] = message
  })
  return errors
}

/**
 * Backend xatolarini forma maydonlariga bog'laydi.
 *
 * DRF `{"field": ["xabar"]}` yoki `{"non_field_errors": [...]}` qaytaradi.
 * Maydon nomi formada bo'lmasa, xato umumiy xabarga tushadi.
 */
export function mapServerErrors(error, fieldNames = []) {
  const details = error?.fieldErrors
  const result = { fields: {}, general: [] }

  if (!details || typeof details !== 'object') {
    if (error?.userMessage) result.general.push(error.userMessage)
    return result
  }

  Object.entries(details).forEach(([key, value]) => {
    const message = Array.isArray(value) ? value.join(' ') : String(value)
    if (fieldNames.includes(key)) {
      result.fields[key] = message
    } else {
      result.general.push(key === 'non_field_errors' ? message : `${key}: ${message}`)
    }
  })

  if (!result.general.length && !Object.keys(result.fields).length && error?.userMessage) {
    result.general.push(error.userMessage)
  }
  return result
}

/**
 * Yuborish uchun payload tayyorlaydi.
 *
 * Yangilashda FAQAT o'zgargan maydonlar yuboriladi (PATCH semantikasi).
 * Bu ikki muammoni hal qiladi:
 *   1. Boshqa admin parallel o'zgartirgan maydonlarni tasodifan qaytarmaydi;
 *   2. Parol kabi "bo'sh qoldirilsa o'zgarmaydi" maydonlar to'g'ri ishlaydi.
 */
export function buildPayload(fields, form, initial = null) {
  const payload = {}

  fields.forEach((field) => {
    // `transient` — forma ichida yordamchi, modelda maydon YO'Q.
    // Masalan «Viloyat»: kompyuter viloyatga to'g'ridan-to'g'ri
    // bog'lanmaydi, u faqat binolar ro'yxatini toraytirish uchun
    // turadi. Uni yuborish serverdan "Unknown field" xatosini oladi.
    if (field.transient || field.readOnly || field.hidden?.(form)) return

    let value = form[field.name]

    // M2M tanlovi: bo'sh to'plam ham HAQIQIY qiymat — "hech narsa
    // tanlanmagan" degani, "tegilmagan" degani emas. Shuning uchun u
    // quyidagi "bo'sh ixtiyoriy maydon" mantig'iga tushmasligi kerak.
    if (Array.isArray(value)) {
      if (typeof field.transform === 'function') value = field.transform(value)
      if (initial && isSameValue(initial[field.name], value)) return
      payload[field.name] = value
      return
    }

    if (field.type === 'number') {
      value = value === '' || value === null ? null : Number(value)
    } else if (field.type === 'boolean') {
      value = Boolean(value)
    } else if (field.type === 'json' && typeof value === 'string') {
      try {
        value = value.trim() ? JSON.parse(value) : field.emptyValue ?? null
      } catch {
        return
      }
    } else if (typeof value === 'string') {
      value = value.trim()
    }

    if (typeof field.transform === 'function') value = field.transform(value)

    // Bo'sh ixtiyoriy maydon: yaratishda umuman yubormaymiz, yangilashda
    // `null` yuboramiz (tozalash niyati aniq bo'lsin).
    //
    // `null` ni ham bo'sh deb hisoblash SHART: yuqorida raqamli maydon
    // bo'sh satrdan `null` ga aylantirilgan. Buni hisobga olmaslik
    // `default=0` bo'lgan NOT NULL ustunga `null` yuborilishiga va
    // "This field may not be null" xatosiga olib keladi.
    const isBlank = value === '' || value === undefined || value === null
    if (isBlank) {
      if (!initial) return
      if (field.clearable === false) return
      value = field.nullable === false ? '' : null
    }

    if (initial && isSameValue(initial[field.name], value)) return

    payload[field.name] = value
  })

  return payload
}

/** Modeldan forma boshlang'ich qiymatlarini yig'adi. */
export function buildInitialValues(fields, row = null, defaults = {}) {
  const values = {}
  const isMulti = (field) => field.type === 'multiselect'

  fields.forEach((field) => {
    // Serializer M2M ni ikki shaklda qaytarishi mumkin: ID massivi
    // (`cameras: [1,2]`) yoki to'liq obyektlar (`permissions: [{id,…}]`).
    // `readFrom` ikkinchi holatni birinchisiga keltiradi.
    let value = row
      ? (typeof field.readFrom === 'function' ? field.readFrom(row) : row[field.name])
      : undefined

    if (value === undefined || value === null) {
      value = defaults[field.name] ?? (isMulti(field) ? [] : field.type === 'boolean' ? false : '')
    }

    if (isMulti(field) && !Array.isArray(value)) value = []

    if (field.type === 'json' && typeof value === 'object' && value !== null) {
      value = JSON.stringify(value, null, 2)
    }
    if (field.type === 'datetime' && typeof value === 'string' && value) {
      // ISO -> `datetime-local` ga mos ko'rinish (soniya va zonasiz).
      value = value.slice(0, 16)
    }
    if (field.type === 'date' && typeof value === 'string' && value) {
      value = value.slice(0, 10)
    }
    if (field.password) value = ''

    values[field.name] = value
  })
  return values
}
