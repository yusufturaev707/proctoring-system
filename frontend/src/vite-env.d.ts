/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend manzili. Bo'sh — sahifaning o'z manzili (production, nginx). */
  readonly VITE_API_URL?: string
  /** WebSocket manzili. Bo'sh — API manzilidan chiqariladi. */
  readonly VITE_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
