import { Chip, Typography } from '@mui/material'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'

import DetailDialog, { InfoNote } from '../data/DetailDialog'
import { dateText, Field, Section, useCopy } from '../data/DetailFields'
import { ActiveChip } from './ControlBits'

const ipToInt = (ip) => ip.split('.').reduce((acc, part) => (acc * 256) + Number(part), 0)
const intToIp = (value) => [24, 16, 8, 0].map((shift) => Math.floor(value / 2 ** shift) % 256).join('.')

/**
 * IPv4 tarmoq: diapazon va manzillar soni. IPv6 yoki buzilgan qiymatda
 * `null` (karta faqat prefiksni ko'rsatadi). Bitli operatorlar EMAS —
 * JS da ular 32-bit ishorali va /1 tarmoqda manfiy son berardi.
 */
export function cidrInfo(network) {
  const match = /^(\d{1,3}(?:\.\d{1,3}){3})\/(\d{1,2})$/.exec(String(network || ''))
  if (!match) return null
  const prefix = Number(match[2])
  if (prefix > 32) return null
  const size = 2 ** (32 - prefix)
  const first = Math.floor(ipToInt(match[1]) / size) * size
  return { prefix, size, first: intToIp(first), last: intToIp(first + size - 1) }
}

/**
 * Ruxsat etilgan manzil kartasi: nima (IP yoki tarmoq, diapazon), qayerga
 * bog'langan va bu bog'lanish nimani anglatadi — bino aniqlanadimi yo'qmi.
 */
export default function AllowedIpDetailDialog({ row, onEdit, onClose }) {
  const copy = useCopy()
  const isNetwork = !row.ip_address
  const address = row.ip_address || row.network
  const cidr = isNetwork ? cidrInfo(row.network) : null
  const global = !row.zone

  const problems = []
  if (!row.is_active) {
    problems.push({
      severity: 'warning',
      text: 'Yozuv o‘chiq — bu manzildan kelgan client rad etiladi (boshqa faol yozuv mos kelmasa).',
    })
  }
  if (global) {
    problems.push({
      severity: 'info',
      text: 'Bino biriktirilmagan: manzil barcha binolar uchun ochiq, lekin qurilma ro‘yxatdan o‘tishda bino shu manzil orqali ANIQLANMAYDI.',
    })
  }

  return (
    <DetailDialog
      icon={isNetwork ? <LanIcon /> : <PublicIcon />}
      tone={row.is_active ? 'primary' : 'neutral'}
      title={<Typography component="span" variant="h6" sx={{ fontFamily: 'monospace' }}>{address}</Typography>}
      subtitle={row.name || 'Nomsiz yozuv'}
      chips={<>
        <ActiveChip active={row.is_active} on="Faol" off="O‘chiq" />
        <Chip size="small" variant="outlined" label={isNetwork ? `Tarmoq /${cidr?.prefix ?? '?'}` : 'Tashqi IP'} />
        {global
          ? <Chip size="small" color="warning" variant="outlined" label="Global — barcha binolar" />
          : <Chip size="small" variant="outlined" icon={<PlaceIcon />} label={row.zone_name} />}
      </>}
      problems={problems}
      onEdit={onEdit}
      onClose={onClose}
      maxWidth="sm"
    >
      <Section title="Manzil">
        <Field
          label="Turi"
          value={isNetwork
            ? 'Tarmoq (CIDR) — server bino ichida yoki binolar VPN orqali ulangan'
            : 'Tashqi (NAT) IP — bino server bilan internet orqali ulanadi'}
        />
        <Field label={isNetwork ? 'Tarmoq' : 'IP manzil'} value={address} mono onCopy={copy} />
        {cidr && (
          <>
            <Field label="Diapazon" value={`${cidr.first} – ${cidr.last}`} mono />
            <Field label="Manzillar soni" value={`${cidr.size.toLocaleString('ru-RU')} ta`} />
          </>
        )}
      </Section>

      <Section title="Bog‘lanish">
        <Field label="Viloyat" value={row.region_name} hint="—" />
        <Field label="Bino" value={row.zone_name} hint="Biriktirilmagan (global)" />
        <Field
          label="Qurilma ro‘yxatdan o‘tganda"
          value={global
            ? 'Bino aniqlanmaydi — kompyuter IP bo‘yicha qidirilmaydi'
            // `resolve_zone_by_public_ip` nofaol/o'chirilgan binoni qaytarmaydi.
            : `Bino avtomatik aniqlanadi: «${row.zone_name}» (bino faol bo‘lsa)`}
        />
      </Section>

      <InfoNote icon={<InfoIcon fontSize="small" />}>
        Client imtihon markazidan ulanayotganini server shu ro‘yxat bo‘yicha tekshiradi — uydan
        ulangan client JSHSHIR qidiruviga kira olmaydi. Aniq IP tarmoqdan ustun; tarmoqlar o‘zaro
        kesishmaydi, ya’ni manzil hech qachon ikki binoga tegishli bo‘lib qolmaydi.
      </InfoNote>

      <Section title="Yozuv">
        <Field label="Qo‘shilgan" value={dateText(row.created_at)} />
        <Field label="ID" value={row.id} mono />
      </Section>
    </DetailDialog>
  )
}
