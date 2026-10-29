# Product chunking benchmark — 26 Oct 2026

## Scope

- Stopped `chatbot-indexer`, `chatbot-image-indexer`, and `chatbot-policy-indexer` before continuing the benchmark. The chatbot API remains running. Benchmark reruns use cached query vectors only (`BENCHMARK_OFFLINE=true`).
- Compared 180 products sampled from 220 whose current Qdrant text chunks match the live catalog. The live catalog has 2,168 approved products, so this is not a full-catalog result.
- Used Gemini `gemini-embedding-001` query vectors already cached for eight Vietnamese search phrases. One phrase, `áo thun nam màu đen`, came from the user; seven are catalog-inspired.
- Marked relevance from product names (type and gender) and actual variant names (color). This corrected a first run in which description-derived color labels missed black variants and included products without a black variant. These are heuristic labels, not human judgments.
- Measured raw vector rankings and rankings with the same product type, audience, and color payload filters used during retrieval. Live stock and final product filtering were not simulated.
- `onePooled` is a normalized average of existing chunk vectors, **not** a Gemini embedding of the complete product document. `baseAndColorGroups` pools title/description into one vector and variants with the same color set into one vector; these pooled vectors are also offline approximations.

## Results

| Layout | Vectors/product | Raw Precision@6 | Raw nDCG@10 | Filtered Precision@6 | Filtered nDCG@10 |
|---|---:|---:|---:|---:|---:|
| One pooled vector | 1.00 | 0.6250 | 0.6912 | 0.8333 | 0.9013 |
| Title only | 1.00 | 0.5208 | 0.6114 | 0.7500 | 0.8202 |
| Title + description | 2.00 | 0.5417 | 0.5949 | 0.6458 | 0.7995 |
| Base + color groups | 3.53 | 0.7292 | 0.8180 | 0.8333 | 0.9267 |
| All chunks (title, description, variants) | 11.49 | **0.7708** | **0.8758** | **0.8958** | **0.9631** |

For `áo thun nam màu đen`, six sampled products have a black variant and a men's T-shirt/Polo name. All chunks retrieved all six in the raw top ten (nDCG@10 0.962), versus four of six for the pooled and title-only layouts. With metadata filters, all chunks scored nDCG@10 0.870 versus 0.681 for pooled. Raw all-chunk results can still include women's tops and men's jackets; metadata filters remove these before final product checks.

All chunks exceeded the grouped layout on seven of eight queries. The mean filtered nDCG@10 advantage was 0.036; an exploratory bootstrap over eight queries (10,000 resamples) gave a 95% interval of 0.016 to 0.058. The queries are related and mostly generated, so this interval does not establish generalization to real shopper traffic. On the complete live catalog, the proposed grouping rule would require 6,597 vectors versus 18,833 for all chunks: 65% fewer embedding inputs.

## Missing comparison

The actual one-vector-per-product design needs Gemini to embed `product_document(product)` for every sampled product. The initial run cached 10 of 180 such vectors, then Gemini returned HTTP 429 with the free tier daily request quota of 1,000 exceeded and a retry delay of about 16 hours 47 minutes. No new embeddings were requested during the offline reruns. Once quota renews, the script can resume this comparison with `BENCHMARK_OFFLINE=false` and `BENCHMARK_EMBED_FULL=true`.

The best quality/cost candidate from this offline experiment is one base vector plus a vector per distinct variant color group, while size remains filterable metadata. It does **not** rule out a carefully written one-vector-per-product document, because that strategy has not yet been measured. Add more human-labeled shopper queries and test actual grouped-text embeddings before changing the production layout.

Detailed per-query results: `chunk-benchmark-results.json`.
