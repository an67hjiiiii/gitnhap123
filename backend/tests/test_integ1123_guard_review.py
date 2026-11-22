from app.core.answer_checks import guard_cited_claims

def test_guard_must_not_strengthen_may_to_must():
    text, removed, supported = guard_cited_claims('Employees must request leave.', ['Employees may request leave.'])
    assert removed and not supported and 'must request' not in text

def test_guard_does_not_swap_named_actors():
    text, removed, supported = guard_cited_claims('Alice approved Bob.', ['Bob approved Alice.'])
    assert removed and not supported and 'Alice approved Bob' not in text

def test_unrelated_negation_does_not_remove_exact_supported_claim():
    claim='Employees are entitled to leave.'
    text, removed, supported = guard_cited_claims(claim, ['Employees are entitled to leave. Managers do not approve expenses.'])
    assert not removed and supported and text==claim

def test_claim_must_match_its_inline_citation_not_other_cited_chunk(monkeypatch):
    import asyncio, json
    import app.research.pipeline as mod
    from app.core.types import SourceChunk, Usage
    a='src_aaaaaaaaaaaaaaaa_c0001'; b='src_aaaaaaaaaaaaaaaa_c0002'
    chunks=[SourceChunk(chunk_id=a,source_id='source',source_name='doc',text='The budget is 30 days.',index=0),SourceChunk(chunk_id=b,source_id='source',source_name='doc',text='The budget is 12 days.',index=1)]
    class Source:
        def snapshot_id(self): return 'test'
        def chunks(self,ids): return chunks
    class Runs:
        def save(self,run): pass
    class Fake:
        name='fake';model='fake'
        async def generate(self,**kwargs):
            return type('R',(),{'text':json.dumps({'status':'COMPLETE','answer':f'The budget is 12 days [{a}].','citations':[a,b],'missing_information':[]}),'usage':Usage()})()
    monkeypatch.setattr(mod,'get_provider',lambda _:Fake())
    for n in ('process_rss_mb','gpu_memory_mb','cpu_times','model_rss_mb'): monkeypatch.setattr(mod,n,lambda:None)
    monkeypatch.setattr(mod,'cpu_busy_percent',lambda _:None)
    pipeline=mod.ResearchPipeline(Source(),Runs())
    monkeypatch.setattr(pipeline,'_retrieve_candidates',lambda *args,**kwargs:chunks)
    result=asyncio.run(pipeline.run('budget',condition='A',product_mode=True))
    assert result['status'] in ('PARTIAL','NO_EVIDENCE') and '12 days' not in result['answer']

def test_inline_citation_after_punctuation_cannot_borrow_another_source():
    a='src_aaaaaaaaaaaaaaaa_c0001'; b='src_aaaaaaaaaaaaaaaa_c0002'
    claim=f'The budget is 12 days. [{a}]'
    result, removed, supported=guard_cited_claims(claim,{a:'The budget is 30 days.',b:'The budget is 12 days.'})
    assert removed and not supported and '12 days' not in result

def test_compound_unknown_locator_is_not_retained():
    from app.core.citations import strip_unauthorized_citations
    bad='src_bbbbbbbbbbbbbbbb_c0002'
    assert bad not in strip_unauthorized_citations(f'[{bad}; see]',set(),set())

def test_nonproduct_vanilla_preserves_evidence_and_answer():
    import asyncio, json
    from app.research.vanilla import answer_vanilla
    from app.core.types import SourceChunk, Usage, RunMetrics
    cid='src_aaaaaaaaaaaaaaaa_c0001'; macro='{!example.py!}'
    class Fake:
        async def generate(self,*,system,user):
            self.prompt=user
            return type('R',(),{'text':json.dumps({'status':'COMPLETE','answer':macro,'citations':[cid],'missing_information':[]}),'usage':Usage()})()
    provider=Fake(); chunk=SourceChunk(chunk_id=cid,source_id='s',source_name='doc',text=macro,index=0)
    result=asyncio.run(answer_vanilla(provider,'q',[chunk],RunMetrics(),product=False))
    assert macro in provider.prompt and macro in result.answer and result.status=='COMPLETE'
