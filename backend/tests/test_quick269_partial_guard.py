import asyncio, json
from app.core.types import RunMetrics, TaskResult, Usage
from app.research.synthesizer import synthesize
from app.research.progress import ndjson_run

GOOD='src_aaaaaaaaaaaaaaaa_c0001'
BAD='src_bbbbbbbbbbbbbbbb_c0002'
class Fake:
    supports_per_call_output_tokens=True
    def __init__(self,text): self.text=text; self.calls=0
    async def generate_structured(self,**kwargs):
        self.calls+=1
        return type('R',(),{'text':json.dumps({'answer':self.text},ensure_ascii=False),'usage':Usage()})()
    async def generate(self,**kwargs):
        self.calls+=1
        return type('R',(),{'text':self.text,'usage':Usage()})()

def task(status='PARTIAL'):
    return TaskResult(task_id='T1',domain='general',status=status,answer='Allowed 12 days.',citations=[GOOD],evidence_ids=[GOOD])

def test_synthesis_flags_unsupported_numbers_articles_and_removes_inline_invalid_id():
    report={}
    provider=Fake(f'Điều 44 quy định 99 ngày [{GOOD}, {BAD}].')
    answer=asyncio.run(synthesize(provider,'policy',[task()],RunMetrics(),max_output_tokens=500,evidence_text='Điều 5 quy định 12 ngày.',guard_report=report))
    assert BAD not in answer and GOOD in answer
    assert report['partial'] is True
    assert '99' not in answer and '44' not in answer

def test_no_evidence_cannot_invent_final_citation():
    report={}; provider=Fake(f'Invented [{BAD}]')
    answer=asyncio.run(synthesize(provider,'policy',[TaskResult(task_id='T1',domain='general',status='NO_EVIDENCE',answer='',evidence_ids=[],citations=[])],RunMetrics(),max_output_tokens=500,evidence_text='',guard_report=report))
    assert BAD not in answer and provider.calls==0 and report['no_evidence'] is True

def test_valid_supported_number_and_citation_unchanged():
    report={}; provider=Fake(f'Điều 5 quy định 12 ngày [{GOOD}].')
    answer=asyncio.run(synthesize(provider,'policy',[task('COMPLETE')],RunMetrics(),max_output_tokens=500,evidence_text='Điều 5 quy định 12 ngày.',guard_report=report))
    assert '99' not in answer and '44' not in answer

def test_stream_done_contains_guarded_final_and_no_answer_event():
    async def run():
        report={}; provider=Fake(f'Điều 44 quy định 99 ngày [{BAD}].')
        async def job():
            answer=await synthesize(provider,'policy',[task()],RunMetrics(),max_output_tokens=500,evidence_text='Điều 5 quy định 12 ngày.',guard_report=report)
            return {'status':'PARTIAL' if report['partial'] else 'COMPLETE','answer':answer}
        return [json.loads(x) async for x in ndjson_run(job)]
    events=asyncio.run(run())
    assert len(events)==1 and events[0]['type']=='done'
    assert BAD not in events[0]['run']['answer'] and events[0]['run']['status']=='PARTIAL'

def test_existing_synthesis_inline_citation_bypass():
    answer=asyncio.run(synthesize(Fake(f'Allowed [{GOOD}], forbidden [{BAD}]'), 'policy',[task()],RunMetrics(),max_output_tokens=500,evidence_text='Allowed 12 days.'))
    assert BAD not in answer

def test_existing_synthesis_all_no_evidence_must_not_generate():
    provider=Fake(f'Invented [{BAD}]')
    asyncio.run(synthesize(provider,'policy',[TaskResult(task_id='T1',domain='general',status='NO_EVIDENCE',answer='',evidence_ids=[],citations=[])],RunMetrics(),max_output_tokens=500,evidence_text=''))
    assert provider.calls==0

def test_partial_worker_result_marks_unsupported_number():
    from app.research.worker import execute_task
    from app.core.types import SourceChunk, Task
    class WorkerFake:
        async def generate(self,**kwargs):
            return type('R',(),{'text':json.dumps({'status':'PARTIAL','answer':'99 days','citations':[GOOD],'missing_information':[]}),'usage':Usage()})()
    evidence=[SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text='12 days',index=0)]
    result=asyncio.run(execute_task(WorkerFake(),Task(task_id='T1',goal='compare'),evidence,RunMetrics(),product=True))
    assert result.status=='PARTIAL' and '99 days' not in result.answer

def test_quick_article_mismatch_cannot_be_complete():
    from app.research.vanilla import answer_vanilla
    from app.core.types import SourceChunk
    class QuickFake:
        async def generate(self,**kwargs):
            return type('R',(),{'text':json.dumps({'status':'COMPLETE','answer':'Theo Điều 3.','citations':[GOOD],'missing_information':[]},ensure_ascii=False),'usage':Usage()})()
    evidence=[SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text='Điều 5 quy định chung.',index=0)]
    result=asyncio.run(answer_vanilla(QuickFake(),'policy',evidence,RunMetrics(),product=True))
    assert result.status=='PARTIAL'

def test_single_digit_unsupported_number_is_not_clean_complete():
    from app.research.worker import execute_task
    from app.core.types import SourceChunk, Task
    class WorkerFake:
        async def generate(self,**kwargs):
            return type('R',(),{'text':json.dumps({'status':'COMPLETE','answer':'7 days','citations':[GOOD],'missing_information':[]}),'usage':Usage()})()
    evidence=[SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text='12 days',index=0)]
    result=asyncio.run(execute_task(WorkerFake(),Task(task_id='T1',goal='compare'),evidence,RunMetrics(),product=True))
    assert result.status=='PARTIAL' and '7 days' not in result.answer

def test_actual_quick_pipeline_stream_persists_only_guarded_partial(monkeypatch):
    import app.research.pipeline as pipe_module
    from app.core.types import SourceChunk
    source=SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text='Điều 5 quy định 12 ngày.',index=0)
    class Source:
        def snapshot_id(self): return 'snapshot'
        def chunks(self,source_ids): return [source]
        def validate_source_selection(self,source_ids): assert source_ids==['source']
    class Runs:
        def __init__(self): self.saved=[]
        def save(self,run): self.saved.append(run)
    class FakeQuick:
        name='fake'; model='fake'; supports_streaming=True
        async def generate_grounded(self,**kwargs):
            raw=json.dumps({'status':'COMPLETE','answer':f'Theo Điều 3 trong 99 ngày [{BAD}].','citations':[GOOD],'missing_information':[]},ensure_ascii=False)
            if kwargs.get('on_text'): kwargs['on_text'](raw)
            return type('R',(),{'text':raw,'usage':Usage()})()
    monkeypatch.setattr(pipe_module,'get_provider',lambda _:FakeQuick())
    for name in ('process_rss_mb','gpu_memory_mb','cpu_times','model_rss_mb'):
        monkeypatch.setattr(pipe_module,name,lambda:None)
    monkeypatch.setattr(pipe_module,'cpu_busy_percent',lambda _:None)
    runs=Runs(); pipeline=pipe_module.ResearchPipeline(Source(),runs)
    monkeypatch.setattr(pipeline,'_retrieve_candidates',lambda *args,**kwargs:[source])
    async def run():
        return [json.loads(x) async for x in ndjson_run(lambda:pipeline.run('policy',condition='A',product_mode=True,source_ids=['source']))]
    events=asyncio.run(run())
    assert not any(e['type']=='answer' for e in events)
    done=events[-1]; assert done['type']=='done' and done['run']['status'] in ('PARTIAL','NO_EVIDENCE')
    assert BAD not in done['run']['answer'] and '99' not in done['run']['answer']
    assert runs.saved[-1]['answer']==done['run']['answer'] and runs.saved[-1]['status']==done['run']['status']

def test_same_number_wrong_unit_cannot_be_clean_complete():
    report={}; provider=Fake(f'Thời hạn là 12 tuần [{GOOD}].')
    answer=asyncio.run(synthesize(provider,'policy',[task('COMPLETE')],RunMetrics(),max_output_tokens=500,evidence_text='Thời hạn là 12 ngày.',guard_report=report))
    assert report['partial'] is True and '12 tuần' not in answer

def test_budget_break_cannot_report_complete(monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "dev")
    import app.research.pipeline as mod
    from app.core.types import SourceChunk, Task, TaskPlan, ObligationConcernExtraction
    from types import SimpleNamespace
    source=SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text='12 days',index=0)
    class Source:
        def snapshot_id(self): return 'snapshot'
        def chunks(self,ids): return [source]
    class Runs:
        def __init__(self): self.saved=[]
        def save(self,run): self.saved.append(run)
    class Provider:
        name='fake'; model='fake'
        async def generate(self,**kwargs):
            data={'status':'COMPLETE','answer':'12 days','citations':[GOOD],'missing_information':[]} if 'WORKER.' in kwargs['system'] else {'answer':'12 days'}
            return type('R',(),{'text':json.dumps(data),'usage':Usage(input_tokens=999999) if 'WORKER.' in kwargs['system'] else Usage()})()
    async def extraction(*a,**kw): return ObligationConcernExtraction()
    tasks=[Task(task_id='T1',goal='first'),Task(task_id='T2',goal='second')]
    async def decompose(*a,**kw): return SimpleNamespace(plan=TaskPlan(request='compare',tasks=tasks),status='COMPLETE',repair_attempted=False,warnings=[])
    monkeypatch.setattr(mod,'get_provider',lambda _:Provider())
    monkeypatch.setattr(mod,'extract_obligations_and_concerns',extraction)
    monkeypatch.setattr(mod,'decompose_plan',decompose)
    monkeypatch.setattr(mod,'is_simple_project_question',lambda *a:False)
    from app.research.plan_verification import PlanVerification
    monkeypatch.setattr(mod,'verify_task_plan',lambda _:PlanVerification(valid=True))
    monkeypatch.setattr(mod,'decide_repair',lambda *a,**k:SimpleNamespace(action='ACCEPT'))
    for name in ('process_rss_mb','gpu_memory_mb','cpu_times','model_rss_mb'): monkeypatch.setattr(mod,name,lambda:None)
    monkeypatch.setattr(mod,'cpu_busy_percent',lambda _:None)
    store=Runs(); pipeline=mod.ResearchPipeline(Source(),store)
    monkeypatch.setattr(pipeline,'_retrieve_candidates',lambda *args,**kwargs:[source])
    result=asyncio.run(pipeline.run('compare two obligations',condition='B',product_mode=True))
    assert result['status']=='PARTIAL' and len(result['task_results'])==1, result['answer']
    assert store.saved[-1]['status']=='PARTIAL'



def test_contradictory_claim_with_same_number_must_not_be_complete(monkeypatch):
    run=_pipeline_claim_case(monkeypatch,'The policy prohibits 12 days of leave.',f'The policy requires 12 days of leave [{GOOD}].')
    assert run['status'] in ('PARTIAL','NO_EVIDENCE') and 'requires 12 days' not in json.dumps(run)


def _pipeline_claim_case(monkeypatch, evidence_text, answer):
    import app.research.pipeline as mod
    from app.core.types import SourceChunk
    from app.research.progress import ndjson_run
    source=SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text=evidence_text,index=0)
    class Sources:
        def snapshot_id(self): return 'snapshot'
        def chunks(self,ids): return [source]
        def validate_source_selection(self,ids): assert ids==['source']
    class Runs:
        def __init__(self): self.saved=[]
        def save(self,run): self.saved.append(run)
    class Provider:
        name='fake'; model='fake'; supports_streaming=True
        async def generate_grounded(self,**kwargs):
            data={'status':'COMPLETE','answer':answer,'citations':[GOOD],'missing_information':[]}
            return type('R',(),{'text':json.dumps(data,ensure_ascii=False),'usage':Usage()})()
    monkeypatch.setattr(mod,'get_provider',lambda _:Provider())
    for name in ('process_rss_mb','gpu_memory_mb','cpu_times','model_rss_mb'): monkeypatch.setattr(mod,name,lambda:None)
    monkeypatch.setattr(mod,'cpu_busy_percent',lambda _:None)
    runs=Runs(); pipeline=mod.ResearchPipeline(Sources(),runs)
    monkeypatch.setattr(pipeline,'_retrieve_candidates',lambda *args,**kwargs:[source])
    async def collect():
        return [json.loads(x) async for x in ndjson_run(lambda:pipeline.run('policy',condition='A',product_mode=True,source_ids=['source']))]
    events=asyncio.run(collect())
    assert not any(e['type']=='answer' for e in events)
    assert events[-1]['type']=='done' and events[-1]['run']==runs.saved[-1]
    return events[-1]['run']


def test_final_boundary_removes_uncited_factual_claim(monkeypatch):
    run=_pipeline_claim_case(monkeypatch,'Employees may request twelve days of leave.',f'Managers own electric aircraft. [{GOOD}]')
    assert run['status'] in ('PARTIAL','NO_EVIDENCE')
    assert 'electric aircraft' not in json.dumps(run,ensure_ascii=False)
    assert [event['status'] for event in run['events'] if event['stage']=='run_finished'] == [run['status']]
    assert any('support' in x.lower() for r in run['task_results'] for x in r['missing_information'])


def test_final_boundary_preserves_supported_paraphrase(monkeypatch):
    statement='Employees can request twelve days of leave.'
    run=_pipeline_claim_case(monkeypatch,'Employees may request twelve days of leave.',f'{statement} [{GOOD}]')
    assert run['status']=='COMPLETE' and statement in run['answer']

def test_no_evidence_provider_cannot_publish_fabricated_answer(monkeypatch):
    import app.research.pipeline as mod
    from app.core.types import SourceChunk
    source=SourceChunk(chunk_id=GOOD,source_id='source',source_name='doc',text='Allowed leave is twelve days.',index=0)
    class Sources:
        def snapshot_id(self): return 'snapshot'
        def chunks(self,ids): return [source]
    class Runs:
        def __init__(self): self.saved=[]
        def save(self,run): self.saved.append(run)
    class Provider:
        name='fake'; model='fake'
        async def generate(self,**kwargs):
            data={'status':'NO_EVIDENCE','answer':'Managers own electric aircraft.','citations':[GOOD],'missing_information':[]}
            return type('R',(),{'text':json.dumps(data),'usage':Usage()})()
    monkeypatch.setattr(mod,'get_provider',lambda _:Provider())
    for name in ('process_rss_mb','gpu_memory_mb','cpu_times','model_rss_mb'): monkeypatch.setattr(mod,name,lambda:None)
    monkeypatch.setattr(mod,'cpu_busy_percent',lambda _:None)
    runs=Runs(); pipeline=mod.ResearchPipeline(Sources(),runs)
    monkeypatch.setattr(pipeline,'_retrieve_candidates',lambda *args,**kwargs:[source])
    run=asyncio.run(pipeline.run('policy',condition='A',product_mode=True))
    assert run['status']=='NO_EVIDENCE' and 'electric aircraft' not in json.dumps(run)
    assert run['task_results'][0]['citations']==[]
