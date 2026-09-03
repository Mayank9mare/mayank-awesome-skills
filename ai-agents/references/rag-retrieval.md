# Retrieval (RAG) that actually works

Most "the model hallucinates" complaints are retrieval failures. The model answered
faithfully from context that didn't contain the answer. **Fix retrieval before touching the
prompt** — and measure retrieval separately from generation, or you can't tell which half is
broken.

## Measure the two halves separately

```
retrieval quality:   was the answer present in what we retrieved?   (recall@k)
generation quality:  given correct context, was the answer right?   (faithfulness)
```

Evaluate them independently. A pipeline scoring 60% end-to-end could be 95% retrieval / 63%
generation or 62% retrieval / 97% generation — completely different fixes. Build a small
labelled set of (question → the chunk that contains the answer) and track **recall@k**:
if the right chunk isn't in the top-k, no prompt engineering will save you.

## Chunking is the highest-leverage decision

| Strategy | Use when |
|---|---|
| **Structure-aware** (by heading/section) | Documents have real structure — docs, wikis, contracts. **Default.** |
| Fixed-size + overlap (~10–20%) | Unstructured prose. Simple, surprisingly competitive. |
| Sentence/paragraph windows | Retrieve a small unit, then expand to neighbours for context. |
| Semantic (embedding-similarity boundaries) | Expensive; rarely beats structure-aware in practice. |
| **Whole document** | Documents are small and models are long-context. Underrated. |

The failure to avoid: a chunk that splits mid-thought so the answer spans two chunks and
neither is retrievable on its own. Structure-aware chunking with a small overlap fixes most
of it.

Two practices that punch above their weight:

**Keep a parent/child relationship.** Embed a small chunk for precise matching, but return
the larger parent section to the model. You get retrieval precision *and* enough context to
answer.

**Prepend context to each chunk before embedding.** A chunk reading "It requires two
approvals" is unmatchable; the same chunk prefixed with its document title and section
heading — "Refund Policy › Escalations: It requires two approvals" — is findable. This is
cheap and one of the biggest single wins available.

**Always store metadata with the chunk**: source ID, title, section, URL, timestamp, tenant,
and permissions. You need it for filtering, for citations, and for expiring stale content.

## Hybrid search beats pure vector search

Pure embeddings miss exact matches. Search for an error code `E4021`, a product SKU, or a
person's surname and semantic similarity returns things that are *about* the topic while
missing the literal string. Keyword search (BM25) nails those and misses paraphrases. You
need both.

```python
# Run both, then fuse. Reciprocal Rank Fusion needs no score normalisation,
# which is exactly the problem when combining a cosine score with a BM25 score.
def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)

fused = rrf([vector_search(q, k=50), bm25_search(q, k=50)])
```

Then **rerank**. Retrieve broadly (k≈50) with cheap methods, then score the candidates with a
cross-encoder reranker and keep the top 5–10. The reranker sees query and document together
rather than comparing pre-computed vectors, so it's far more accurate — and running it on 50
candidates instead of the whole corpus keeps it affordable. **Retrieve wide, rerank, pass
narrow** is the standard shape for a reason.

## Multi-tenant isolation is a hard requirement

```python
# WRONG — the classic cross-tenant leak. Filtering after retrieval means the
# top-k was computed across ALL tenants, so you may return zero rows for a user
# whose documents were crowded out — or leak if the filter is ever skipped.
results = [r for r in vector_search(q, k=10) if r.tenant_id == tenant_id]

# RIGHT — the filter is part of the query. The index never considers other tenants.
results = vector_search(q, k=10, filter={"tenant_id": tenant_id})
```

**Test this adversarially.** Seed two tenants with distinctive documents and assert that
tenant A's query never returns tenant B's content — including when A's own corpus is empty,
the case where a broken filter is most likely to surface another tenant's data. Same for
per-document ACLs: filter at query time, and re-check permissions before rendering, because
a document's ACL may have changed since indexing.

## Query transformation

The user's question is often not the best search query.

- **HyDE** — have the model write a hypothetical answer, embed *that*, and search with it.
  Answers look like documents; questions don't. Cheap and effective.
- **Multi-query** — generate 2–3 paraphrases, search each, fuse. Improves recall on
  ambiguous phrasing.
- **Decomposition** — split a compound question ("compare X and Y") into sub-queries and
  retrieve for each. Single-shot retrieval systematically fails compound questions.
- **Conversational rewrite** — resolve pronouns and ellipsis against history before
  searching. "What about the second one?" is meaningless as a standalone query, and this is
  the most commonly missed step in chat RAG.

Each adds latency and cost. Add them because your recall measurement says you need them.

## Citations, and verifying them

Citations are a correctness mechanism, not a UI nicety — they make the answer checkable.

```python
# Ask for structured citations tied to the chunk IDs you supplied…
class Answer(BaseModel):
    text: str
    citations: list[str]      # chunk IDs, from the provided context only

# …then VERIFY. A citation to a chunk you never supplied is a hallucination
# with a footnote, and it's the most credible-looking failure mode there is.
supplied = {c.id for c in context_chunks}
if invalid := set(answer.citations) - supplied:
    span.add_event("guardrail.invalid_citation", {"ids": sorted(invalid)})
    return retry_or_escalate()
```

Stronger still, where it matters: check that each cited chunk plausibly supports the claim
(an entailment check, or a judge). Unsupported-but-cited is the failure users trust most.

## Common failure modes

| Symptom | Likely cause |
|---|---|
| "It says it doesn't know" but the doc exists | Recall failure — chunking or embedding mismatch. Check recall@k first. |
| Right topic, wrong specifics | Chunks too large; the answer is buried. Reduce chunk size, add reranking. |
| Misses exact codes/IDs/names | No keyword search. Add BM25 and fuse. |
| Answers from an outdated document | No recency handling. Filter or boost by timestamp; expire stale content. |
| Confidently wrong with a citation | Not verifying citations, or the chunk was retrieved but doesn't support the claim. |
| Fails on "compare A and B" | Single-shot retrieval on a compound query. Decompose. |
| Fails on follow-up questions | No conversational query rewriting. |
| Cross-tenant content appears | Filtering after retrieval instead of in the query. |
| Slow | Reranking too many candidates, or embedding the query on every call. Cache embeddings. |

## Keeping the index fresh

- **Incremental updates with content hashes.** Re-embedding a corpus nightly is wasteful and
  slow; re-embed only what changed.
- **Deletion must propagate.** A deleted source document that stays in the index is both a
  correctness bug and, for access-revoked content, a compliance one.
- **Re-embed the whole corpus when you change the embedding model.** Vectors from different
  models are not comparable — mixed-model indexes silently return garbage. Version your
  index and do a blue/green switch rather than a partial migration.
- **Track index freshness as a metric.** "Oldest un-reindexed document" is the signal that
  catches a broken ingestion pipeline before users report stale answers.

## When not to use RAG

- **The corpus fits in context.** With long-context models, just pass the documents. No
  retrieval means no retrieval failures. Cost is higher per call — but prompt caching
  changes that maths, and a stable document prefix caches well.
- **The answer needs computation, not lookup** — query a database or call an API.
- **A structured query is the real requirement.** "How many orders shipped last week?" is
  SQL. Semantic search over rows is the wrong tool and will be subtly wrong.

## Checklist

- [ ] Retrieval and generation evaluated **separately**; recall@k tracked
- [ ] Structure-aware chunking; no answers split across chunks
- [ ] Document/section context prepended to chunks before embedding
- [ ] Metadata stored: source, title, section, timestamp, tenant, permissions
- [ ] **Hybrid** vector + keyword search, fused (RRF)
- [ ] Retrieve wide → rerank → pass narrow (5–10 chunks)
- [ ] Tenant/ACL filter applied **in the query**, adversarially tested, incl. empty-corpus case
- [ ] Permissions re-checked at render time, not only at index time
- [ ] Conversational query rewriting for follow-ups
- [ ] Compound questions decomposed
- [ ] Structured citations, **verified** against supplied chunk IDs
- [ ] Incremental re-indexing by content hash; deletions propagate
- [ ] Full re-embed + index version bump on embedding-model change
- [ ] Index freshness monitored
- [ ] Considered whether long-context + caching removes the need for RAG entirely
