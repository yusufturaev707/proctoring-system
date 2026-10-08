import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Chip, Skeleton } from '@mui/material'
import ApartmentIcon from '@mui/icons-material/ApartmentOutlined'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'
import VideocamIcon from '@mui/icons-material/VideocamOutlined'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'

import DetailDialog, { StatTiles } from '../data/DetailDialog'
import { dateText, Field, Section, useCopy } from '../data/DetailFields'
import { listAll } from '../data/useResource'
import { ActiveChip } from '../controls/ControlBits'
import { allowedIps as allowedIpsApi, zones as zonesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

/**
 * Bino kartasi: joylashuv, sig'im va jihozlar, binoga biriktirilgan
 * IP/tarmoqlar (qurilma ro'yxatdan o'tishda bino SHULAR orqali
 * aniqlanadi — `devices.services.resolve_zone_by_public_ip`).
 */
export default function ZoneDetailDialog({ row, onEdit, onClose }) {
  const navigate = useNavigate()
  const copy = useCopy()
  const { can } = useAuth()
  const canIps = can('controls.ip_view')
  const canDevices = can('devices.view')
  const deleted = Boolean(row.deleted_at)

  // Ro'yxat qatori eskirgan bo'lishi mumkin (boshqa admin tahrirladi).
  const { data: fresh } = useQuery({
    queryKey: ['zones', 'detail', row.id],
    queryFn: () => zonesApi.detail(row.id),
    enabled: !deleted,
  })
  const { data: ipsData, isLoading: ipsLoading } = useQuery({
    queryKey: ['allowed-ips', 'by-zone', row.id],
    queryFn: () => listAll(allowedIpsApi, { zone: row.id }),
    enabled: canIps && !deleted,
  })

  const zone = { ...row, ...(fresh || {}) }
  const ips = ipsData?.results || []
  const activeIps = ips.filter((item) => item.is_active)
  const fill = zone.capacity > 0 ? Math.round(((zone.computers_count || 0) / zone.capacity) * 100) : null

  const problems = []
  if (deleted) {
    problems.push({ severity: 'error', text: `Bino o‘chirilgan (${dateText(zone.deleted_at)}). Tiklash — jadvaldagi «Tiklash» tugmasi.` })
  } else {
    if (!zone.is_active) {
      problems.push({
        severity: 'warning',
        text: 'Bino nofaol — qurilma ro‘yxatdan o‘tishda bu bino IP orqali aniqlanmaydi.',
      })
    }
    if (canIps && ipsData && !activeIps.length) {
      problems.push({
        severity: 'warning',
        text: 'Binoga faol IP yoki tarmoq biriktirilmagan: qurilma ro‘yxatdan o‘tganda bino avtomatik aniqlanmaydi, client esa faqat umumiy (global) manzil bo‘lsa kira oladi.',
      })
    }
  }

  return (
    <DetailDialog
      icon={<ApartmentIcon />}
      tone={deleted ? 'error' : zone.is_active ? 'primary' : 'neutral'}
      title={zone.name}
      subtitle={`${zone.region_name} · bino № ${zone.number}`}
      chips={<>
        {deleted ? <Chip size="small" color="error" label="O‘chirilgan" /> : <ActiveChip active={zone.is_active} />}
        {zone.is_part && <Chip size="small" variant="outlined" label="Anklav" />}
      </>}
      problems={problems}
      onEdit={deleted ? undefined : onEdit}
      onClose={onClose}
      actions={!deleted && canDevices && <>
        <Button
          startIcon={<ComputerIcon />}
          onClick={() => navigate(`/computers?f.zone__region=${zone.region}&f.zone=${zone.id}`)}
        >
          Kompyuterlar
        </Button>
        <Button
          startIcon={<VideocamIcon />}
          onClick={() => navigate(`/cameras?f.zone__region=${zone.region}&f.zone=${zone.id}`)}
        >
          Kameralar
        </Button>
      </>}
    >
      <StatTiles
        items={[
          { label: 'Kompyuterlar', value: zone.computers_count ?? 0 },
          { label: 'Kameralar', value: zone.cameras_count ?? 0 },
          { label: 'Sig‘im, o‘rin', value: zone.capacity || '—' },
          {
            label: 'Kompyuter / sig‘im',
            value: fill == null ? '—' : `${fill}%`,
            hint: fill == null ? 'Sig‘im kiritilmagan' : '',
          },
        ]}
      />

      <Section title="Joylashuv">
        <Field icon={<PlaceIcon fontSize="small" />} label="Viloyat" value={zone.region_name} />
        <Field
          label="Bino raqami — viloyat ichida unikal (Excel import va FaceID integratsiyasi shu bo‘yicha)"
          value={zone.number}
          mono
        />
        <Field label="Manzil" value={zone.address} hint="Kiritilmagan" onCopy={copy} />
        <Field label="Bino anklavmi" value={zone.is_part ? 'Ha' : 'Yo‘q'} />
      </Section>

      {canIps && !deleted && (
        <Section title={`Ruxsat etilgan manzillar · ${ipsLoading ? '…' : ips.length}`}>
          {ipsLoading ? (
            <Box sx={{ p: 2 }}><Skeleton height={40} /></Box>
          ) : ips.length ? ips.map((item) => (
            <Field
              key={item.id}
              icon={item.ip_address ? <PublicIcon fontSize="small" /> : <LanIcon fontSize="small" />}
              label={[item.ip_address ? 'Tashqi IP' : 'Tarmoq', item.name, !item.is_active && 'o‘chiq'].filter(Boolean).join(' · ')}
              value={item.ip_address || item.network}
              mono
              onCopy={copy}
            />
          )) : (
            <Field label="IP / tarmoq" value="" hint="Biriktirilmagan — «Ruxsat etilgan IP'lar» sahifasida qo‘shing" />
          )}
        </Section>
      )}

      <Section title="Yozuv">
        <Field label="Yaratilgan" value={dateText(zone.created_at)} />
        <Field label="ID" value={zone.id} mono />
      </Section>
    </DetailDialog>
  )
}
