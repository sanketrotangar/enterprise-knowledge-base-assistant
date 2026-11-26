import type { DocumentStatus, SensitivityLevel } from '../types/api'

/** Tailwind classes per document status — icon + text always accompany color (a11y). */
export const STATUS_STYLES: Record<
  DocumentStatus,
  { label: string; badgeClass: string; dotClass: string }
> = {
  pending: {
    label: 'Pending',
    badgeClass: 'bg-warning-bg text-warning-text border-warning-border',
    dotClass: 'bg-amber-500 animate-pulse',
  },
  ready: {
    label: 'Ready',
    badgeClass: 'bg-success-bg text-success-text border-success-border',
    dotClass: 'bg-emerald-500',
  },
  failed: {
    label: 'Failed',
    badgeClass: 'bg-danger-bg text-danger-text border-danger-border',
    dotClass: 'bg-red-500',
  },
}

export const SENSITIVITY_LABELS: Record<SensitivityLevel, string> = {
  public: 'Public',
  internal: 'Internal',
  confidential: 'Confidential',
  restricted: 'Restricted',
}
