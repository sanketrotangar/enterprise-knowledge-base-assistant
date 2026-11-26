/// <reference types="vite/client" />

// Ambient declarations for Vite environment variables (see .env.example).
interface ImportMetaEnv {
  /** Base URL of the FastAPI backend when NOT using the Vite proxy. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
