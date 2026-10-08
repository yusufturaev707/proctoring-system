import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Chip, Skeleton, Stack, Tooltip, Typography } from '@mui/material'
import MapIcon from '@mui/icons-material/MapOutlined'
import ApartmentIcon from '@mui/icons-material/ApartmentOutlined'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'
import WarningIcon from '@mui/icons-material/WarningAmberOutlined'

import DetailDialog, { StatTiles } from '../data/DetailDialog'
import { dateText, Field, Section } from '../data/DetailFields'
import { listAll } from '../data/useResource'
import { ActiveChip } from '../controls/ControlBits'
import { allowedIps as allowedIpsApi, zones as zonesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

const fmt = (value) => (value == null ? null : value.toLocaleString('ru-RU'))

/**
 * Viloyat kartasi: identifikatorlar, binolari va ularning jami
 * (kompyuter, kamera, sig'im) hamda qaysi binoga IP/tarmoq
 * biriktirilmagani. Binolar `listAll` bilan — viloyatda 50 dan ortiq
 * bino bo'lsa ham jami to'g'ri chiqsin (bitta sahifa jimgina kesardi).
 */
export default function RegionDetailDialog({ row, onEdit, onClose }) {
  const navigate = useNavigate()
  const { can } = useAuth()
  const canIps = can('controls.ip_view')
  const canDevices = can('devices.view')

  const { data: zonesData, isLoading } = useQuery({
    queryKey: ['zones', 'by-region', row.id],
    queryFn: () => listAll(zonesApi, { region: row.id }),
  })
  const { data: ipsData } = useQuery({
    queryKey: ['allowed-ips', 'by-region', row.id],
    queryFn: () => listAll(allowedIpsApi, { zone__region: row.id }),
    enabled: canIps,
  })

  const zones = useMemo(() => zonesData?.results || [], [zonesData])
  const zonesWithIp = useMemo(
    () => new Set((ipsData?.results || []).filter((item) => item.is_active).map((item) => item.zone)),
    [ipsData],
  )
  const totals = useMemo(() => zones.reduce(
    (acc, zone) => ({
      computers: acc.computers + (zone.computers_count || 0),
      cameras: acc.cameras + (zone.cameras_count || 0),
      capacity: acc.capacity + (zone.capacity || 0),
      active: acc.active + (zone.is_active ? 1 : 0),
    }),
    { computers: 0, cameras: 0, capacity: 0, active: 0 },
  ), [zones])
  const withoutIp = canIps && ipsData ? zones.filter((zone) => zone.is_active && !zonesWithIp.has(zone.id)) : []

  const problems = []
  if (!isLoading && zones.length === 0) {
    problems.push({ severity: 'info', text: 'Bu viloyatda hali bino yo‘q — kompyuter va kameralar binoga biriktiriladi.' })
  }
  if (withoutIp.length) {
    problems.push({
      severity: 'warning',
      text: `${withoutIp.length} ta faol binoga IP yoki tarmoq biriktirilmagan — u yerda qurilma ro‘yxatdan o‘tganda bino avtomatik aniqlanmaydi.`,
    })
  }

  return (
    <DetailDialog
      icon={<MapIcon />}
      tone={row.is_active ? 'primary' : 'neutral'}
      title={row.name}
      subtitle={`DTM ID ${row.dtm_id} · VM raqami ${row.vm_number}`}
      chips={<>
        <ActiveChip active={row.is_active} />
        {row.is_have_part && <Chip size="small" variant="outlined" label="Bo‘linmalari bor" />}
      </>}
      problems={problems}
      onEdit={onEdit}
      onClose={onClose}
      actions={<>
        <Button startIcon={<ApartmentIcon />} onClick={() => navigate(`/zones?f.region=${row.id}`)}>
          Binolar
        </Button>
        {canDevices && (
          <Button startIcon={<ComputerIcon />} onClick={() => navigate(`/computers?f.zone__region=${row.id}`)}>
            Kompyuterlar
          </Button>
        )}
      </>}
    >
      <StatTiles
        items={[
          { label: 'Binolar', value: isLoading ? null : fmt(zones.length), hint: isLoading ? '' : `${totals.active} tasi faol` },
          { label: 'Kompyuterlar', value: isLoading ? null : fmt(totals.computers) },
          { label: 'Kameralar', value: isLoading ? null : fmt(totals.cameras) },
          { label: 'Sig‘im, o‘rin', value: isLoading ? null : fmt(totals.capacity) },
        ]}
      />

      <Section title="Identifikatorlar">
        <Field
          label="DTM ID — tashqi tizimdagi raqam (Excel import va FaceID integratsiyasi shu bo‘yicha)"
          value={row.dtm_id}
          mono
        />
        <Field label="VM raqami" value={row.vm_number} mono />
        <Field label="Bo‘linmalari bor" value={row.is_have_part ? 'Ha' : 'Yo‘q'} />
      </Section>

      <Section title={`Binolar · ${isLoading ? '…' : zones.length}`}>
        {isLoading ? (
          <Box sx={{ p: 2 }}><Skeleton height={40} /><Skeleton height={40} /></Box>
        ) : zones.length ? (
          <Box sx={{ maxHeight: 360, overflowY: 'auto' }}>
            {zones.map((zone) => (
              <Stack
                key={zone.id}
                direction="row"
                spacing={1.5}
                alignItems="center"
                sx={{ px: 2, py: 1.25, '& + &': { borderTop: 1, borderColor: 'divider' } }}
              >
                <Box
                  sx={{
                    minWidth: 36, height: 28, px: 0.75, borderRadius: '8px', flexShrink: 0,
                    display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 700,
                    bgcolor: zone.is_active ? 'm3.secondaryContainer' : 'm3.surfaceContainerHighest',
                    color: zone.is_active ? 'm3.onSecondaryContainer' : 'text.disabled',
                  }}
                >
                  {zone.number}
                </Box>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" fontWeight={600} noWrap color={zone.is_active ? 'text.primary' : 'text.secondary'}>
                    {zone.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" noWrap display="block">
                    {`${zone.computers_count || 0} PC · ${zone.cameras_count || 0} kamera`}
                    {zone.capacity ? ` · ${zone.capacity} o‘rin` : ''}
                    {zone.address ? ` · ${zone.address}` : ''}
                  </Typography>
                </Box>
                {!zone.is_active && <Chip size="small" variant="outlined" label="Nofaol" />}
                {canIps && ipsData && zone.is_active && !zonesWithIp.has(zone.id) && (
                  <Tooltip title="Binoga faol IP/tarmoq biriktirilmagan — bino avtomatik aniqlanmaydi">
                    <WarningIcon fontSize="small" color="warning" />
                  </Tooltip>
                )}
              </Stack>
            ))}
          </Box>
        ) : (
          <Field label="Binolar" value="" hint="Hali bino qo‘shilmagan" />
        )}
      </Section>

      <Section title="Yozuv">
        <Field label="Yaratilgan" value={dateText(row.created_at)} />
        <Field label="ID" value={row.id} mono />
      </Section>
    </DetailDialog>
  )
}
