/**
 * Typed access to Vite environment variables.
 * Ambient types live in src/vite-env.d.ts; all flags are optional.
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
