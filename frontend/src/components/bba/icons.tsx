import { Avatar } from '@mui/material'
import { alpha } from '@mui/material/styles'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import ScreenShareIcon from '@mui/icons-material/ScreenShareOutlined'
import VideocamIcon from '@mui/icons-material/VideocamOutlined'
import DescriptionIcon from '@mui/icons-material/DescriptionOutlined'
import PdfIcon from '@mui/icons-material/PictureAsPdfOutlined'
import ZipIcon from '@mui/icons-material/FolderZipOutlined'
import PlayIcon from '@mui/icons-material/PlayCircleOutline'
import ForumIcon from '@mui/icons-material/ForumOutlined'
import ShieldIcon from '@mui/icons-material/ShieldOutlined'
import ExtensionIcon from '@mui/icons-material/ExtensionOutlined'
import CodeIcon from '@mui/icons-material/CodeOutlined'
import MemoryIcon from '@mui/icons-material/MemoryOutlined'
import VerifiedIcon from '@mui/icons-material/VerifiedUserOutlined'
import GamesIcon from '@mui/icons-material/SportsEsportsOutlined'
import BrushIcon from '@mui/icons-material/BrushOutlined'
import BoardIcon from '@mui/icons-material/DeveloperBoardOutlined'
import CubeIcon from '@mui/icons-material/ViewInArOutlined'
import SdCardIcon from '@mui/icons-material/SdCardOutlined'
import StorageIcon from '@mui/icons-material/StorageOutlined'
import UsbIcon from '@mui/icons-material/UsbOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import MonitorIcon from '@mui/icons-material/MonitorOutlined'
import KeyboardIcon from '@mui/icons-material/KeyboardOutlined'
import MouseIcon from '@mui/icons-material/MouseOutlined'
import HeadsetIcon from '@mui/icons-material/HeadsetOutlined'
import VolumeIcon from '@mui/icons-material/VolumeUpOutlined'
import FingerprintIcon from '@mui/icons-material/FingerprintOutlined'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'
import WindowsIcon from '@mui/icons-material/DesktopWindowsOutlined'
import WifiIcon from '@mui/icons-material/WifiOutlined'
import EthernetIcon from '@mui/icons-material/SettingsEthernetOutlined'
import CloudIcon from '@mui/icons-material/CloudQueueOutlined'
import InventoryIcon from '@mui/icons-material/Inventory2Outlined'
import RestartIcon from '@mui/icons-material/RestartAltOutlined'
import PowerIcon from '@mui/icons-material/PowerSettingsNewOutlined'
import LockIcon from '@mui/icons-material/LockOutlined'
import LockOpenIcon from '@mui/icons-material/LockOpenOutlined'
import TerminalIcon from '@mui/icons-material/TerminalOutlined'
import RocketIcon from '@mui/icons-material/RocketLaunchOutlined'
import DownloadIcon from '@mui/icons-material/DownloadOutlined'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import EditIcon from '@mui/icons-material/EditOutlined'
import TouchIcon from '@mui/icons-material/TouchAppOutlined'
import UpdateIcon from '@mui/icons-material/SystemUpdateAltOutlined'
import DeleteForeverIcon from '@mui/icons-material/DeleteForeverOutlined'
import AppsIcon from '@mui/icons-material/AppsOutlined'
import type { ComponentType } from 'react'
import type { SvgIconProps } from '@mui/material'

type Icon = ComponentType<SvgIconProps>

/**
 * Dastur ikonkasi — NOM BO'YICHA. Console inventory'sida dasturning
 * haqiqiy ikonkasi yo'q (`InstalledSoftware` — faqat `name`, `version`,
 * `scope`), shuning uchun turi va brend rangi nomdan aniqlanadi; tanilmagani
 * — bosh harf, rangi nomdan (bir dastur har doim bir xil rangda).
 *
 * `risk` — imtihon kompyuterida bo'lmasligi kerak bo'lgan turlar (masofaviy
 * boshqaruv, ekran yozish, o'yin): ro'yxatda ajratib ko'rsatiladi.
 * Tartib muhim — birinchi mos qoida.
 */
export interface AppKind {
  icon: Icon
  color: string
  category: string
  risk?: boolean
}

const APP_RULES: [RegExp, AppKind][] = [
  [/anydesk|rustdesk|teamviewer|radmin|ultravnc|tightvnc|realvnc|vnc (server|viewer)|ammyy|chrome remote desktop|supremo|aeroadmin|litemanager|splashtop|parsec|dwservice|meshagent/i,
    { icon: ScreenShareIcon, color: '#D32F2F', category: 'Masofaviy boshqaruv', risk: true }],
  [/obs studio|bandicam|camtasia|fraps|sharex|screen ?recorder|action!/i,
    { icon: VideocamIcon, color: '#7B1FA2', category: 'Ekran yozish', risk: true }],
  [/steam|epic games|battle\.net|riot|minecraft|counter-strike/i,
    { icon: GamesIcon, color: '#37474F', category: 'O‘yin', risk: true }],
  [/proctoring|bba agent|bba console/i, { icon: VerifiedIcon, color: '#1565C0', category: 'Proktoring' }],
  [/google chrome|chromium/i, { icon: PublicIcon, color: '#4285F4', category: 'Brauzer' }],
  [/firefox/i, { icon: PublicIcon, color: '#FF7139', category: 'Brauzer' }],
  [/microsoft edge/i, { icon: PublicIcon, color: '#0C8CE9', category: 'Brauzer' }],
  [/yandex/i, { icon: PublicIcon, color: '#FC3F1D', category: 'Brauzer' }],
  [/opera/i, { icon: PublicIcon, color: '#FF1B2D', category: 'Brauzer' }],
  [/brave|vivaldi|tor browser/i, { icon: PublicIcon, color: '#FB542B', category: 'Brauzer' }],
  [/acrobat|pdf|foxit|sumatra/i, { icon: PdfIcon, color: '#E2231A', category: 'PDF' }],
  [/microsoft (office|365)|\bword\b|\bexcel\b|powerpoint|outlook|onenote/i,
    { icon: DescriptionIcon, color: '#D83B01', category: 'Ofis' }],
  [/libreoffice|openoffice|wps office|onlyoffice/i, { icon: DescriptionIcon, color: '#18A303', category: 'Ofis' }],
  [/7-zip|winrar|winzip|peazip|bandizip/i, { icon: ZipIcon, color: '#795548', category: 'Arxiv' }],
  [/vlc|k-lite|media player|aimp|potplayer|kmplayer|codec/i, { icon: PlayIcon, color: '#FF8800', category: 'Media' }],
  [/telegram|whatsapp|viber|skype|zoom|discord|microsoft teams|imo\b/i,
    { icon: ForumIcon, color: '#229ED9', category: 'Muloqot' }],
  [/kaspersky|eset|avast|\bavg\b|defender|malwarebytes|dr\.?web|bitdefender|norton|mcafee|360 total/i,
    { icon: ShieldIcon, color: '#2E7D32', category: 'Antivirus' }],
  [/photoshop|illustrator|coreldraw|gimp|paint\.net|inkscape|figma/i, { icon: BrushIcon, color: '#00A0E9', category: 'Grafika' }],
  [/visual studio|vs ?code|\bgit\b|notepad\+\+|pycharm|intellij|sublime|android studio/i,
    { icon: CodeIcon, color: '#007ACC', category: 'Dasturlash' }],
  [/visual c\+\+|\.net|redistributable|runtime|directx|\bjava\b|python|node\.?js|vcredist|webview2|update health/i,
    { icon: ExtensionIcon, color: '#607D8B', category: 'Kutubxona' }],
  [/nvidia|intel|realtek|\bamd\b|radeon|driver|chipset|synaptics|elan/i,
    { icon: MemoryIcon, color: '#546E7A', category: 'Drayver' }],
]

export function appKind(name: unknown): AppKind | null {
  const text = String(name || '')
  for (const [pattern, kind] of APP_RULES) if (pattern.test(text)) return kind
  return null
}

function hashHue(text: string): number {
  let hash = 0
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) % 360
  return hash
}

export function AppIcon({ name, size = 36 }: { name: unknown; size?: number }) {
  const kind = appKind(name)
  if (kind) {
    const Glyph = kind.icon
    return (
      <Avatar
        variant="rounded"
        sx={{ width: size, height: size, borderRadius: '10px', bgcolor: alpha(kind.color, 0.14), color: kind.color }}
      >
        <Glyph sx={{ fontSize: size * 0.58 }} />
      </Avatar>
    )
  }
  const text = String(name || '?').trim()
  const hue = hashHue(text)
  return (
    <Avatar
      variant="rounded"
      sx={{
        width: size, height: size, borderRadius: '10px', fontSize: size * 0.42, fontWeight: 700,
        bgcolor: `hsl(${hue} 70% 92%)`, color: `hsl(${hue} 55% 32%)`,
      }}
    >
      {text ? text.charAt(0).toUpperCase() : <AppsIcon fontSize="small" />}
    </Avatar>
  )
}

/** Hardware qatori turi -> ikonka (`InventoryPanels.HardwarePanel`). */
export const HARDWARE_ICON: Record<string, Icon> = {
  cpu: MemoryIcon,
  motherboard: BoardIcon,
  gpu: CubeIcon,
  ram: SdCardIcon,
  disk: StorageIcon,
  external: UsbIcon,
  network_disks: LanIcon,
  monitors: MonitorIcon,
  keyboards: KeyboardIcon,
  mice: MouseIcon,
  cameras: VideocamIcon,
  headsets: HeadsetIcon,
  audio_devices: VolumeIcon,
}

/** Hardware ID turi -> ikonka. */
export const ID_ICON: Record<string, Icon> = {
  uuid: FingerprintIcon,
  serial: FingerprintIcon,
  tpm: KeyIcon,
  windows: WindowsIcon,
  cpu: MemoryIcon,
  disk: StorageIcon,
  ram: SdCardIcon,
  nic: LanIcon,
  monitor: MonitorIcon,
}

/** Tarmoq adapteri turi — nomidan (Windows adapter nomi). */
export function adapterIcon(name: unknown): { icon: Icon; label: string } {
  const text = String(name || '')
  if (/wi-?fi|wireless|wlan|802\.11/i.test(text)) return { icon: WifiIcon, label: 'Wi-Fi' }
  if (/vethernet|virtual|vmware|hyper-v|virtualbox|loopback|vpn|tap-|tunnel|wsl|docker|bluetooth/i.test(text)) {
    return { icon: CloudIcon, label: 'Virtual' }
  }
  return { icon: EthernetIcon, label: 'Ethernet' }
}

/** Job turi -> ikonka (`apps/bba/jobs.py` katalogi bilan bir xil kodlar). */
export const JOB_ICON: Record<string, Icon> = {
  collect_inventory: InventoryIcon,
  restart_computer: RestartIcon,
  shutdown_computer: PowerIcon,
  lock_system: LockIcon,
  unlock_system: LockOpenIcon,
  run_script: TerminalIcon,
  manage_startup_app: RocketIcon,
  install_software: DownloadIcon,
  uninstall_software: DeleteIcon,
  rename_computer: EditIcon,
  run_interactive: TouchIcon,
  update_agent: UpdateIcon,
  uninstall_agent: DeleteForeverIcon,
}

export function JobIcon({ type, size = 32 }: { type: string; size?: number }) {
  const Glyph = JOB_ICON[type] || TerminalIcon
  return (
    <Avatar
      variant="rounded"
      sx={{ width: size, height: size, borderRadius: '10px', bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer' }}
    >
      <Glyph sx={{ fontSize: size * 0.56 }} />
    </Avatar>
  )
}
