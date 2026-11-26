import { cn } from '@/lib/utils'

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-panel-muted', className)}
      {...props}
    />
  )
}

export function StatSkeleton() {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <Skeleton className="h-3 w-16" />
      <Skeleton className="mt-3 h-7 w-20" />
    </div>
  )
}
