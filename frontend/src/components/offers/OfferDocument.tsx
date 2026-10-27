import { Box } from '@mui/material'
import type { Theme } from '@mui/material'
import type { SystemStyleObject } from '@mui/system'

/**
 * Oferta hujjati tipografiyasi — muharrir (`RichTextEditor`) va ko'rish
 * oynasi (`OfferDocument`) BITTA qoidadan.
 *
 * Ikki nusxa bo'lsa muharrirda yozilgan matn ko'rish oynasida boshqacha
 * ko'rinardi va administrator "saqlanganda buzildi" deb o'ylardi. Client
 * (Qt) o'z uslubini `client/ui/dialogs/offer_dialog.py` da shu
 * o'lchamlarga yaqin qilib beradi.
 */
export const documentSx: SystemStyleObject<Theme> = {
  color: 'text.primary',
  fontSize: 15,
  lineHeight: 1.65,
  wordBreak: 'break-word',
  '& > :first-of-type': { mt: 0 },
  '& p': { my: 1 },
  '& h1': { fontSize: 24, fontWeight: 700, lineHeight: 1.3, mt: 3, mb: 1.5 },
  '& h2': { fontSize: 20, fontWeight: 700, lineHeight: 1.35, mt: 2.5, mb: 1.25 },
  '& h3': { fontSize: 17, fontWeight: 600, lineHeight: 1.4, mt: 2, mb: 1 },
  '& h4': { fontSize: 15, fontWeight: 600, mt: 1.5, mb: 0.75 },
  '& ul, & ol': { pl: 3.5, my: 1 },
  '& li': { my: 0.25 },
  '& li > p': { my: 0.25 },
  '& blockquote': {
    m: 0, my: 1.5, py: 0.5, px: 2,
    borderLeft: 4, borderColor: 'primary.main',
    bgcolor: 'm3.surfaceContainerLow', borderRadius: '0 12px 12px 0',
    color: 'text.secondary',
  },
  '& hr': { border: 0, borderTop: 1, borderColor: 'divider', my: 2.5 },
  '& strong, & b': { fontWeight: 700 },
}

/**
 * Saqlangan oferta matni (ko'rish rejimi).
 *
 * `dangerouslySetInnerHTML` XAVFSIZ: server matnni yozishda oq ro'yxat
 * bo'yicha tozalaydi (`apps/common/html_sanitizer.py`) va bazada faqat
 * toza HTML yotadi — skript, hodisa atributi, havola o'tmaydi.
 */
export default function OfferDocument({ html }: { html: string }) {
  return (
    <Box
      sx={documentSx}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
