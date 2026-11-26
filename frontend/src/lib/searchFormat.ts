/**
 * Format a search score for display.
 * Cross-encoder scores are unbounded logits (e.g. 8.93, -4.92) — show two
 * decimals; they are relative rankings, not probabilities.
 */
export function formatScore(score: number): string {
  if (!Number.isFinite(score)) return '—'
  return score.toFixed(2)
}
