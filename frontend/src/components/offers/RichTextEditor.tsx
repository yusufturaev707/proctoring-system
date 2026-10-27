import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Box, Divider, IconButton, MenuItem, TextField, Tooltip, Typography } from '@mui/material'
import BoldIcon from '@mui/icons-material/FormatBoldRounded'
import ItalicIcon from '@mui/icons-material/FormatItalicRounded'
import UnderlineIcon from '@mui/icons-material/FormatUnderlinedRounded'
import StrikeIcon from '@mui/icons-material/StrikethroughSRounded'
import BulletIcon from '@mui/icons-material/FormatListBulletedRounded'
import NumberedIcon from '@mui/icons-material/FormatListNumberedRounded'
import QuoteIcon from '@mui/icons-material/FormatQuoteRounded'
import RuleIcon from '@mui/icons-material/HorizontalRuleRounded'
import AlignLeftIcon from '@mui/icons-material/FormatAlignLeftRounded'
import AlignCenterIcon from '@mui/icons-material/FormatAlignCenterRounded'
import AlignRightIcon from '@mui/icons-material/FormatAlignRightRounded'
import AlignJustifyIcon from '@mui/icons-material/FormatAlignJustifyRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import RedoIcon from '@mui/icons-material/RedoRounded'
import ClearIcon from '@mui/icons-material/FormatClearRounded'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import TextAlign from '@tiptap/extension-text-align'
import { Placeholder } from '@tiptap/extensions'

import { documentSx } from './OfferDocument'

/**
 * Hujjat muharriri (TipTap / ProseMirror) — Material 3 asboblar paneli bilan.
 *
 * NIMA UCHUN TIPTAP. ProseMirror ustida qurilgan va "headless": hujjat
 * modeli qat'iy sxemaga ega (Word'dan nusxalangan begona teg va uslub
 * sxemaga sig'maganda tashlanadi), ko'rinish esa butunlay bizniki — panel
 * temasi (`palette.m3`) bilan bir xil. CKEditor/TinyMCE o'z UI va
 * litsenziya/kalit talablarini olib kirardi, Quill esa React 18 bilan
 * rasman qo'llab-quvvatlanmaydi.
 *
 * IMKONIYATLAR ATAYLAB CHEKLANGAN — server oq ro'yxati bilan bir xil
 * (`apps/common/html_sanitizer.py`): sarlavha, qalin/kursiv/tagiga/ustiga
 * chizilgan, ro'yxatlar, iqtibos, ajratgich, tekislash. HAVOLA, rasm,
 * jadval va kod YO'Q: client kiosk rejimida (havola tashqi brauzerga
 * olib chiqmasligi kerak) va oferta hujjati ularsiz to'liq.
 */

type BlockType = 'p' | 'h1' | 'h2' | 'h3'
type Align = 'left' | 'center' | 'right' | 'justify'

const BLOCK_OPTIONS: { value: BlockType; label: string }[] = [
  { value: 'p', label: 'Oddiy matn' },
  { value: 'h1', label: 'Sarlavha 1' },
  { value: 'h2', label: 'Sarlavha 2' },
  { value: 'h3', label: 'Sarlavha 3' },
]

const ALIGNS: { value: Align; label: string; icon: ReactNode }[] = [
  { value: 'left', label: 'Chapga', icon: <AlignLeftIcon fontSize="small" /> },
  { value: 'center', label: 'Markazga', icon: <AlignCenterIcon fontSize="small" /> },
  { value: 'right', label: 'O‘ngga', icon: <AlignRightIcon fontSize="small" /> },
  { value: 'justify', label: 'Ikki chetga', icon: <AlignJustifyIcon fontSize="small" /> },
]

interface ToolbarState {
  block: BlockType
  bold: boolean
  italic: boolean
  underline: boolean
  strike: boolean
  bulletList: boolean
  orderedList: boolean
  blockquote: boolean
  align: Align
  canUndo: boolean
  canRedo: boolean
  chars: number
  words: number
}

const EMPTY_STATE: ToolbarState = {
  block: 'p', bold: false, italic: false, underline: false, strike: false,
  bulletList: false, orderedList: false, blockquote: false, align: 'left',
  canUndo: false, canRedo: false, chars: 0, words: 0,
}

function readState(editor: Editor | null): ToolbarState {
  if (!editor) return EMPTY_STATE
  const { doc } = editor.state
  // Bloklar orasiga bo'shliq — aks holda paragraf oxiri va keyingisining
  // boshi bitta so'z bo'lib sanalardi.
  const text = doc.textBetween(0, doc.content.size, ' ', ' ')
  const level = ([1, 2, 3] as const).find((value) => editor.isActive('heading', { level: value }))
  return {
    block: level ? (`h${level}` as BlockType) : 'p',
    bold: editor.isActive('bold'),
    italic: editor.isActive('italic'),
    underline: editor.isActive('underline'),
    strike: editor.isActive('strike'),
    bulletList: editor.isActive('bulletList'),
    orderedList: editor.isActive('orderedList'),
    blockquote: editor.isActive('blockquote'),
    align: (['center', 'right', 'justify'] as const).find((value) => editor.isActive({ textAlign: value })) ?? 'left',
    canUndo: editor.can().undo(),
    canRedo: editor.can().redo(),
    chars: doc.textContent.length,
    words: text.split(/\s+/).filter(Boolean).length,
  }
}

export interface RichTextEditorProps {
  value: string
  onChange: (html: string) => void
  disabled?: boolean
  error?: boolean
  placeholder?: string
  minHeight?: number
}

export default function RichTextEditor({
  value,
  onChange,
  disabled = false,
  error = false,
  placeholder = 'Matnni shu yerga yozing yoki Word hujjatidan nusxalab qo‘ying…',
  minHeight = 380,
}: RichTextEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        // Server oq ro'yxatida yo'q — tugmasi ham, kalit birikmasi ham.
        link: false,
        code: false,
        codeBlock: false,
      }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      Placeholder.configure({ placeholder }),
    ],
    content: value || '',
    editable: !disabled,
    // Bo'sh hujjat `<p></p>` emas, bo'sh satr: forma `required` tekshiruvi
    // va "saqlanmagan o'zgarish" ogohlantirishi shunga tayanadi.
    onUpdate: ({ editor: current }) => onChange(current.isEmpty ? '' : current.getHTML()),
  })

  const state = useEditorState({ editor, selector: ({ editor: current }) => readState(current) }) ?? EMPTY_STATE

  useEffect(() => {
    editor?.setEditable(!disabled)
  }, [editor, disabled])

  // Tashqaridan kelgan qiymat (forma boshqa yozuv bilan ochildi). O'zimiz
  // yuborgan qiymat muharrirdagisi bilan teng — qayta yozilmaydi, aks
  // holda kursor har harfda hujjat boshiga sakrardi.
  useEffect(() => {
    if (!editor || editor.isFocused) return
    const current = editor.isEmpty ? '' : editor.getHTML()
    if ((value || '') !== current) editor.commands.setContent(value || '', { emitUpdate: false })
  }, [editor, value])

  const run = (command: (chain: ReturnType<Editor['chain']>) => ReturnType<Editor['chain']>) => {
    if (editor) command(editor.chain().focus()).run()
  }

  const setBlock = (block: BlockType) => {
    run((chain) => (block === 'p' ? chain.setParagraph() : chain.setHeading({ level: Number(block[1]) as 1 | 2 | 3 })))
  }

  return (
    <Box
      sx={{
        border: 1,
        borderColor: error ? 'error.main' : 'm3.outlineVariant',
        borderRadius: '16px',
        overflow: 'hidden',
        bgcolor: 'background.paper',
        transition: 'border-color 150ms, box-shadow 150ms',
        opacity: disabled ? 0.7 : 1,
        '&:hover': { borderColor: error ? 'error.main' : disabled ? 'm3.outlineVariant' : 'm3.outline' },
        // MD3 fokus: rang + qalinlik. `box-shadow` bilan — ramka qalinlashib
        // matnni 1 px surmasin.
        '&:focus-within': {
          borderColor: error ? 'error.main' : 'primary.main',
          boxShadow: (theme) => `0 0 0 1px ${error ? theme.palette.error.main : theme.palette.primary.main}`,
        },
      }}
    >
      <Box
        role="toolbar"
        aria-label="Matn formati"
        sx={{
          display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.5,
          px: 1, py: 0.75,
          bgcolor: 'm3.surfaceContainerLow',
          borderBottom: 1, borderColor: 'm3.outlineVariant',
          position: 'sticky', top: 0, zIndex: 1,
        }}
      >
        <TextField
          select
          size="small"
          value={state.block}
          onChange={(event) => setBlock(event.target.value as BlockType)}
          disabled={disabled || !editor}
          inputProps={{ 'aria-label': 'Abzats turi' }}
          sx={{
            width: 150,
            '& .MuiOutlinedInput-root': { borderRadius: '10px', bgcolor: 'background.paper', fontSize: 14 },
            '& .MuiSelect-select': { py: 0.75 },
          }}
        >
          {BLOCK_OPTIONS.map((option) => (
            <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
          ))}
        </TextField>

        <ToolbarDivider />
        <ToolButton label="Qalin" shortcut="Ctrl+B" active={state.bold} disabled={disabled}
          onClick={() => run((chain) => chain.toggleBold())}><BoldIcon fontSize="small" /></ToolButton>
        <ToolButton label="Kursiv" shortcut="Ctrl+I" active={state.italic} disabled={disabled}
          onClick={() => run((chain) => chain.toggleItalic())}><ItalicIcon fontSize="small" /></ToolButton>
        <ToolButton label="Tagiga chizilgan" shortcut="Ctrl+U" active={state.underline} disabled={disabled}
          onClick={() => run((chain) => chain.toggleUnderline())}><UnderlineIcon fontSize="small" /></ToolButton>
        <ToolButton label="Ustiga chizilgan" shortcut="Ctrl+Shift+S" active={state.strike} disabled={disabled}
          onClick={() => run((chain) => chain.toggleStrike())}><StrikeIcon fontSize="small" /></ToolButton>

        <ToolbarDivider />
        <ToolButton label="Belgili ro‘yxat" shortcut="Ctrl+Shift+8" active={state.bulletList} disabled={disabled}
          onClick={() => run((chain) => chain.toggleBulletList())}><BulletIcon fontSize="small" /></ToolButton>
        <ToolButton label="Raqamli ro‘yxat" shortcut="Ctrl+Shift+7" active={state.orderedList} disabled={disabled}
          onClick={() => run((chain) => chain.toggleOrderedList())}><NumberedIcon fontSize="small" /></ToolButton>
        <ToolButton label="Iqtibos" shortcut="Ctrl+Shift+B" active={state.blockquote} disabled={disabled}
          onClick={() => run((chain) => chain.toggleBlockquote())}><QuoteIcon fontSize="small" /></ToolButton>
        <ToolButton label="Ajratuvchi chiziq" disabled={disabled}
          onClick={() => run((chain) => chain.setHorizontalRule())}><RuleIcon fontSize="small" /></ToolButton>

        <ToolbarDivider />
        {ALIGNS.map((align) => (
          <ToolButton key={align.value} label={align.label} active={state.align === align.value} disabled={disabled}
            onClick={() => run((chain) => chain.setTextAlign(align.value))}>{align.icon}</ToolButton>
        ))}

        <ToolbarDivider />
        <ToolButton label="Formatni tozalash" disabled={disabled}
          onClick={() => run((chain) => chain.unsetAllMarks().clearNodes())}><ClearIcon fontSize="small" /></ToolButton>
        <Box sx={{ flex: 1 }} />
        <ToolButton label="Bekor qilish" shortcut="Ctrl+Z" disabled={disabled || !state.canUndo}
          onClick={() => run((chain) => chain.undo())}><UndoIcon fontSize="small" /></ToolButton>
        <ToolButton label="Qaytarish" shortcut="Ctrl+Shift+Z" disabled={disabled || !state.canRedo}
          onClick={() => run((chain) => chain.redo())}><RedoIcon fontSize="small" /></ToolButton>
      </Box>

      <Box
        sx={{
          px: { xs: 2, sm: 4 },
          py: 2.5,
          maxHeight: '58vh',
          overflowY: 'auto',
          cursor: disabled ? 'default' : 'text',
          '& .ProseMirror': {
            ...documentSx,
            minHeight,
            outline: 'none',
          },
          // Bo'sh hujjatdagi izoh (`Placeholder` kengaytmasi `data-placeholder` qo'yadi).
          '& .ProseMirror p.is-editor-empty:first-of-type::before': {
            content: 'attr(data-placeholder)',
            color: 'text.disabled',
            float: 'left',
            height: 0,
            pointerEvents: 'none',
          },
        }}
        onClick={() => editor && !editor.isFocused && !disabled && editor.commands.focus()}
      >
        <EditorContent editor={editor} />
      </Box>

      <Box
        sx={{
          display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap',
          px: 2, py: 0.75,
          borderTop: 1, borderColor: 'm3.outlineVariant',
          bgcolor: 'm3.surfaceContainerLow',
        }}
      >
        <Typography variant="caption" color="text.secondary">
          {state.words.toLocaleString('uz')} so‘z · {state.chars.toLocaleString('uz')} belgi
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" color="text.secondary">
          Word’dan nusxalanganda format saqlanadi, ortiqcha uslublar olib tashlanadi
        </Typography>
      </Box>
    </Box>
  )
}

function ToolbarDivider() {
  return <Divider orientation="vertical" flexItem sx={{ mx: 0.5, my: 0.5 }} />
}

interface ToolButtonProps {
  label: string
  shortcut?: string
  active?: boolean
  disabled?: boolean
  onClick: () => void
  children: ReactNode
}

/**
 * MD3 "standard icon button (toggle)": tanlangani — `secondaryContainer`
 * foni, holat `aria-pressed` bilan ham aytiladi (faqat rang emas).
 */
function ToolButton({ label, shortcut, active = false, disabled = false, onClick, children }: ToolButtonProps) {
  return (
    <Tooltip title={shortcut ? `${label} (${shortcut})` : label} disableInteractive>
      {/* `span` — o'chiq tugmada ham tooltip ishlashi uchun. */}
      <span>
        <IconButton
          size="small"
          aria-label={label}
          aria-pressed={active}
          disabled={disabled}
          // Bosilganda muharrir fokusini yo'qotmasin: belgilangan matn
          // tanlovi saqlanib qoladi.
          onMouseDown={(event) => event.preventDefault()}
          onClick={onClick}
          sx={{
            width: 34, height: 34, borderRadius: '10px',
            color: active ? 'm3.onSecondaryContainer' : 'text.secondary',
            bgcolor: active ? 'm3.secondaryContainer' : 'transparent',
            '&:hover': { bgcolor: active ? 'm3.secondaryContainer' : 'action.hover' },
          }}
        >
          {children}
        </IconButton>
      </span>
    </Tooltip>
  )
}
