import { alpha } from '@mui/material/styles'
import { Box, ButtonBase, Card, CardContent, Stack, Tooltip, Typography } from '@mui/material'
import TrendUpIcon from '@mui/icons-material/TrendingUpOutlined'
import TrendDownIcon from '@mui/icons-material/TrendingDownOutlined'

import { useCountUp } from './motion/Transitions'
import { StatCardSkeleton } from './feedback/Skeletons'
import { Sparkline } from './charts/ChartKit'

/**
 * Ko'rsatkich kartasi.
 *
 * Interaktivlik: `onClick` berilsa karta bosiladigan bo'ladi va tegishli
 * ro'yxatga filtr bilan o'tadi. Bu dashboardni "rasm" emas, boshqaruv
 * vositasiga aylantiradi — proktor "3 ta chetlashtirilgan" ni ko'rib
 * darhol bosib, aynan o'sha uchtasini ko'radi.
 *
 * Rang faqat MA'NO tashiganda ishlatiladi. Neytral ko'rsatkich neytral
 * qoladi, aks holda ekranda nima muhimligi ajralmay qoladi.
 */
export default function StatCard({
  label,
  value,
  icon: Icon,
  color = 'primary',
  hint,
  /** Izoh bo'lmasa ham uning qatorini band qilish (yonma-yon kartalar uchun). */
  reserveHint = true,
  loading,
  onClick,
  trend,
  trendData,
  active = false,
}) {
  const animated = useCountUp(Number(value) || 0)

  if (loading) return <StatCardSkeleton />

  // NOM TEPADA, KARTANING TO'LIQ KENGLIGIDA va ikki qatorgacha
  // o'raladi; ikonka pastda, raqam qatorida. Ilgari ikonka nom yonida
  // edi: dashboardda oltita karta yonma-yon turadi va har biriga
  // ~160 px tegadi — "Chetlashtirilgan" (bitta uzun so'z, o'ralmaydi)
  // "Chetlas…" bo'lib qolardi, ya'ni raqam nimani sanayotganini faqat
  // tooltip'dan bilish mumkin edi.
  const content = (
    <CardContent sx={{ p: 2.25, width: '100%', '&:last-child': { pb: 2.25 } }}>
      <Typography
        variant="body2"
        color="text.secondary"
        fontWeight={600}
        title={typeof label === 'string' ? label : undefined}
        sx={{
          lineHeight: 1.3, minHeight: '2.6em',
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}
      >
        {label}
      </Typography>

      <Box sx={{ minWidth: 0, mt: 0.5 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Stack direction="row" spacing={1} alignItems="baseline" sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h4" sx={{ lineHeight: 1.15 }}>{animated}</Typography>
            {trend != null && trend !== 0 && (
              <Tooltip title="Kechagi kunga nisbatan">
                <Stack
                  direction="row"
                  spacing={0.25}
                  alignItems="center"
                  sx={{ color: trend > 0 ? 'warning.main' : 'success.main' }}
                >
                  {trend > 0 ? <TrendUpIcon sx={{ fontSize: 15 }} /> : <TrendDownIcon sx={{ fontSize: 15 }} />}
                  <Typography variant="caption" fontWeight={700}>
                    {Math.abs(trend)}%
                  </Typography>
                </Stack>
              </Tooltip>
            )}
            </Stack>
            {Icon && (
              <Box
                sx={{
                  width: 36, height: 36, borderRadius: '12px', flexShrink: 0,
                  display: 'grid', placeItems: 'center',
                  bgcolor: (theme) => alpha(theme.palette[color].main, 0.12),
                  color: `${color}.main`,
                }}
              >
                <Icon sx={{ fontSize: 20 }} />
              </Box>
            )}
          </Stack>

          {/*
            Izoh qatori HAR DOIM chiziladi — matni bo'lmasa ham joyi
            band qoladi. Sabab: bu kartalar bitta qatorda yonma-yon
            turadi va faqat bittasida izoh bor edi; o'sha karta bir
            qatorga baland bo'lib, qator "sinib" ko'rinardi. Bo'sh joyni
            zaxiralash raqamlarni bir sathga tekislaydi.

            `reserveHint={false}` — karta yolg'iz ishlatilsa, bu bo'sh
            joy keraksiz.
          */}
          {(hint || reserveHint) && (
            <Typography
              variant="caption"
              color="text.secondary"
              noWrap
              display="block"
              sx={{ minHeight: '1.35em' }}
            >
              {hint || ' '}
            </Typography>
          )}

          {trendData?.length > 1 && (
            <Box sx={{ mt: 1, mx: -0.5 }}>
              <Sparkline data={trendData} color={undefined} height={30} />
            </Box>
          )}
      </Box>
    </CardContent>
  )

  if (!onClick) {
    return <Card sx={{ height: '100%' }}>{content}</Card>
  }

  return (
    <Card
      sx={{
        height: '100%',
        borderColor: active ? `${color}.main` : 'divider',
        // Bosiladigan karta ko'tarilib, ko'rsatkich rangi bilan
        // ramkalanadi — "bu tugma" degan aniq signal.
        '&:hover': {
          borderColor: `${color}.main`,
          transform: 'translateY(-2px)',
          boxShadow: 3,
        },
        transition: (theme) =>
          theme.transitions.create(['transform', 'box-shadow', 'border-color'], { duration: 150 }),
      }}
    >
      <ButtonBase
        onClick={onClick}
        sx={{ width: '100%', height: '100%', textAlign: 'left', alignItems: 'stretch', borderRadius: 'inherit' }}
      >
        {content}
      </ButtonBase>
    </Card>
  )
}
