# Midterm multilingual knowledge demo

The fixture corpus under `datasets/demo/midterm_multilingual_v1/` is a small,
synthetic, non-normative demo set. It covers Architecture/API, Database and
Security with English and Vietnamese Markdown/TXT sources.

Retrieval keeps the original query and adds one bounded deterministic concept
variant for the existing lexical/hash-vector stack. Owner and source filters
are applied by the existing candidate-index path for every variant. The
answer boundary asks the local grounded answerer for natural Vietnamese while
preserving technical identifiers and original citation locators.

This is a demo hardening layer, not a multilingual embedding benchmark. It
does not add file formats, a translation service, or new orchestration stages.
