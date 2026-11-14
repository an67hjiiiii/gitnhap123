# Seeded retrieval negative evidence

These 14 cases are authored fixtures, not model-generated labels. Every query,
chunk ID, source ID, text, and `relevant_ids` list is fixed in `cases.json` before
retrieval runs. Relevance means the chunk directly supplies the requested fact
or supports the requested assertion. A conflicting number, channel, or subject
does not support that assertion. Empty relevance lists deliberately distinguish
missing facts from topical similarity. English and Vietnamese cases are included.

## Construction and measurement

- Five `present` cases contain explicit facts. The notification case requires
  both email and SMS chunks, so recall measures coverage rather than any-hit rate.
- Four `absent` cases omit the requested duration, region, or session expiry,
  or contain an entirely unrelated corpus. Topical chunks cannot answer them.
- Three `near_miss_conflicting` cases substitute 90 for 180 days, email-only for
  SMS, or 60 for 30 minutes. Their fixed support sets are empty by construction.
- Two `distractor_heavy` cases each have eight chunks and a single explicit
  answer. Shared words and numbers in other subjects are intentional distractors.

Tests use `LocalHashEmbedder` (default dimension 768), `InMemoryVectorStore`,
`CandidateIndex`, and `ResearchPipeline._retrieve_candidates`. Provider selection
is monkeypatched to `fake`; synthetic responses use local doubles without sleeps.
No source/run files, databases, external models, or network services are needed.
The index writer initializes its identity manifest in memory. Emptying that index
also exercises the production lexical fallback over the same scoped chunks.

The fixed settings are `k=4` and `min_score=0.18` (the current runtime default).
The printed table covers all cases; macro recall@4 averages
`len(retrieved_ids & relevant_ids) / len(relevant_ids)` over `present` cases only.
Empty relevance sets are shown as `n/a`, never treated as perfect recall.
The observed present baseline is 1.000; the regression floor is 0.950, a margin
of 0.050. Distractor and conflict rows are diagnostics, outside that average.

Absent false support counts every returned candidate from an `absent` case, since
none supplies the missing fact. This measures retrieval exposure, not fabricated
model claims or validated review evidence. The baseline is five chunks across
three of four absent cases: retention 2, backup region 2, Vietnamese session 1,
unrelated 0. A separate non-strict xfail records the desired zero-candidate
behavior with reason `SUSPECTED DEFECT: min_score accepts topical chunks that do
not contain the requested fact`; the characterization test pins current counts.

Citation tests check the real vanilla answerer's rejection of a known corpus ID
outside its supplied evidence, plus a direct static call to
`PipelineReviewEngine._evidence` using an untrusted synthetic answer. Existing
but unretrieved chunks, invented IDs, and uncited retrieved chunks cannot become
review evidence. A valid duplicate citation yields one evidence item. The
absent-evidence adapter runs explicitly supply an empty retrieval result to the
real answerer, then check `NO_EVIDENCE` maps to `NOT_FOUND`, with no evidence or
conflict event. These doubles test that boundary, not semantic abstention by the
retriever; the absent retrieval measurement documents that separate limitation.

Run from the worktree's `backend` directory:

```powershell
& 'D:\CAP1_AI_STUDIO_C1SE27\backend\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp=D:\CAP1-Worktrees\s3\w-5\backend\.pytest_basetemp -s tests/test_retrieval_negative_evidence.py
```

## Raw output of the new test file

```text
.
case | kind | retrieved ids | hit | recall@4
present_retention | present | retention_policy,retention_ui | 1 | 1.0
present_timeout | present | session_limit | 1 | 1.0
present_notifications | present | notify_email,notify_sms | 2 | 1.0
present_backup_vi | present | backup_schedule | 1 | 1.0
present_crypto | present | invoice_cipher | 1 | 1.0
absent_retention_duration | absent | logs_screen,logs_format | 0 | n/a
absent_backup_region | absent | backup_cipher,backup_restore | 0 | n/a
absent_session_vi | absent | session_audit_vi | 0 | n/a
absent_unrelated | absent | - | 0 | n/a
conflicting_retention | near_miss_conflicting | retention_90,invoice_180 | 0 | n/a
conflicting_notifications | near_miss_conflicting | email_only,marketing_sms | 0 | n/a
conflicting_timeout_vi | near_miss_conflicting | session_60_vi,backup_30_vi | 0 | n/a
distractors_retention | distractor_heavy | heavy_auth_policy,heavy_display,heavy_billing,heavy_debug | 1 | 1.0
distractors_backup_vi | distractor_heavy | heavy_backup_02,heavy_backup_button,heavy_backup_cipher,heavy_backup_owner | 1 | 1.0
present macro recall@4=1.000; floor=0.950
.
absent false-support retrievals (min_score=0.18): {'absent_retention_duration': 2, 'absent_backup_region': 2, 'absent_session_vi': 1, 'absent_unrelated': 0}
absent false-support chunks=5; affected cases=3/4
.x.......
10 passed, 1 xfailed in 0.52s
```
