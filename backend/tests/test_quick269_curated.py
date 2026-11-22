import asyncio, json
from app.core.types import SourceChunk, RunMetrics, Usage
from app.research.vanilla import answer_vanilla
from app.research.worker import execute_task
from app.core.types import Task

GOOD='src_aaaaaaaaaaaaaaaa_c0001'
BAD='src_bbbbbbbbbbbbbbbb_c0002'
class Provider:
    def __init__(self, answer): self.answer=answer; self.prompt=''
    async def generate(self, *, system, user):
        self.prompt=user
        body={'status':'COMPLETE','answer':self.answer,'citations':[GOOD],'missing_information':[]}
        return type('Response',(),{'text':json.dumps(body),'usage':Usage()})()

def chunk():
    return SourceChunk(chunk_id=GOOD,source_id='src_aaaaaaaaaaaaaaaa',source_name='doc',text='Policy permits access. {!../../sensitive.py!}',index=0,provenance={'locator':{'section_path':['Policies','Access']}})

def test_quick_inline_scope_and_evidence_context():
    provider=Provider(f'Valid [{GOOD}], forbidden [{BAD}]; [note].')
    result=asyncio.run(answer_vanilla(provider,'policy',[chunk()],RunMetrics(),product=True))
    assert f'[{GOOD}]' in result.answer and f'[{BAD}]' not in result.answer and '[note]' in result.answer
    assert 'Policies > Access' in provider.prompt and '{!../../sensitive.py!}' not in provider.prompt

def test_worker_macro_output_is_inert_and_partial():
    provider=Provider('Use {!../../sensitive.py!} as code.')
    result=asyncio.run(execute_task(provider,Task(task_id='T1',goal='policy'),[chunk()],RunMetrics(),product=True))
    assert '{!' not in result.answer and result.status=='PARTIAL'

def test_telemetry_only_when_enabled(monkeypatch, capsys):
    from app.providers import ollama
    monkeypatch.setenv('OLLAMA_METRICS_LOG','1')
    logger=ollama.metrics_logger
    old=logger.handlers[:],logger.level,logger.propagate
    logger.handlers=[]
    try:
        ollama._configure_metrics_logging()
        logger.handlers[0].setStream(__import__('sys').stderr)
        ollama._log_response_metrics({'total_duration':123,'eval_count':5,'secret':'private','eval_duration':True})
        line=capsys.readouterr().err
        assert 'total_duration' in line and 'eval_count' in line and 'private' not in line and 'eval_duration' not in line
    finally:
        logger.handlers,logger.level,logger.propagate=old

def test_stream_does_not_emit_before_final_guard():
    from app.research.progress import progress_sink
    from app.core.types import ProviderResult
    seen=[]
    class Streaming:
        supports_streaming=True
        async def generate_grounded(self, *, system, user, evidence_ids, on_text=None):
            raw=json.dumps({'status':'COMPLETE','answer':f'Bad [{BAD}]','citations':[GOOD],'missing_information':[]})
            if on_text: on_text(raw)
            return ProviderResult(text=raw,usage=Usage())
    async def run():
        token=progress_sink.set(seen.append)
        try: return await answer_vanilla(Streaming(),'policy',[chunk()],RunMetrics(),product=True)
        finally: progress_sink.reset(token)
    result=asyncio.run(run())
    assert not any(item.get('type') == 'answer' for item in seen)
    assert BAD not in result.answer
