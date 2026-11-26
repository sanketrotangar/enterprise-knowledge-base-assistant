Groq switch is done. Now the two explanations you asked for.

2. The step-by-step story (simple language)

a data-flow walkthrough — following one item through every stage of the system. Drawn as a diagram it's called a Data Flow Diagram (DFD); narrated stage-by-stage it's often called a request-lifecycle trace or "trace walkthrough." So: "I gave you a data-flow walkthrough of the request lifecycle."

Stage A — Upload (Part 1)

1. You pick a file in the frontend → browser packs the file + title + sensitivity + role tags into one request →  POST /api/v1/documents/upload .
2. The router (receptionist) only checks the request shape, then hands it to the service (the kitchen).
3. Validation: extension allowed (pdf/txt/md)? content-type sane? Then the file is streamed to disk in 1 MB pieces while counting size — if it crosses the limit mid-way, writing stops and the partial file is deleted. (Size is measured, not trusted from headers — headers can lie.)
4. Identity: "whose document is this?" — no login exists yet, so a default dev org + user is created once and reused.
5. Metadata saved to Postgres ( documents  table): title, disk path, size, sensitivity, role tags, and  status = 'uploaded' . Postgres is the ledger — it always knows what exists.
6. Pipeline starts in a background thread so the web server stays free for other requests.

Stage B — The ingestion pipeline (the cooking)

7. Parse: text is pulled out of the file (pypdf for PDFs). Empty text → document marked  failed .
8. Chunk: text cut into ~320-word overlapping windows, snapping to sentence ends. Why: models can only read ~512 tokens at once, and overlap stops a fact split across a boundary from being lost.
9. Contextualize (the "contextual RAG" step): each chunk alone is ambiguous ("this applies to them" — who?). So each chunk is sent to Groq: "here's the document title + beginning, here's the chunk — write 2–3 sentences situating it." No key or Groq down → heuristic fallback (title + peek at neighboring chunks).
10. Final text = context + chunk. This exact string is what gets searched later.
11. Two numeric fingerprints of that same text:
- Dense vector — MiniLM converts it into 384 numbers capturing meaning.
- Sparse vector — word counts (indices + weights), capturing exact keywords.
12. Storage (two homes, on purpose):
- Qdrant: one point per chunk = id + dense vector + sparse vector + payload (raw chunk, contextualized text, context header, title, org_id, sensitivity, role_access, chunk_index, document_id).
- Postgres:  document_chunks  rows (the registry: which point ids belong to this doc) and  documents.status = 'indexed' ,  chunk_count = N .
13. Frontend polls  GET /documents/{id}/status  every few seconds until status =  indexed / failed .

Stage C — Search (Part 3)

14. You type a question → frontend sends  POST /api/v1/search {query, top_k} .
15. Identity + permissions resolved (dev org/role for now) — these become the RBAC filter.
16. The question gets the same two fingerprints (same embedder → same 384-number space; same tokenizer → same sparse space). Must be the same model, or the numbers aren't comparable.
17. One Qdrant call, two searches: the dense leg finds similar meaning ("vacation days" ≈ "paid leave"), the sparse leg finds exact words ("policy v2.3"). Both legs are filtered by RBAC before scoring. The two ranked lists are fused with RRF: each list gives every hit  1/(60+rank) ; a chunk found by both gets both scores → naturally near the top. Top 20 candidates out.
18. Rerank: a cross-encoder reads each (question, chunk) pair together and gives a precision score → reorder, keep top 5. Model fails → keep the hybrid order (search never dies).
19. Answer: question + the 5 chunks (numbered [1]..[5]) go to Groq → a grounded answer with [n] citations. No key → fallback that quotes the best chunk.
20. Log: one  search_queries  row + 5  query_citations  rows (which doc, which rank, which score). This is Phase 4 feedback's join target.
21. Response  {query_id, answer, sources[], response_time_ms}  → frontend renders the answer panel + source cards. History page later reads the log via  GET /search/history .

One-line summary: file → text → chunks → context-enriched chunks → two vectors each → Qdrant (+ registry in Postgres); question → two vectors → filtered hybrid search → RRF → rerank → LLM answer → log → browser.

────────────────────────────────────────────────────────────────────────────────

3. Qdrant basics — what's happening and why this format

What Qdrant is: a specialized database whose job is one thing — "given these numbers, find me the stored points whose numbers are closest." Postgres answers "exact match on a value"; Qdrant answers "most similar." We use both because those are different questions.

What a vector is here: text squeezed into 384 numbers that preserve meaning. Texts with similar meaning land close together, measured by the angle between them (Cosine — angle ignores length, standard for sentence models).

What our collection looks like:

enterprise_embeddings (collection = one big table of points)
├─ "dense"  named vector : 384 floats (MiniLM, Cosine)   ← meaning leg
├─ "sparse" named vector : {index: value, ...}           ← keyword leg (BM25)
└─ payload (JSON blob per point) : text + metadata

- Why named vectors: one point can carry multiple representations; the search picks which one(s) to use. We query both and fuse.
- Why sparse looks like  {index: weight} : vocabulary is ~50,000+ words but a chunk uses maybe 150 — storing 384 dense numbers per word-position would be wasteful. Sparse stores only the nonzero entries: word → its hashed index, plus its count. Qdrant applies IDF at query time (rare words count more than "the").
- Why two legs: dense finds paraphrases, sparse finds exact terms. Either alone misses half the real-world queries. RRF merges their rankings without needing comparable score scales.
- Why the payload carries everything: search filters ( org_id = X AND not restricted ) run on payload before similarity scoring — that's the RBAC enforcement. And the matched point returns its payload, so we can show title/text without a second DB lookup.
- Why payload indexes: same idea as Postgres indexes — the KEYWORD/BOOL indexes keep filtered search fast as the corpus grows.
- Why point id is a UUID we generate: we store it in Postgres ( document_chunks.qdrant_point_id ) so the registry can always map a Qdrant point back to its document — that's how re-indexing deletes the old points.
- Why chunks, not whole documents: the model's reading limit + precision — you want to cite the paragraph, not the 80-page PDF.
- One gotcha you already lived through: the vector layout (names, size, sparse config) is fixed at collection creation. Changing it = delete collection + re-ingest everything (that's exactly what  reindex_all.py  did).

────────────────────────────────────────────────────────────────────────────────

Everything is in place for you to add your Groq key test when ready —  contextualizer.py  (ingestion) and  llm.py  (answers) will both pick it up automatically, and if the key is wrong/out of quota both fall back gracefully instead of failing.