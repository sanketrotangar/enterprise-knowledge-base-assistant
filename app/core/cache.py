# Cache Service
# --------------
# Redis-backed caching for search results and sessions
#
# Responsibilities:
# - Cache search results (5 min TTL)
# - Invalidate cache on document update/delete
# - Store rate limit counters
# - Manage user sessions (optional)
#
# Key functions:
# - get_cached_search(query, org_id) -> dict | None
# - set_cached_search(query, org_id, results): Cache results
# - invalidate_doc_cache(doc_id): Clear cache for document
# - is_rate_limited(user_id, limit, window) -> bool
#
# Cache key format:
# - search:{org_id}:{md5(query)}
# - rate_limit:{user_id}:{window}
#
# Invalidation strategy:
# - TTL-based (5 min default)
# - Event-driven on document update/delete
# - Pattern-based deletion for document-related cache
