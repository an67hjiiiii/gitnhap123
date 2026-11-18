"""DEV-only speed experiment. Never touches TEST or the original evidence."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from measure_context_dev import WORK, configure, setup, read_rows, independent_rows, digest, gold_for, article, write_once

OUT = WORK / 'speed5_verified'
BASE = WORK / 'context4_v4'
CONTEXT = 8192
OUTPUT = 700


def append(path, row):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        f.flush()
        os.fsync(f.fileno())


def check_prompt(system, user, schema=None, known_token_count=None):
    from app.retrieval.text import estimate_tokens
    # Approximation only; the provider's actual count is checked after generation.
    size = estimate_tokens(system + user + json.dumps(schema or {}, ensure_ascii=False))
    if size + 512 + OUTPUT > CONTEXT and not (
            known_token_count is not None and 0 < known_token_count <= CONTEXT - OUTPUT):
        raise ValueError('BUDGET_PREFLIGHT: estimated prompt exceeds context')
    return size


def runtime_ps():
    exe = shutil.which('ollama')
    if not exe:
        candidate = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Ollama/ollama.exe'
        exe = str(candidate) if candidate.is_file() else None
    if not exe:
        return {'status': 'NOT_VERIFIED', 'reason': 'ollama executable unavailable'}
    try:
        p = subprocess.run([exe, 'ps'], capture_output=True, text=True, timeout=10, check=False)
        return {'status': 'VERIFIED' if p.returncode == 0 else 'NOT_VERIFIED',
                'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status': 'NOT_VERIFIED', 'reason': type(exc).__name__}


def configure_speed(mode, k):
    flags = configure()
    flags.update(RETRIEVAL_FUSION='off' if mode == 'bm25' else 'bm25',
                 TASK_TOP_K=str(k), MAX_CONTEXT_TOKENS='3000', MAX_RUN_TOKENS='8892',
                 LOCAL_LLM_CONTEXT_TOKENS=str(CONTEXT))
    os.environ.update(flags)
    return flags


def select_rows(dev, phase, sample):
    if len(dev) != 29 or len(sample) != 10 or len(set(sample)) != 10:
        raise ValueError('Unexpected DEV or sample size')
    ids = {r['id'] for r in dev}
    if not set(sample) <= {r['id'] for r in independent_rows(dev)} or len(ids) != 29:
        raise ValueError('Sample must contain unique independent DEV rows')
    return dev if phase == 'all' else [r for r in dev if r['id'] in sample]


def install_bm25(pipeline):
    from app.retrieval.candidate_index import cached_rank
    def retrieve(query, chunks, *, top_k, min_score, source_ids, fallback_trace=None, **kwargs):
        if fallback_trace is not None:
            fallback_trace['backend'] = 'experiment_bm25_only'
        result = cached_rank(pipeline.source_store, query, source_ids, top_k, bm25=True)
        if result is None:
            raise RuntimeError('BM25 index unavailable; refusing fallback')
        return result
    pipeline._retrieve_candidates = retrieve


async def main(args):
    flags = configure_speed(args.retrieval, args.k)
    directory = OUT / f'{args.retrieval}_k{args.k}'
    directory.mkdir(parents=True, exist_ok=True)
    dev_path = WORK / 'bo_cau_hoi' / 'dev.csv'
    dev = read_rows(dev_path)
    sample_path = BASE / 'sample_ids.json'
    target = select_rows(dev, args.phase, json.loads(sample_path.read_text(encoding='utf-8'))['ids'])
    pipeline, vector = setup()
    try:
        from app.core.config import RuntimeConfig
        from app.providers.ollama import OllamaProvider
        from app.providers.base import OutputTruncatedError
        from app.research import pipeline as pipeline_module, vanilla
        from app.research.conversation_context import build_conversation_context
        from app.retrieval.embeddings import OllamaEmbedder
        from app.retrieval.index_identity import IndexIdentity
        from sqlalchemy import text
        import httpx

        chunks = pipeline.source_store.chunks()
        names = sorted({c.source_name for c in chunks})
        if (len(names), len(chunks)) != (21, 1277):
            raise RuntimeError('Scratch corpus drift')
        with pipeline.source_store.session_factory() as db:
            versions = [dict(r) for r in db.execute(text('select * from document_versions order by source_id')).mappings()]
        cache = json.loads((BASE / 'query_vectors.json').read_text(encoding='utf-8'))
        prior = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
        from app.retrieval.multilingual import build_query_variants
        queries = sorted({v.text for r in dev for v in build_query_variants(r['cau_hoi'])})
        if any(q not in cache for q in queries) or digest({q:cache[q] for q in queries}) != prior['query_cache_hash']:
            raise RuntimeError('Query cache differs from prior manifest')
        tags = httpx.get('http://127.0.0.1:11434/api/tags', timeout=10).json()['models']
        digests = {m['name']: m.get('digest') for m in tags if m['name'] in (flags['LOCAL_LLM_MODEL'], 'bge-m3:latest')}
        if digests != prior['model_digests']:
            raise RuntimeError('Model identity differs from cached vectors')
        prior_prompts = [json.loads(line) for line in (BASE/'k10'/'prompts_raw.jsonl').read_text(encoding='utf-8').splitlines()]
        real = pipeline.candidate_index.embedder
        class CachedEmbedder(OllamaEmbedder):
            def embed(self, query):
                if query not in cache:
                    raise RuntimeError('Query vector absent from immutable cache')
                return tuple(cache[query])
        cached = CachedEmbedder(dimension=real.dimension, model=real.model, base_url=real.base_url, timeout=real.timeout)
        if IndexIdentity.from_embedder(cached) != IndexIdentity.from_embedder(real):
            raise RuntimeError('Embedding identity differs')
        pipeline.candidate_index.embedder = cached
        if args.retrieval == 'bm25':
            install_bm25(pipeline)
        code = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))}
        gold_path = WORK/'lo_truy_hoi'/'recall_rows.csv'
        checker_path = WORK/'scripts'/'check_reference_answers.py'
        manifest = dict(code_hash=digest(code), runner_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            helper_hash=hashlib.sha256((ROOT/'scripts'/'measure_context_dev.py').read_bytes()).hexdigest(),
            data_hash=digest(dict(chunks=[(c.chunk_id,c.text,c.provenance) for c in chunks], versions=versions)),
            dev_hash=hashlib.sha256(dev_path.read_bytes()).hexdigest(), sample_hash=hashlib.sha256(sample_path.read_bytes()).hexdigest(),
            gold_hash=hashlib.sha256(gold_path.read_bytes()).hexdigest(), checker_hash=hashlib.sha256(checker_path.read_bytes()).hexdigest(),
            cache_hash=digest(cache), model_digests=digests, flags=flags, runtime_config=asdict(RuntimeConfig.from_env()),
            retrieval=args.retrieval, k=args.k, num_ctx=CONTEXT, max_output=OUTPUT, corpus=[21,1277],
            evaluation='DEV only; version diff is a separate route; no semantic grading')
        if manifest['code_hash'] != prior['code_hash']:
            raise RuntimeError('Prior exact-prompt counts require unchanged application code')
        write_once(directory/'manifest.json', manifest)
        key = digest(manifest)
        result_path = directory/'results.jsonl'
        existing = {}
        if result_path.exists():
            for line in result_path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                if row['manifest_hash'] != key or row['id'] in existing:
                    raise RuntimeError('Existing result mismatch or duplicate')
                existing[row['id']] = row
        current = {}; calls = []; formatted = []
        original_format = vanilla._format_evidence_chunk
        def capture_format(chunk):
            formatted.append(chunk)
            return original_format(chunk)
        vanilla._format_evidence_chunk = capture_format
        class CapturingProvider(OllamaProvider):
            async def _generate(self, **kwargs):
                record = dict(id=current['id'], manifest_hash=key, system=kwargs['system'], user=kwargs['user'],
                    schema=kwargs.get('response_schema'), num_ctx=self.context_tokens,
                    evidence_ids=re.findall(r'\[([^\]\s]+)\] Tài liệu:', kwargs['user']))
                calls.append(record)
                started = time.perf_counter()
                try:
                    if self.context_tokens != CONTEXT or self.max_output_tokens != OUTPUT or kwargs.get('max_output_tokens') not in (None, OUTPUT):
                        raise ValueError('Unexpected model options')
                    known = next((p['prompt_eval_count'] for p in prior_prompts
                        if p['system'] == kwargs['system'] and p['user'] == kwargs['user']
                        and p['evidence_ids'] == record['evidence_ids'] and p.get('prompt_eval_count')), None)
                    record['known_exact_prompt_tokens'] = known
                    record['prompt_token_estimate'] = check_prompt(kwargs['system'], kwargs['user'], kwargs.get('response_schema'), known)
                    response = await super()._generate(**kwargs)
                    record.update(prompt_eval_count=response.usage.input_tokens, eval_count=response.usage.output_tokens, raw_output=response.text)
                    if not response.usage.input_tokens or response.usage.input_tokens + OUTPUT > CONTEXT:
                        raise ValueError('BUDGET_ACTUAL: provider prompt count exceeds context or missing')
                    if known is not None and response.usage.input_tokens != known:
                        raise ValueError('BUDGET_ACTUAL: exact prior prompt count changed; truncation or tokenizer drift')
                    return response
                except OutputTruncatedError as exc:
                    record.update(error_type=type(exc).__name__, raw_output=exc.partial_text,
                                  prompt_eval_count=exc.usage.input_tokens, eval_count=exc.usage.output_tokens)
                    raise
                except Exception as exc:
                    record.update(error_type=type(exc).__name__, error=str(exc))
                    raise
                finally:
                    try:
                        record['api_ps'] = httpx.get(self.base_url+'/api/ps', timeout=5).json()
                    except (httpx.HTTPError, ValueError) as exc:
                        record['api_ps'] = {'status':'NOT_VERIFIED', 'reason':type(exc).__name__}
                    record['seconds'] = time.perf_counter()-started
                    append(directory/'prompts_raw.jsonl', record)
        pipeline_module.get_provider = lambda *a, **kw: CapturingProvider()
        sys.path.insert(0, str(WORK/'scripts'))
        from check_reference_answers import atoms
        histories = {}
        for row in target:
            group = row.get('ma_chuoi') or row['id']
            if row['id'] in existing:
                record = existing[row['id']]
            else:
                current['id'] = row['id']; calls.clear(); formatted.clear()
                before = runtime_ps(); started = time.perf_counter()
                try:
                    response = await pipeline.run(row['cau_hoi'], condition='A', provider_name='ollama', product_mode=True,
                        conversation_context=build_conversation_context({'messages':histories.get(group, [])}))
                    error = None
                except Exception as exc:
                    response = {}; error = {'type':type(exc).__name__, 'message':str(exc)}
                elapsed = time.perf_counter()-started; after = runtime_ps()
                event = next ( (e for e in response.get('events',[]) if e.get('stage') == 'vanilla_retrieval'), {} )
                selected = event.get('selected', [])
                selected_chunks = formatted or pipeline.source_store.chunks_by_ids(selected)
                # Gold and reference are consumed only after inference.
                gold_rows = {r['id']:r for r in read_rows(gold_path) if not r.get('excluded')}
                gold = gold_for(gold_rows[row['id']], names) if row['id'] in gold_rows else set()
                prompt_ids = {cid for call in calls for cid in call.get('evidence_ids', [])}
                reference = {(k,str(v)) for k,v,_ in atoms(row['dap_an_tham_khao'])}
                answer = {(k,str(v)) for k,v,_ in atoms(response.get('answer',''))}
                record = dict(id=row['id'], manifest_hash=key, answer=response.get('answer',''), status=response.get('status'),
                    error=error, budget_failure=any('BUDGET_' in c.get('error','') for c in calls),
                    seconds=elapsed, retrieval_route=event.get('retrieval_fallback'), selected_ids=selected,
                    dropped=event.get('dropped', []), prompt_evidence_ids=sorted(prompt_ids), gold=sorted(gold),
                    gold_in_prompt=sorted({(c.source_name,article(c)) for c in selected_chunks
                        if c.chunk_id in prompt_ids} & gold),
                    gold_ranks=[i+1 for i,cid in enumerate(selected) if cid in prompt_ids and any(c.chunk_id==cid and (c.source_name,article(c)) in gold for c in selected_chunks)],
                    rule_missing=sorted(reference-answer), prompt_eval_counts=[c.get('prompt_eval_count') for c in calls],
                    ps_before=before, ps_after=after, response=response)
                append(result_path, record)
                print('DONE', args.retrieval, args.k, row['id'], elapsed, flush=True)
            histories.setdefault(group, []).extend([dict(message_id=row['id']+'u',role='USER',content=row['cau_hoi']),
                dict(message_id=row['id']+'a',role='ASSISTANT',content=record['answer'])])
    finally:
        vector.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--retrieval', required=True, choices=['bm25','d3'])
    parser.add_argument('--k', type=int, required=True, choices=[5,6])
    parser.add_argument('--phase', required=True, choices=['sample','all'])
    asyncio.run(main(parser.parse_args()))
