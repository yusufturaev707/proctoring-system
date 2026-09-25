/**
 * MJPEG oqimini (`multipart/x-mixed-replace`) `fetch` orqali o'qish.
 *
 * NIMA UCHUN `<img src>` EMAS. Brauzer `<img>` MJPEG ni o'zi o'ynatadi,
 * lekin so'rovga `Authorization` sarlavhasini qo'sha olmaydi - tokenni
 * esa URL'ga qo'yish uni brauzer tarixiga, `Referer` ga va nginx
 * log'iga chiqaradi (`api/endpoints.js:screenshotFile` bilan bir xil
 * sabab). `fetch` sarlavha qo'yadi va javob tanasini oqim sifatida
 * beradi - kadrlar shu yerda ajratiladi.
 *
 * Har qism: `--chegara`, sarlavhalar (`Content-Length`,
 * `X-Frame-Taken-At`, `X-Frame-Sent-At`), bo'sh qator, JPEG baytlari.
 * Uzunlik sarlavhadan olinadi - JPEG ichida chegara satriga o'xshash
 * baytlar bo'lishi mumkin, ya'ni chegarani qidirib kesish ishonchsiz.
 */

const CRLFCRLF = [13, 10, 13, 10]
const textDecoder = new TextDecoder('latin1')

function indexOfSequence(buffer, sequence, from = 0) {
  outer: for (let i = from; i <= buffer.length - sequence.length; i += 1) {
    for (let j = 0; j < sequence.length; j += 1) {
      if (buffer[i + j] !== sequence[j]) continue outer
    }
    return i
  }
  return -1
}

function concat(left, right) {
  if (!left.length) return right
  const merged = new Uint8Array(left.length + right.length)
  merged.set(left, 0)
  merged.set(right, left.length)
  return merged
}

const header = (head, name) => {
  const match = new RegExp(`${name}:\\s*([^\\r\\n]+)`, 'i').exec(head)
  return match ? match[1].trim() : null
}

/**
 * Oqimni o'qiydi va har kadr uchun `onFrame({ jpeg, takenAt, sentAt })`
 * chaqiradi. Server javobni yopganda (`CAMERA_LIVE_STREAM_SECONDS`)
 * oddiygina qaytadi - chaqiruvchi qayta ulanadi.
 *
 * Xatoda `Error` tashlaydi: `status` (HTTP) va odam tilidagi `message`
 * (backend konvertidagi `error.message`).
 */
export async function readMjpeg(url, { token, signal, onFrame }) {
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
    cache: 'no-store',
  })
  if (!response.ok) {
    let message = ''
    try {
      message = (await response.json())?.error?.message || ''
    } catch {
      // JSON emas - umumiy matn.
    }
    const error = new Error(message || `Xatolik (${response.status})`)
    error.status = response.status
    throw error
  }

  const reader = response.body.getReader()
  let buffer = new Uint8Array(0)
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer = concat(buffer, value)

    for (;;) {
      const headEnd = indexOfSequence(buffer, CRLFCRLF)
      if (headEnd < 0) break
      const head = textDecoder.decode(buffer.subarray(0, headEnd))
      const length = Number(header(head, 'content-length'))
      if (!length) {
        // Sarlavhasiz bo'lak (masalan oqim boshidagi bo'sh qator) - o'tkazamiz.
        buffer = buffer.slice(headEnd + 4)
        continue
      }
      const start = headEnd + 4
      if (buffer.length < start + length) break
      const jpeg = buffer.slice(start, start + length)
      buffer = buffer.slice(start + length)
      onFrame({
        jpeg,
        takenAt: Number(header(head, 'x-frame-taken-at')) || null,
        sentAt: Number(header(head, 'x-frame-sent-at')) || null,
      })
    }
  }
}
