import { BeakerIcon } from '../icons'

interface ComingSoonProps {
  title: string
  /** Which backend phase will unlock this page (helps set expectations). */
  phase: string
}

/** Full-page placeholder for features whose backend phase hasn't landed. */
export function ComingSoon({ title, phase }: ComingSoonProps) {
  return (
    <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      <div className="rounded-lg border border-dashed border-strong bg-surface px-6 py-14 text-center">
        <BeakerIcon className="mx-auto h-10 w-10 text-muted" />
        <h2 className="mt-4 text-lg font-semibold text-fg">{title}</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted">
          This section is part of an upcoming phase of the platform. The API
          contracts are already wired in the frontend — it will light up as
          soon as the backend endpoints are available.
        </p>
        <p className="mt-4 inline-flex items-center rounded-full border border-default bg-subtle px-3 py-1 text-xs font-medium text-muted">
          {phase}
        </p>
      </div>
    </div>
  )
}
