import { Box, Card, CardContent, Grid, Skeleton, Stack } from '@mui/material'

/**
 * Skelet ekranlar — spinner o'rniga.
 *
 * Nima uchun spinner emas: aylanuvchi indikator "qancha kutish kerak"
 * degan savolga javob bermaydi va sahifa yuklangach layout sakraydi
 * (layout shift). Skelet esa kelayotgan kontentning ANIQ shaklini
 * ko'rsatadi — foydalanuvchi ma'lumot kelishidan oldin ham sahifa
 * tuzilishini o'qiy boshlaydi va kutish qisqaroq tuyuladi.
 *
 * Har bir skelet o'zi almashtiradigan komponentning o'lchamiga mos.
 */

export function StatCardSkeleton() {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ p: 2.5 }}>
        <Stack direction="row" spacing={2} alignItems="flex-start">
          <Skeleton variant="rounded" width={44} height={44} sx={{ borderRadius: 2.5 }} />
          <Box sx={{ flex: 1 }}>
            <Skeleton width="60%" height={16} />
            <Skeleton width="45%" height={38} />
            <Skeleton width="75%" height={13} />
          </Box>
        </Stack>
      </CardContent>
    </Card>
  )
}

export function StatRowSkeleton({ count = 6 }) {
  return (
    <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
      {Array.from({ length: count }).map((_, index) => (
        <Grid item xs={6} sm={4} lg={2} key={index}>
          <StatCardSkeleton />
        </Grid>
      ))}
    </Grid>
  )
}

export function ChartSkeleton({ height = 320, bars = 7 }) {
  return (
    <Box sx={{ height, display: 'flex', alignItems: 'flex-end', gap: 1.5, px: 2, pb: 3 }}>
      {Array.from({ length: bars }).map((_, index) => (
        <Skeleton
          key={index}
          variant="rounded"
          sx={{
            flex: 1,
            // Turli balandlik — haqiqiy grafikka o'xshaydi, "yuklanmoqda"
            // holati sun'iy ko'rinmaydi.
            height: `${35 + ((index * 37) % 55)}%`,
            borderRadius: 1.5,
          }}
        />
      ))}
    </Box>
  )
}

export function TableSkeleton({ rows = 8, columns = 6, showToolbar = true }) {
  return (
    <Card>
      {showToolbar && (
        <Box sx={{ p: 2, display: 'flex', gap: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          <Skeleton variant="rounded" width={240} height={38} />
          <Box sx={{ flex: 1 }} />
          <Skeleton variant="rounded" width={110} height={38} />
        </Box>
      )}
      <Box sx={{ px: 2, py: 1.5, display: 'flex', gap: 2 }}>
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton key={index} height={14} sx={{ flex: index === 0 ? 2 : 1 }} />
        ))}
      </Box>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <Box
          key={rowIndex}
          sx={{
            px: 2, py: 1.25, display: 'flex', gap: 2, alignItems: 'center',
            borderTop: 1, borderColor: 'divider',
            // Har bir qator ketma-ket paydo bo'ladi — jonli tuyuladi.
            opacity: 1 - rowIndex * 0.06,
          }}
        >
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton key={colIndex} height={18} sx={{ flex: colIndex === 0 ? 2 : 1 }} />
          ))}
        </Box>
      ))}
    </Card>
  )
}

export function ListSkeleton({ rows = 6 }) {
  return (
    <Stack spacing={0} divider={<Box sx={{ borderBottom: 1, borderColor: 'divider' }} />}>
      {Array.from({ length: rows }).map((_, index) => (
        <Box key={index} sx={{ px: 2, py: 1.5 }}>
          <Skeleton width="55%" height={18} />
          <Skeleton width="35%" height={14} />
        </Box>
      ))}
    </Stack>
  )
}

export function DetailSkeleton() {
  return (
    <>
      <Stack direction="row" justifyContent="space-between" sx={{ mb: 3 }}>
        <Box sx={{ flex: 1 }}>
          <Skeleton width={280} height={36} />
          <Skeleton width={380} height={18} />
        </Box>
        <Stack direction="row" spacing={1}>
          <Skeleton variant="rounded" width={100} height={38} />
          <Skeleton variant="rounded" width={130} height={38} />
        </Stack>
      </Stack>
      <Grid container spacing={2.5}>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: 300 }}>
            <CardContent>
              <Skeleton width="45%" height={24} sx={{ mb: 2 }} />
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                <Skeleton variant="circular" width={64} height={64} />
                <Box sx={{ flex: 1 }}>
                  <Skeleton width="80%" height={20} />
                  <Skeleton width="55%" height={16} />
                </Box>
              </Stack>
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} height={22} sx={{ my: 1 }} />
              ))}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={8}>
          <Card sx={{ height: 300 }}>
            <CardContent>
              <Skeleton width="35%" height={24} sx={{ mb: 2 }} />
              <Grid container spacing={2}>
                {Array.from({ length: 8 }).map((_, index) => (
                  <Grid item xs={6} key={index}>
                    <Skeleton height={22} sx={{ my: 0.75 }} />
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </>
  )
}

/** Marshrut lazy-yuklanayotganda ko'rsatiladigan umumiy skelet. */
export function PageSkeleton() {
  return (
    <>
      <Box sx={{ mb: 3 }}>
        <Skeleton width={240} height={36} />
        <Skeleton width={340} height={18} />
      </Box>
      <StatRowSkeleton count={4} />
      <Box sx={{ mt: 2.5 }}>
        <TableSkeleton rows={6} />
      </Box>
    </>
  )
}
