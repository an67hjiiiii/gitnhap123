# CAP1 synthetic benchmark v1

This benchmark is a deterministic, independent retrieval and contradiction test set. It uses only Python 3.12 standard-library modules and makes no model or service calls. The synthetic corpus is generated from the human-readable rows in `seed.py` using seed `20261115`. `generate.py` writes `data/n5`, `data/n30`, and `data/n100`, questions, the real-document sanity set, and SHA-256 inventory. Corpus sizes are document counts, not equal fact counts: n5 contains 20 base facts, while n30 and n100 cover all 60 seed facts; n100 adds repeated coverage and filler documents.

## Generate and verify

From the repository root:

```powershell
python bench/generate.py
python bench/score.py --self-test
python -m pytest -q bench/tests
```

`generate.py --output-dir PATH` can generate an isolated copy for determinism checks. Generated documents use Markdown headings, varied sentence templates, repeated explanatory filler, and spans longer than a 1200-character chunk. `truth.json` records fact placement, exact fact sentences, injected contradictions, duplicates, decoys, and source document text. All conflict values retain identical subject, attribute, and scope; decoy pairs use distinct attributes or scopes.

## Answer result format

`--answers FILE.jsonl` accepts one JSON object per line:

```json
{"qid":"q01","answer":"...","status":"ANSWERABLE","cited_chunk_ids":["chunk-1"],"cited_texts":["..."]}
```

`cited_chunk_ids` and `cited_texts` are accepted for convenient output capture but are not scored. Answers are correct when each expected normalized quantity is present, no `must_not_contain` string appears, and an evidence question is not marked `NO_EVIDENCE`. A no-evidence answer must have status `NO_EVIDENCE` and must not assert a recognized quantity. The scorer reports answerable accuracy, no-answer correctness, hallucinations, wrong-attribute counts for trap questions, and language counts. Numeric time units normalize across seconds, minutes, hours, days, and 365-day years.

## Contradiction result format

`--pairs FILE.json` accepts an array:

```json
[{"quote_a":"exact sentence","quote_b":"exact sentence","doc_a":"n30/docs/doc_001.md","doc_b":"n30/docs/doc_030.md","kind":"contradiction"}]
```

Document names are corpus-relative paths or literal document text. Each quote must be a verbatim substring of its named document and contain a known exact fact sentence. Matching is by the unordered pair of fact IDs. `kind` is `contradiction`, `duplicate`, or `other`; the scorer reports precision and recall separately for contradictions and duplicates, decoy hits, and invalid quotes. A duplicate is the same fact repeated in another document, not a contradiction.

## Paired comparison

`--compare A.jsonl B.jsonl` uses common question IDs only, computes two-sided exact McNemar from discordant outcomes, and reports Wilson 95% accuracy intervals. It prints both systems' raw correct counts and explicitly prints `no significant difference` when p is at least 0.05. No claim of significance should be made from overlapping individual confidence intervals alone.

## Known limits

The corpus is synthetic and its language patterns are intentionally compact; it cannot establish performance on real customer documents, OCR, long-range table structure, ambiguous prose, or production traffic. Quantity recognition is intentionally narrow and should be treated as a benchmark convention, not a general Vietnamese number parser. The real-document sanity questions are a small manually quoted smoke set, not part of the synthetic answer score. Citation relevance is not scored by the answer scorer; contradiction scoring requires verbatim quotes and known fact sentences.
