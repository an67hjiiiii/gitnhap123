"""DEV-only D0 counterfactual on canonical scratch chunks; never writes SQL."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import measure_context_dev as base

OUT = base.WORK / 'speed5' / 'd0_verified'
CACHE = base.WORK / 'speed5' / 'd0'


def old_article(chunk):
    match = re.search(r'Điều\s+(\d+)', chunk.text, re.I)
    return int(match[1]) if match else 0


def scoring(hits, gold, names, heading=True, alias=True):
    pairs = base.gold_for({'gold_pairs': json.dumps(gold, ensure_ascii=False)}, names) if alias else {
        (p['tệp'], int(p['Điều'])) for p in gold}
    normalize = lambda name: re.sub(r'\s+', ' ', name.strip()).casefold()
    pairs = {(normalize(name), number) for name, number in pairs}
    ranked = [(normalize(c.source_name), base.article(c) if heading else old_article(c)) for c in hits]
    return {str(k): len(set(ranked[:k]) & pairs) for k in (5, 10, 20)}


async def main(args):
    base.configure()  # Guards exactly the authorized scratch database.
    os.environ.update(EMBEDDING_MODEL='nomic-embed-text', EMBEDDING_DIMENSION='768',
        VECTOR_SIZE='768', VECTOR_COLLECTION='speed5_nomic', BM25_INDEX='', BM25_INDEX_DIR='',
        VERSION_FILTER='off', VERSION_RELATIONS='0', VERSION_DIFF='0', VERSION_PROPOSE='0',
        RETRIEVAL_NO_FULL_LOAD='0')
    from sqlalchemy import text
    from app.storage.postgres import create_postgres_engine, create_session_factory
    from app.storage.postgres.runtime import PostgresSourceStore, PostgresRunStore
    from app.storage.vector_store import QdrantVectorStore, VectorRecord
    from app.retrieval.text import contextual_text, content_hash
    from app.retrieval.embeddings import OllamaEmbedder
    from app.retrieval.index_identity import IndexIdentity, IndexManifest
    from app.retrieval.candidate_index import CandidateIndex
    from app.retrieval.multilingual import build_query_variants
    from app.research.pipeline import ResearchPipeline
    from app.research.product_retrieval import product_retrieve
    from app.core.config import RuntimeConfig
    from app.core.types import RunMetrics
    import httpx

    OUT.mkdir(parents=True, exist_ok=True)
    engine = create_postgres_engine()
    factory = create_session_factory(engine)
    with engine.connect() as db:
        owners = db.execute(text('select distinct owner_user_id from knowledge_sources')).scalars().all()
        versions = [dict(r) for r in db.execute(text('select * from document_versions order by source_id')).mappings()]
    assert len(owners) == 1
    store = PostgresSourceStore(factory, owners[0])
    chunks = store.chunks()
    names = sorted({c.source_name for c in chunks})
    assert (len(names), len(chunks)) == (21, 1277)
    dev = base.read_rows(base.WORK / 'bo_cau_hoi' / 'dev.csv')
    assert len(dev) == 29
    gold = {r['id']: r for r in base.read_rows(base.WORK / 'lo_truy_hoi' / 'recall_rows.csv') if not r.get('excluded')}
    tags = httpx.get('http://127.0.0.1:11434/api/tags', timeout=10).json()['models']
    model = next(m for m in tags if m['name'] in ('nomic-embed-text:latest', 'nomic-embed-text'))
    code = {str(p.relative_to(base.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((base.ROOT / 'app').rglob('*.py'))}
    manifest = dict(code_hash=base.digest(code), data_hash=base.digest(dict(
        chunks=[(c.chunk_id, c.text, c.provenance) for c in chunks], versions=versions)),
        dev_hash=hashlib.sha256((base.WORK / 'bo_cau_hoi' / 'dev.csv').read_bytes()).hexdigest(),
        model_digest=model['digest'], corpus_files=21, corpus_chunks=1277,
        evaluator_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        flags={k: os.getenv(k) for k in ('EMBEDDING_MODEL', 'EMBEDDING_DIMENSION', 'BM25_INDEX',
            'VERSION_FILTER', 'VERSION_DIFF', 'VERSION_PROPOSE', 'RETRIEVAL_FUSION',
            'RETRIEVAL_NO_FULL_LOAD', 'DOC_ROUTE', 'QUERY_NORMALIZE')})
    base.write_once(OUT / 'manifest.json', manifest)
    prepared_manifest = json.loads((CACHE / 'manifest.json').read_text(encoding='utf-8'))
    for key in ('data_hash', 'dev_hash', 'model_digest'):
        assert prepared_manifest[key] == manifest[key], f'Prepared embedding identity changed: {key}'
    embedder = OllamaEmbedder(dimension=768, model='nomic-embed-text')
    queries = sorted({v.text for row in dev for v in build_query_variants(row['cau_hoi'])})
    vector_path = CACHE / 'vectors.jsonl'
    cached = {r['chunk_id']: r for r in (json.loads(line) for line in vector_path.read_text(encoding='utf-8').splitlines())} if vector_path.exists() else {}
    started = time.perf_counter()
    if args.phase == 'prepare':
        missing = [c for c in chunks if c.chunk_id not in cached]
        for offset in range(0, len(missing), 16):
            batch = missing[offset:offset + 16]
            vectors = embedder.embed_many([contextual_text(c) for c in batch])
            with vector_path.open('a', encoding='utf-8') as file:
                for chunk, vector in zip(batch, vectors):
                    row = dict(chunk_id=chunk.chunk_id, text_hash=content_hash(contextual_text(chunk)), vector=vector)
                    file.write(json.dumps(row) + '\n')
                file.flush(); os.fsync(file.fileno())
            print('EMBED', min(offset + 16, len(missing)), '/', len(missing), flush=True)
        query_path = CACHE / 'queries.json'
        query_cache = json.loads(query_path.read_text(encoding='utf-8')) if query_path.exists() else {}
        for query in queries:
            if query not in query_cache:
                query_cache[query] = list(embedder.embed(query))
                base.write(query_path, query_cache)
        base.write(OUT / 'preparation.json', dict(seconds=time.perf_counter() - started,
            embedded_chunks=len(missing), query_n=len(query_cache), no_generation=True))
        print('PREPARED', flush=True)
        return
    assert len(cached) == 1277
    for chunk in chunks:
        assert cached[chunk.chunk_id]['text_hash'] == content_hash(contextual_text(chunk))
    query_cache = json.loads((CACHE / 'queries.json').read_text(encoding='utf-8'))
    class CachedNomic(OllamaEmbedder):
        def embed(self, query):
            return tuple(query_cache[query])  # Missing cache fails closed; recall never calls Ollama.
    cached_embedder = CachedNomic(dimension=768, model='nomic-embed-text')
    assert IndexIdentity.from_embedder(cached_embedder) == IndexIdentity.from_embedder(embedder)
    vector = QdrantVectorStore(str(OUT / 'qdrant'), 'speed5_nomic', 768)
    try:
        identity = IndexIdentity.from_embedder(embedder)
        sidecar = OUT / 'index_manifest.json'
        base.write_once(sidecar, dict(schema_version=1, **asdict(IndexManifest(identity, payload_complete=True))))
        if vector.count() == 0:
            vector.upsert(VectorRecord(f'{owners[0]}:{c.chunk_id}', tuple(cached[c.chunk_id]['vector']), {
                **c.provenance, 'owner_user_id': owners[0], 'source_id': c.source_id,
                'chunk_id': c.chunk_id, 'source_name': c.source_name, 'workspace_id': None,
                'embedding_version': identity.embedding_version, 'content_hash': content_hash(c.text)}) for c in chunks)
        assert vector.count() == 1277
        index = CandidateIndex(store, vector, owner_user_id=owners[0], embedder=cached_embedder, manifest_path=sidecar)
        pipeline = ResearchPipeline(store, PostgresRunStore(factory, owners[0]), index, 'qdrant')
        cfg = replace(RuntimeConfig.from_env(), task_top_k=20)
        for mode, version in [(m,v) for m in ('historical_api', 'product_hybrid') for v in ('off','on')]:
            path = OUT / f'recall_{mode}_version_{version}.json'
            if path.exists():
                assert json.loads(path.read_text(encoding='utf-8'))['manifest_hash'] == base.digest(manifest)
                print('SKIP', mode, version, flush=True)
                continue
            os.environ['VERSION_FILTER'] = version
            os.environ['VERSION_RELATIONS'] = '1' if version == 'on' else '0'
            rows = []; start = time.perf_counter()
            for row in dev:
                scope = sorted(store.effective_source_ids(row['cau_hoi'], None))
                if mode == 'historical_api':
                    # /api/studio/retrieval-test never calls product_retrieve/fusion.
                    hits = pipeline._retrieve_candidates(row['cau_hoi'], chunks, top_k=20,
                        min_score=0.0, source_ids=None, fallback_trace={})
                else:
                    hits = await product_retrieve(pipeline, None, RunMetrics(), query=row['cau_hoi'],
                        retrieval_query=row['cau_hoi'], chunks=None, cfg=cfg, source_ids=scope,
                        trace={}, event=lambda *a, **k: None, retry=False)
                pairs = json.loads(gold[row['id']]['gold_pairs']) if row['id'] in gold else []
                scored = {f'{heading}_{alias}': scoring(hits, pairs, names, heading, alias)
                          for heading in (False, True) for alias in (False, True)}
                rows.append(dict(id=row['id'], gold=pairs, scores=scored,
                    ranked=[dict(chunk_id=c.chunk_id, source_name=c.source_name,
                        article=base.article(c), old_article=old_article(c), text=c.text,
                        provenance=c.provenance) for c in hits]))
            effective = {**manifest['flags'], 'VERSION_FILTER': version,
                'VERSION_RELATIONS': os.environ['VERSION_RELATIONS'], 'retrieval_path': mode,
                'top_k': 20, 'min_score': 0.0 if mode == 'historical_api' else cfg.retrieval_min_score}
            result = dict(manifest_hash=base.digest(manifest), version_filter=version, retrieval_path=mode,
                effective_config=effective, config_hash=base.digest(effective),
                seconds=time.perf_counter() - start, query_embeddings='precomputed', rows=rows)
            base.write_once(path, result)
            print(mode, version, 'NEW_METRIC', {k: sum(r['scores']['True_True'][k] for r in rows) for k in ('5','10','20')},
                  'seconds', result['seconds'], flush=True)
    finally:
        vector.client.close()
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('prepare', 'recall'), required=True)
    asyncio.run(main(parser.parse_args()))
