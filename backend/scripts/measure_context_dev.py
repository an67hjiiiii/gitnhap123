"""Scratch-only DEV experiment. Never loads held-out questions or changes source data."""
from __future__ import annotations
import argparse, asyncio, csv, hashlib, json, os, re, sys, time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = Path(r'D:\CAP1-Orchestration\work\p3')
OUT = WORK / 'context4_v4'

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def stem(name):
    # Only unique exact stems may bridge the PDF -> extracted TXT representation.
    return Path(name).stem.casefold().strip()

def article(chunk):
    m = re.search(r'Điều\s+(\d+)', chunk.provenance.get('section_path', '') or chunk.text, re.I)
    return int(m[1]) if m else 0

def gold_for(row, names):
    result = []
    for pair in json.loads(row.get('gold_pairs') or '[]'):
        matches = [n for n in names if stem(n) == stem(pair['tệp'])]
        if len(matches) != 1:
            result.append((pair['tệp'], int(pair['Điều'])))
        else:
            result.append((matches[0], int(pair['Điều'])))
    return set(result)

def independent_rows(dev):
    first={}
    for row in dev:
        first.setdefault(row.get('ma_chuoi') or row['id'],row)
    return list(first.values())

def configure():
    defaults = dict(APP_STORAGE_BACKEND='postgres', IMPLEMENTATION_PROFILE='m2', PROVIDER='ollama',
        LOCAL_LLM_MODEL='qwen3:4b-instruct-2507-q4_K_M', VECTOR_BACKEND='qdrant',
        VECTOR_INDEX_PATH=r'D:\CAP1-Orchestration\work\smoke\integ\qdrant_vtest_full_bge2',
        VECTOR_COLLECTION='recall_bge2', VECTOR_SIZE='1024', EMBEDDING_DIMENSION='1024',
        EMBEDDING_BACKEND='ollama', EMBEDDING_MODEL='bge-m3', CHUNK_MODE='legal', INGEST_CLEAN='rules',
        VERSION_FILTER='on', VERSION_RELATIONS='1', VERSION_DIFF='1', VERSION_PROPOSE='1',
        BM25_INDEX='persist', BM25_INDEX_DIR=str(WORK/'lo_truy_hoi3'/'bm25_index_bge2'),
        RETRIEVAL_FUSION='bm25', RETRIEVAL_RETRY='0', RETRIEVAL_NO_FULL_LOAD='1', DOC_ROUTE='off',
        QUERY_NORMALIZE='off', MAX_OUTPUT_TOKENS='700', TASK_PLAN_MAX_OUTPUT_TOKENS='1400')
    for k, v in defaults.items():
        os.environ[k] = v
    url = os.environ.get('DATABASE_URL', '')
    if not re.search(r'127\.0\.0\.1:55440/vtest_full_bge2$', url):
        raise RuntimeError('Only approved scratch database vtest_full_bge2:55440 is allowed')
    return defaults

def setup():
    from sqlalchemy import text
    from app.storage.postgres import create_postgres_engine, create_session_factory
    from app.storage.postgres.runtime import PostgresSourceStore, PostgresRunStore
    from app.research.pipeline import ResearchPipeline
    from app.storage.vector_store import QdrantVectorStore
    from app.retrieval.candidate_index import CandidateIndex
    from app.retrieval.embeddings import make_embedder
    engine = create_postgres_engine(); factory = create_session_factory(engine)
    with engine.connect() as db:
        owners = db.execute(text('select distinct owner_user_id from knowledge_sources')).scalars().all()
    if len(owners) != 1:
        raise RuntimeError('Corpus must have exactly one scratch owner')
    store = PostgresSourceStore(factory, owners[0])
    vector = QdrantVectorStore(path=os.environ['VECTOR_INDEX_PATH'], collection='recall_bge2', vector_size=1024)
    index = CandidateIndex(store, vector, owner_user_id=owners[0], embedder=make_embedder(1024))
    pipeline = ResearchPipeline(store, PostgresRunStore(factory, owners[0]), candidate_index=index, retrieval_backend='qdrant')
    return pipeline, vector

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')

def write_once(path, value):
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != json.loads(json.dumps(value,default=str)):
            raise RuntimeError(f'Immutable evidence differs: {path}; use an explicit new experiment version')
        return
    write(path,value)

async def main(args):
    flags = configure(); OUT.mkdir(parents=True, exist_ok=True)
    dev = read_rows(WORK/'bo_cau_hoi'/'dev.csv'); assert len(dev) == 29
    ids = {r['id'] for r in dev}
    gold_rows = {r['id']: r for r in read_rows(WORK/'lo_truy_hoi'/'recall_rows.csv') if r['id'] in ids and not r.get('excluded')}
    pipeline, vector = setup()
    from app.core.config import RuntimeConfig
    from app.core.types import RunMetrics
    from app.research.product_retrieval import product_retrieve
    from app.retrieval.candidate_index import cached_rank
    from app.retrieval.multilingual import build_query_variants
    from app.research.vanilla import _format_evidence_chunk
    from app.retrieval.text import estimate_tokens
    chunks = pipeline.source_store.chunks(); names = sorted({c.source_name for c in chunks})
    if (len(names),len(chunks)) != (21,1277):
        raise RuntimeError(f'Corpus drift: {len(names)}/{len(chunks)}')
    cfg = replace(RuntimeConfig.from_env(), task_top_k=20)
    cache_path = OUT/'query_vectors.json'
    queries = sorted({v.text for r in dev for v in build_query_variants(r['cau_hoi'])})
    prior_cache=WORK/'context4'/'query_vectors.json'
    cache = json.loads((cache_path if cache_path.exists() else prior_cache).read_text(encoding='utf-8')) if cache_path.exists() or prior_cache.exists() else {}
    real_embedder = pipeline.candidate_index.embedder
    # Embedding preparation is serial and measured separately; tier0 never generates an answer.
    missing = [q for q in queries if q not in cache]
    for q in missing:
        cache[q] = list(pipeline.candidate_index.embedder.embed(q))
    if missing or not cache_path.exists(): write(cache_path, cache)
    from app.retrieval.embeddings import OllamaEmbedder
    class CachedEmbedder(OllamaEmbedder):
        def embed(self, query):
            if query not in cache:
                cache[query] = list(real_embedder.embed(query))
                write(cache_path, cache)
            return tuple(cache[query])
    pipeline.candidate_index.embedder = CachedEmbedder(dimension=real_embedder.dimension,model=real_embedder.model,
        base_url=real_embedder.base_url,timeout=real_embedder.timeout)
    from app.retrieval.index_identity import IndexIdentity
    assert IndexIdentity.from_embedder(pipeline.candidate_index.embedder)==IndexIdentity.from_embedder(real_embedder)
    code = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))}
    from sqlalchemy import text
    with pipeline.source_store.session_factory() as db:
        version_rows=[dict(r) for r in db.execute(text('select * from document_versions order by source_id')).mappings()]
    import httpx
    tags=httpx.get('http://127.0.0.1:11434/api/tags',timeout=10).json().get('models',[])
    model_digests={m['name']:m.get('digest') for m in tags if m['name'] in (flags['LOCAL_LLM_MODEL'],'bge-m3:latest')}
    manifest = dict(code_hash=digest(code), data_hash=digest(dict(chunks=[(c.chunk_id,c.text,c.provenance) for c in chunks],versions=version_rows)),
        config_hash=digest(flags), dev_hash=hashlib.sha256((WORK/'bo_cau_hoi'/'dev.csv').read_bytes()).hexdigest(),
        corpus_files=len(names), corpus_chunks=len(chunks), query_cache_hash=digest({q:cache[q] for q in queries}), flags=flags,
        version_rows=len(version_rows),model_digests=model_digests,evaluator_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        reference_checker_hash=hashlib.sha256((WORK/'scripts'/'check_reference_answers.py').read_bytes()).hexdigest(),
        retrieval_gold_hash=hashlib.sha256((WORK/'lo_truy_hoi'/'recall_rows.csv').read_bytes()).hexdigest(),
        evaluation='DEV_ONLY; exact stem PDF/TXT alias only when unique; no semantic grading')
    write_once(OUT/'manifest.json', manifest)
    try:
        if args.phase == 'prepare':
            print('QUERY_CACHE_READY',len(cache),flush=True)
        elif args.phase == 'recall':
            path = OUT/'retrieval.json'; key = digest(manifest)
            if path.exists():
                if json.loads(path.read_text(encoding='utf-8')).get('key') != key:
                    raise RuntimeError('Existing retrieval evidence differs; do not overwrite')
                print('SKIP unchanged retrieval',flush=True); return
            started=time.perf_counter(); rows=[]
            for row in dev:
                scope=sorted(pipeline.source_store.effective_source_ids(row['cau_hoi'],None))
                bm=cached_rank(pipeline.source_store,row['cau_hoi'],scope,20,bm25=True)
                hy=await product_retrieve(pipeline,None,RunMetrics(),query=row['cau_hoi'],retrieval_query=row['cau_hoi'],
                    chunks=None,cfg=cfg,source_ids=scope,trace={},event=lambda *a,**k:None,retry=False)
                gold=gold_for(gold_rows[row['id']],names) if row['id'] in gold_rows else set()
                for label,hits in [('BM25',bm),('D3',hy)]:
                    ranked=[(c.source_name,article(c)) for c in hits]
                    rows.append(dict(id=row['id'],config=label,gold=sorted(gold),ranked=ranked,
                        chunk_ids=[c.chunk_id for c in hits],hits={str(k):len(set(ranked[:k])&gold) for k in (5,10,20)},
                        gold_ranks=[i+1 for i,p in enumerate(ranked) if p in gold],
                        top10_formatted_chars=sum(len(_format_evidence_chunk(c)) for c in hits[:10]),
                        top10_token_est=sum(estimate_tokens(_format_evidence_chunk(c)) for c in hits[:10])))
            write(path,dict(key=key,manifest=manifest,seconds=time.perf_counter()-started,rows=rows))
            print('RECALL_DONE',time.perf_counter()-started,flush=True)
        else:
            from app.providers.ollama import OllamaProvider
            from app.research import pipeline as pipeline_module
            from app.research.conversation_context import build_conversation_context
            sys.path.insert(0,str(WORK/'scripts'))
            from check_reference_answers import atoms
            retrieval=json.loads((OUT/'retrieval.json').read_text(encoding='utf-8'))
            # Diff evidence deliberately has its own path; size it too rather than clipping comparisons silently.
            diff_peak=0
            for row in dev:
                scope=sorted(pipeline.source_store.effective_source_ids(row['cau_hoi'],None))
                diff=pipeline.source_store.version_diff_evidence(row['cau_hoi'],scope)
                if diff:
                    diff_peak=max(diff_peak,sum(estimate_tokens(_format_evidence_chunk(c)) for c in diff))
            budget=max(3000,max(r['top10_token_est'] for r in retrieval['rows'] if r['config']=='D3')+1500,diff_peak+1500)
            context=max(8192,((budget*2+2047)//2048)*2048)
            os.environ['TASK_TOP_K']=str(args.k)
            os.environ['MAX_CONTEXT_TOKENS']=str(budget)
            os.environ['MAX_RUN_TOKENS']=str(context+1400)
            os.environ['LOCAL_LLM_CONTEXT_TOKENS']=str(context)
            manifest.update(task_top_k=args.k,max_context_tokens=budget,num_ctx=context,condition='A',product_mode=True,
                diff_peak_token_est=diff_peak,token_estimates_are_not_provider_counts=True)
            sample=[]; groups=set(); kinds=set()
            def add_sample(row):
                if row['nhom_noi_dung'] not in groups and len(sample)<10:
                    sample.append(row['id']); groups.add(row['nhom_noi_dung'])
            pool=independent_rows(dev)
            for row in pool:
                if row['kieu_cau'] not in kinds:
                    add_sample(row); kinds.add(row['kieu_cau'])
            for row in pool:
                if row['id'].startswith('L2_'):
                    add_sample(row)
            for row in pool:
                add_sample(row)
            assert len(sample)==10 and len(set(sample))==10
            write_once(OUT/'sample_ids.json',dict(ids=sample,rule='independent first turns only; first per type then L2 groups then remaining groups; no outcome selection'))
            directory=OUT/f'k{args.k}'; directory.mkdir(exist_ok=True)
            runkey=digest(manifest); mpath=directory/'manifest.json'
            if mpath.exists() and json.loads(mpath.read_text(encoding='utf-8'))!=manifest:
                raise RuntimeError('Existing attempt config differs; do not overwrite evidence')
            write_once(mpath,manifest)
            results_path=directory/'results.jsonl'
            existing={r['id']:r for r in (json.loads(x) for x in results_path.read_text(encoding='utf-8').splitlines())} if results_path.exists() else {}
            if any(r.get('manifest_hash')!=runkey for r in existing.values()):
                raise RuntimeError('Persisted attempt manifest mismatch')
            # Explicit reuse mapping: preserve original files; do not regenerate unchanged independent inputs.
            prior=WORK/'context4_v2'/f'k{args.k}'
            if args.reuse_compatible and (prior/'manifest.json').exists() and (prior/'results.jsonl').exists():
                prior_manifest=json.loads((prior/'manifest.json').read_text(encoding='utf-8'))
                comparable=('code_hash','data_hash','flags','dev_hash','reference_checker_hash','retrieval_gold_hash',
                    'model_digests','task_top_k','max_context_tokens','num_ctx')
                if any(prior_manifest.get(k)!=manifest.get(k) for k in comparable):
                    raise RuntimeError('Prior attempts are not compatible for reuse')
                first_ids={r['id'] for r in pool}
                for line in (prior/'results.jsonl').read_text(encoding='utf-8').splitlines():
                    old=json.loads(line)
                    if old['id'] in first_ids and old['id'] not in existing:
                        record={**old,'original_manifest_hash':old['manifest_hash'],'manifest_hash':runkey,
                            'reused_from':str(prior/'results.jsonl'),'new_inference':False}
                        with results_path.open('a',encoding='utf-8') as f:
                            f.write(json.dumps(record,ensure_ascii=False)+'\n')
                        existing[record['id']]=record
            current={}; calls=[]; formatted_chunks=[]
            from app.research import vanilla as vanilla_module
            original_format=vanilla_module._format_evidence_chunk
            def capture_format(chunk):
                formatted_chunks.append(chunk)
                return original_format(chunk)
            vanilla_module._format_evidence_chunk=capture_format
            class CapturingProvider(OllamaProvider):
                async def _generate(self, **kwargs):
                    record=dict(id=current['id'],k=args.k,system=kwargs['system'],user=kwargs['user'],num_ctx=context,
                        evidence_ids=re.findall(r'\[([^\]\s]+)\] Tài liệu:',kwargs['user']))
                    calls.append(record); start=time.perf_counter()
                    try:
                        response=await super()._generate(**kwargs)
                        record.update(prompt_eval_count=response.usage.input_tokens,eval_count=response.usage.output_tokens,
                                      raw_output=response.text,seconds=time.perf_counter()-start)
                        try:
                            loaded=httpx.get('http://127.0.0.1:11434/api/ps',timeout=5).json().get('models',[])
                            record['runtime_context_length']=next((m.get('context_length') for m in loaded if m.get('name')==self.model),None)
                        except httpx.HTTPError:
                            record['runtime_context_length']=None
                        return response
                    except Exception as exc:
                        record.update(error_type=type(exc).__name__,seconds=time.perf_counter()-start)
                        raise
                    finally:
                        with (directory/'prompts_raw.jsonl').open('a',encoding='utf-8') as f:
                            f.write(json.dumps(record,ensure_ascii=False)+'\n')
            provider=CapturingProvider()
            pipeline_module.get_provider=lambda *a,**kw:provider
            histories={}
            target=dev if args.phase=='all' else [r for r in dev if r['id'] in sample]
            for row in target:
                group=row.get('ma_chuoi') or row['id']
                if row['id'] in existing:
                    record=existing[row['id']]
                else:
                    current['id']=row['id']; calls.clear(); formatted_chunks.clear(); start=time.perf_counter()
                    response=await pipeline.run(row['cau_hoi'],condition='A',provider_name='ollama',product_mode=True,
                        conversation_context=build_conversation_context({'messages':histories.get(group,[])}))
                    event=next((e for e in response.get('events',[]) if e.get('stage')=='vanilla_retrieval'),{})
                    selected=event.get('selected',[])
                    selected_chunks=formatted_chunks or pipeline.source_store.chunks_by_ids(selected)
                    gold=gold_for(gold_rows[row['id']],names) if row['id'] in gold_rows else set()
                    prompt_ids={cid for call in calls for cid in call.get('evidence_ids',[])}
                    in_prompt={(c.source_name,article(c)) for c in selected_chunks if c.chunk_id in prompt_ids}
                    reference_atoms={(k,str(v)) for k,v,_ in atoms(row['dap_an_tham_khao'])}
                    answer_atoms={(k,str(v)) for k,v,_ in atoms(response.get('answer',''))}
                    record=dict(row,id=row['id'],answer=response.get('answer',''),status=response.get('status'),
                        seconds=time.perf_counter()-start,run_id=response.get('run_id'),selected_ids=selected,
                        dropped=event.get('dropped',[]),prompt_evidence_ids=sorted(prompt_ids),gold=sorted(gold),
                        gold_in_prompt=sorted(in_prompt&gold),gold_prompt_ranks=[i+1 for i,cid in enumerate(selected)
                            if any(c.chunk_id==cid and (c.source_name,article(c)) in gold and cid in prompt_ids for c in selected_chunks)],
                        rule_missing=sorted(reference_atoms-answer_atoms),rule_reference_n=len(reference_atoms),
                        prompt_eval_counts=[c.get('prompt_eval_count') for c in calls],metrics=response.get('metrics'),
                        response=response,manifest_hash=runkey)
                    with results_path.open('a',encoding='utf-8') as f:
                        f.write(json.dumps(record,ensure_ascii=False,default=str)+'\n');f.flush();os.fsync(f.fileno())
                    print(f"DONE k{args.k} {row['id']} {record['seconds']:.1f}s selected={len(selected)} prompt={len(prompt_ids)}",flush=True)
                histories.setdefault(group,[]).extend([
                    dict(message_id=row['id']+'u',role='USER',content=row['cau_hoi']),
                    dict(message_id=row['id']+'a',role='ASSISTANT',content=record['answer'])])
    finally:
        vector.client.close()

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['prepare','recall','sample','all'],required=True)
    p.add_argument('--k',type=int,choices=[6,10],default=10)
    p.add_argument('--reuse-compatible',action='store_true',help='Explicitly reuse only verified independent attempts from the preliminary v2 cohort')
    asyncio.run(main(p.parse_args()))
