import { useState } from 'react'
import { alpha, useTheme } from '@mui/material/styles'
import { Box, Card, CardContent, CardHeader, Stack, Typography } from '@mui/material'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ChartSkeleton } from '../feedback/Skeletons'
import { EmptyState } from '../feedback/States'

/**
 * Grafik komponentlari.
 *
 * Interaktivlik tamoyillari:
 *   - Hover'da faqat shu element yorqin qoladi, qolganlari xiralashadi
 *     (focus+context). Bu ko'zni kerakli joyga yo'naltiradi.
 *   - Bosilganda drill-down: filtr qo'llanadi yoki tegishli sahifaga o'tadi.
 *   - Tooltip har doim aniq son va ulush foizini ko'rsatadi — foydalanuvchi
 *     ustun balandligini "chamalab" o'lchamasligi kerak.
 */

function ChartTooltip({ active, payload, label, total, unit = '' }) {
  const theme = useTheme()
  if (!active || !payload?.length) return null

  return (
    <Box
      sx={{
        bgcolor: 'background.paper',
        border: 1,
        borderColor: 'divider',
        borderRadius: 2,
        boxShadow: 4,
        px: 1.75,
        py: 1.25,
        minWidth: 160,
      }}
    >
      {label != null && (
        <Typography variant="caption" color="text.secondary" fontWeight={600}>
          {label}
        </Typography>
      )}
      {payload.map((entry) => {
        const value = entry.value ?? 0
        const share = total ? Math.round((value / total) * 100) : null
        return (
          <Stack
            key={entry.dataKey || entry.name}
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{ mt: 0.5 }}
          >
            <Box
              sx={{
                width: 10, height: 10, borderRadius: '3px', flexShrink: 0,
                bgcolor: entry.color || entry.payload?.fill || theme.palette.primary.main,
              }}
            />
            <Typography variant="body2" sx={{ flex: 1 }}>
              {entry.name || entry.payload?.name}
            </Typography>
            <Typography variant="body2" fontWeight={700}>
              {value}{unit}
            </Typography>
            {share != null && (
              <Typography variant="caption" color="text.secondary">
                {share}%
              </Typography>
            )}
          </Stack>
        )
      })}
    </Box>
  )
}

/** Grafik uchun umumiy karta: sarlavha, yuklanish, bo'sh holat. */
export function ChartCard({ title, subheader, action, loading, isEmpty, emptyText, height = 320, children }) {
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardHeader title={title} subheader={subheader} action={action} />
      <CardContent sx={{ flex: 1, pt: 0, '&:last-child': { pb: 2 } }}>
        {loading ? (
          <ChartSkeleton height={height} />
        ) : isEmpty ? (
          // Bo'sh holat telefonda PAST: grafik uchun ajratilgan 330 px
          // ichida bitta ikonka ekranning yarmini bo'sh egallardi.
          <Box sx={{ height: { xs: 180, md: height }, display: 'grid', placeItems: 'center' }}>
            <EmptyState title={emptyText || 'Ma’lumot yo‘q'} dense />
          </Box>
        ) : (
          <Box sx={{ height }}>{children}</Box>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Gorizontal ustunli diagramma.
 *
 * Gorizontal (vertikal emas) ataylab: turkum nomlari uzun bo'lsa
 * («Masofaviy boshqaruv aniqlandi»), vertikal ustunlarda ular
 * qiyshaytiriladi va o'qib bo'lmaydi.
 */
export function RankedBarChart({ data, onSelect, valueKey = 'count', height = 320, unit = '' }) {
  const theme = useTheme()
  const [hovered, setHovered] = useState(null)
  const total = data.reduce((sum, item) => sum + (item[valueKey] || 0), 0)

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ left: 8, right: 24, top: 4, bottom: 4 }}
        onMouseLeave={() => setHovered(null)}
      >
        <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={theme.chart.grid} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: theme.chart.axis }} axisLine={false} tickLine={false} />
        <YAxis
          dataKey="name"
          type="category"
          width={150}
          tick={{ fontSize: 12, fill: theme.chart.axis }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={{ fill: alpha(theme.palette.primary.main, 0.06) }}
          content={<ChartTooltip total={total} unit={unit} />}
        />
        <Bar
          dataKey={valueKey}
          name="Soni"
          radius={[0, 6, 6, 0]}
          maxBarSize={26}
          onClick={(entry) => onSelect?.(entry)}
          cursor={onSelect ? 'pointer' : 'default'}
        >
          {data.map((entry, index) => (
            <Cell
              key={entry.name}
              fill={entry.color || theme.chart.colors[index % theme.chart.colors.length]}
              // Focus + context: sichqoncha ustidagi ustun to'liq,
              // qolganlari 35% shaffof.
              fillOpacity={hovered === null || hovered === index ? 1 : 0.35}
              onMouseEnter={() => setHovered(index)}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Halqa diagramma — markazda umumiy son. */
export function DonutChart({ data, onSelect, height = 320, centerLabel = 'Jami' }) {
  const theme = useTheme()
  const [activeIndex, setActiveIndex] = useState(null)
  const total = data.reduce((sum, item) => sum + (item.value || 0), 0)
  const active = activeIndex != null ? data[activeIndex] : null

  return (
    <Box sx={{ position: 'relative', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="60%"
            outerRadius="86%"
            paddingAngle={2}
            stroke="none"
            onMouseEnter={(_, index) => setActiveIndex(index)}
            onMouseLeave={() => setActiveIndex(null)}
            onClick={(entry) => onSelect?.(entry)}
            cursor={onSelect ? 'pointer' : 'default'}
          >
            {data.map((entry, index) => (
              <Cell
                key={entry.name}
                fill={entry.color || theme.chart.colors[index % theme.chart.colors.length]}
                fillOpacity={activeIndex === null || activeIndex === index ? 1 : 0.35}
              />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip total={total} />} />
        </PieChart>
      </ResponsiveContainer>

      {/* Markazdagi raqam: hover'da tanlangan segment, aks holda jami. */}
      <Stack
        alignItems="center"
        sx={{
          position: 'absolute', inset: 0, justifyContent: 'center',
          pointerEvents: 'none', textAlign: 'center', px: 4,
        }}
      >
        <Typography variant="h4" sx={{ lineHeight: 1 }}>
          {active ? active.value : total}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
          {active ? active.name : centerLabel}
        </Typography>
      </Stack>

      <Stack direction="row" flexWrap="wrap" justifyContent="center" gap={1.5} sx={{ mt: 1 }}>
        {data.map((entry, index) => (
          <Stack
            key={entry.name}
            direction="row"
            spacing={0.75}
            alignItems="center"
            onMouseEnter={() => setActiveIndex(index)}
            onMouseLeave={() => setActiveIndex(null)}
            onClick={() => onSelect?.(entry)}
            sx={{
              cursor: onSelect ? 'pointer' : 'default',
              opacity: activeIndex === null || activeIndex === index ? 1 : 0.45,
              transition: (t) => t.transitions.create('opacity', { duration: 120 }),
            }}
          >
            <Box
              sx={{
                width: 9, height: 9, borderRadius: '3px',
                bgcolor: entry.color || theme.chart.colors[index % theme.chart.colors.length],
              }}
            />
            <Typography variant="caption">{entry.name}</Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  )
}

/** Kichik trend chizig'i — stat kartalar ichida. */
export function Sparkline({ data, color, height = 36, dataKey = 'value' }) {
  const theme = useTheme()
  const stroke = color || theme.palette.primary.main
  const gradientId = `spark-${dataKey}-${stroke.replace('#', '')}`

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey={dataKey}
          stroke={stroke}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          isAnimationActive={false}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
