import { useEffect, useRef, useState } from 'react'
import { Box, Fade } from '@mui/material'
import { useLocation } from 'react-router-dom'

/**
 * Sahifalar orasidagi o'tish.
 *
 * Ataylab juda qisqa (190 ms) va faqat opacity + kichik Y siljish:
 *   - opacity brauzerda compositor'da bajariladi (GPU), layout hisoblanmaydi;
 *   - `translateY(6px)` yo'nalish hissini beradi, lekin ko'zni charchatmaydi;
 *   - kattaroq animatsiya admin panelida ishni sekinlashtiradi.
 *
 * `key={pathname}` — har bir marshrut o'z animatsiyasini oladi.
 */
export function PageTransition({ children }) {
  const location = useLocation()

  return (
    <Fade in timeout={{ enter: 190, exit: 120 }} key={location.pathname}>
      <Box
        sx={{
          animation: 'pageEnter 190ms cubic-bezier(0.2, 0.8, 0.2, 1)',
          '@keyframes pageEnter': {
            from: { transform: 'translateY(6px)' },
            to: { transform: 'translateY(0)' },
          },
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      >
        {children}
      </Box>
    </Fade>
  )
}

/**
 * Kontent almashganda "chaqnash"ning oldini oladi.
 *
 * Muammo: `isLoading` bir necha o'n millisekundga true bo'lsa, skelet
 * paydo bo'lib darhol yo'qoladi — bu chaqnash sifatida ko'rinadi va
 * sahifa "sakragan" tuyuladi.
 *
 * Yechim: skeletni faqat yuklanish `delay` dan uzoq davom etsa
 * ko'rsatamiz, va ko'rsatilgach kamida `minDuration` ushlab turamiz.
 */
export function useDeferredLoading(isLoading, { delay = 180, minDuration = 320 } = {}) {
  const [visible, setVisible] = useState(false)
  const shownAt = useRef(0)

  useEffect(() => {
    let showTimer
    let hideTimer

    if (isLoading) {
      showTimer = setTimeout(() => {
        shownAt.current = Date.now()
        setVisible(true)
      }, delay)
    } else if (visible) {
      const elapsed = Date.now() - shownAt.current
      const remaining = Math.max(0, minDuration - elapsed)
      hideTimer = setTimeout(() => setVisible(false), remaining)
    }

    return () => {
      clearTimeout(showTimer)
      clearTimeout(hideTimer)
    }
  }, [isLoading, visible, delay, minDuration])

  return visible
}

/**
 * Ro'yxat elementlarini ketma-ket paydo qiladi.
 * `index` ortishi bilan kechikish oshadi, lekin 8-elementdan keyin
 * to'xtaydi — aks holda uzun ro'yxat sekin "oqib" chiqadi.
 */
export function StaggerItem({ index = 0, children, step = 28 }) {
  return (
    <Box
      sx={{
        // Balandlikni O'TKAZIB YUBORAMIZ: bu o'ram Grid item bilan
        // kartaning orasida turadi. Usiz kartaning `height: 100%` i shu
        // `Box` ning avtomatik balandligiga tayanadi va qatordagi
        // kartalar bir xil bo'lmay qoladi.
        height: '100%',
        animation: `itemEnter 220ms cubic-bezier(0.2, 0.8, 0.2, 1) both`,
        animationDelay: `${Math.min(index, 8) * step}ms`,
        '@keyframes itemEnter': {
          from: { opacity: 0, transform: 'translateY(8px)' },
          to: { opacity: 1, transform: 'translateY(0)' },
        },
        '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
      }}
    >
      {children}
    </Box>
  )
}

/** Raqamlarni silliq o'zgartiradi (dashboard hisoblagichlari uchun). */
export function useCountUp(target = 0, duration = 420) {
  const [value, setValue] = useState(target)
  const fromRef = useRef(target)
  const frameRef = useRef()

  useEffect(() => {
    const from = fromRef.current
    const to = Number(target) || 0
    if (from === to) return undefined

    // Katta sakrash bo'lsa animatsiya qilamiz; kichik o'zgarishda darhol.
    if (Math.abs(to - from) < 2) {
      fromRef.current = to
      setValue(to)
      return undefined
    }

    const start = performance.now()
    const tick = (now) => {
      const progress = Math.min(1, (now - start) / duration)
      // easeOutCubic — oxirida sekinlashadi, tabiiy ko'rinadi.
      const eased = 1 - (1 - progress) ** 3
      setValue(Math.round(from + (to - from) * eased))
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = to
      }
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameRef.current)
  }, [target, duration])

  return value
}
