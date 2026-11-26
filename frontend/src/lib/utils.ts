import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge Tailwind classes without duplicates. Prefer this in shared UI. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Display value or em-dash placeholder when metric is unavailable. */
export function metricOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}
