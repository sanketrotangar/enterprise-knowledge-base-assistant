import { useEffect, useRef, useState } from 'react'
import { usePageTitle } from '../features/usePageTitle'
import { useSearch } from '../features/useSearch'
import { Button } from '../components/ui/button'
import { Card, CardBody } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { ErrorState } from '../components/ui/states'
import { formatScore } from '../lib/searchFormat'
import type { SearchResponse } from '../types/api'

/**
 * Live Search page — the Part 3 retrieval feature.
 *
 * Flow: query box → POST /api/v1/search → answer panel (LLM, cited [n]) +
 * ranked sources. Sources link to nothing yet (document viewer is a later
 * phase); each card shows the chunk's title, position and reranker score.
 */
export function SearchPage() {
  const { setTitle } = usePageTitle('')
  useEffect(() => setTitle('Search'), [setTitle])

  const [query, setQuery] = useState('')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const searchMutation = useSearch()
  const inputRef = useRef<HTMLInputElement>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  function runSearch(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || searchMutation.isPending) return

    searchMutation.mutate(
      { query: trimmed, top_k: 5 },
      {
        onSuccess: (data) => {
          setResult(data)
          // Scroll the answer into view (mobile especially).
          requestAnimationFrame(() =>
            resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
          )
        },
      },
    )
  }

  function exportJson() {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `search-${result.query_id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const pending = searchMutation.isPending

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      {/* Query form */}
      <form onSubmit={runSearch} role="search" className="space-y-3">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="search"
            inputMode="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask the knowledge base… e.g. how many vacation days do I get?"
            aria-label="Search query"
            maxLength={500}
            className="h-10 flex-1 rounded-md border border-default bg-surface px-3 text-sm text-fg placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
          />
          <Button type="submit" loading={pending} disabled={!query.trim()}>
            {pending ? 'Searching' : 'Search'}
          </Button>
        </div>
        <p className="text-xs text-muted">
          Hybrid retrieval (semantic + keyword) → cross-encoder rerank → cited
          answer. <kbd className="rounded border border-default bg-subtle px-1">Enter</kbd> to run.
        </p>
      </form>

      {/* Error state */}
      {searchMutation.isError && (
        <Card>
          <CardBody>
            <ErrorState
              message={
                searchMutation.error instanceof Error
                  ? searchMutation.error.message
                  : 'The search pipeline failed. Check that the backend is running.'
              }
              onRetry={() => searchMutation.reset()}
            />
          </CardBody>
        </Card>
      )}

      {/* Loading skeleton */}
      {pending && (
        <div className="space-y-4" aria-live="polite" aria-busy="true">
          <Card>
            <CardBody className="space-y-3">
              <div className="h-3 w-1/3 animate-pulse rounded bg-subtle" />
              <div className="h-3 w-full animate-pulse rounded bg-subtle" />
              <div className="h-3 w-5/6 animate-pulse rounded bg-subtle" />
            </CardBody>
          </Card>
          <Card>
            <CardBody className="space-y-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 animate-pulse rounded bg-subtle" />
              ))}
            </CardBody>
          </Card>
        </div>
      )}

      {/* Results */}
      {result && !pending && (
        <div ref={resultRef} className="space-y-4">
          {/* Answer */}
          <Card>
            <CardBody className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-fg">Answer</h3>
                <div className="flex items-center gap-2">
                  <Badge className="border-default bg-subtle text-muted">
                    {result.response_time_ms} ms
                  </Badge>
                  <Button variant="ghost" size="sm" onClick={exportJson}>
                    Export JSON
                  </Button>
                </div>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
                {result.answer}
              </p>
              <p className="text-xs text-muted">
                Query id <code className="text-fg">{result.query_id}</code> — used by
                sources below show where the answer came from.
              </p>
            </CardBody>
          </Card>

          {/* Sources */}
          <section aria-label="Sources" className="space-y-3">
            <h3 className="text-sm font-semibold text-fg">
              Sources ({result.sources.length})
            </h3>
            {result.sources.map((source, index) => (
              <Card key={source.id}>
                <CardBody className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-bold text-white ${index === 0 ? 'bg-brand' : 'bg-muted'}`}
                      title="Citation number used in the answer"
                    >
                      {index + 1}
                    </span>
                    <span className="text-sm font-medium text-fg">
                      {source.document_title}
                    </span>
                    <Badge className="border-default bg-subtle text-muted">
                      chunk {source.chunk_index}
                    </Badge>
                    <Badge className="border-default bg-subtle text-muted">
                      score {formatScore(source.score)}
                    </Badge>
                  </div>
                  <p className="text-sm leading-relaxed text-muted">
                    {source.content}
                  </p>
                </CardBody>
              </Card>
            ))}
          </section>
        </div>
      )}

      {/* Empty state before first query */}
      {!result && !pending && !searchMutation.isError && (
        <Card>
          <CardBody className="flex flex-col items-center py-12 text-center">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="h-10 w-10 text-muted"
            >
              <path d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
            </svg>
            <h3 className="mt-3 text-sm font-medium text-fg">
              Ask anything about your documents
            </h3>
            <p className="mt-1 max-w-md text-sm text-muted">
              Results combine semantic and keyword matches, are reranked for
              precision, and every answer cites the chunks it was built from.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {['how many vacation days do I get?', 'sick leave notification', 'remote work approval'].map(
                (sample) => (
                  <button
                    key={sample}
                    type="button"
                    onClick={() => {
                      setQuery(sample)
                      searchMutation.mutate(
                        { query: sample, top_k: 5 },
                        {
                          onSuccess: (data) => {
                            setResult(data)
                            requestAnimationFrame(() =>
                              resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
                            )
                          },
                        },
                      )
                    }}
                    className="rounded-full border border-default bg-subtle px-3 py-1 text-xs font-medium text-muted transition-colors hover:bg-brand-light/40 hover:text-brand-dark"
                  >
                    {sample}
                  </button>
                ),
              )}
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  )
}
