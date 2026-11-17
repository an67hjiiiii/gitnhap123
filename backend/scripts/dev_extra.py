"""Kiểm luật và phân loại tín hiệu; không gọi mô hình, không chấm đúng/sai."""
import csv, json, re, statistics, unicodedata, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from check_reference_answers import atoms, references
sys.path.insert(0,'D:/CAP1-Worktrees/p3/combo/backend')
from app.chat.intent import classify_intent
R=Path('D:/CAP1-Orchestration/work'); O=R/'p3/lo_day_du'; D=O/'dev_run'

def readcsv(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def writecsv(p,rows,fields):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def tokens(s):
    s=unicodedata.normalize('NFC',s or '').replace('\u00a0',' ')
    # Normalize common cardinal words and decimal trailing zeros via atoms().
    for a,b in [('một năm','12 tháng'),('một giờ','60 phút'),('một ngày','1 ngày')]:s=re.sub(a,b,s,flags=re.I)
    return {(k,str(v)):label for k,v,label in atoms(s)}

def md(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+''.join('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in row)+' |\n' for row in rows)

def main():
    records=[json.loads(x) for x in (D/'results.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    dev={x['id']:x for x in readcsv(R/'p3/bo_cau_hoi/dev.csv')}
    labels={x['id']:x for x in readcsv(R/'p3/bo_cau_hoi/kiem_dap_an.csv')}
    snap=json.loads((O/'snapshot.json').read_text(encoding='utf-8'))
    chunks={c['chunk_id']:c for c in snap['knowledge_chunks']}
    runs=defaultdict(list)
    for r in snap['runs']:runs[r['query']].append(r)
    for rr in runs.values():rr.sort(key=lambda x:x['created_at'])
    checked=[]; classes=[]; groups=defaultdict(list); details=[]
    unavailable={20,54,56,59,5185}
    inconsistent=set()
    content=defaultdict(list)
    for r in records:content[r['nhom_noi_dung']].append(r)
    # Different prompts sharing a topic need not have identical numbers. Only
    # flag differing answer atoms when the reference atom sets are identical.
    for rr in content.values():
        subsets=defaultdict(list)
        for x in rr:subsets[tuple(sorted(tokens(x['dap_an_tham_khao'])))].append(x)
        for subset in subsets.values():
            if len(subset)>1 and len({tuple(sorted(tokens(x['answer']))) for x in subset})>1:
                inconsistent.update(x['id'] for x in subset)
    for r in records:
        rid=r['id']; l=labels.get(rid,{}).get('nhan','khong_nhan'); groups[l].append(r)
        ref=tokens(r['dap_an_tham_khao']); ans=tokens(r['answer'])
        missing={k:v for k,v in ref.items() if k not in ans}
        rule=('thieu' if missing else 'co_du') if l in ('khop','tinh_toan') else 'khong_kiem'
        checked.append({'id':rid,'nhan':l,'kiem_luat':rule,'so_ngay_tham_khao':'; '.join(ref.values()),'thieu':'; '.join(missing.values()) if rule!='khong_kiem' else ''})
        run=next((x for x in runs[r['cau_hoi']] if x.get('answer')==r['answer']),None)
        if run is None and runs[r['cau_hoi']]:run=runs[r['cau_hoi']][0]
        run=run or {}; events=run.get('events',[])
        intent_rule=classify_intent(r['cau_hoi'],has_history=bool(r.get('ma_chuoi') and r.get('luot')!='1'))
        selected=next((e.get('selected',[]) for e in events if e.get('stage')=='vanilla_retrieval'),[])
        selected_text='\n'.join(chunks.get(cid,{}).get('content') or '' for cid in selected if isinstance(cid,str))
        substantive_missing={k:v for k,v in missing.items() if k[0] in ('number','date')}
        absent_evidence={k:v for k,v in substantive_missing.items() if k not in tokens(selected_text)}
        refs=references(dev[rid].get('van_ban_nguon','')+' '+r['dap_an_tham_khao'])
        src_missing=bool({n for n,y in refs}&unavailable)
        notes=r.get('guard_notes',[])
        guard_drop=any(any(k in str(n).lower() for k in ('removed','number','số','numeric')) for n in notes)
        nofound='chưa tìm thấy' in r['answer'].lower()
        signals=[]
        if rule=='thieu':signals.append('kiểm luật thiếu')
        if nofound:signals.append('chưa tìm thấy')
        if r['http']=='timeout':signals.append('timeout')
        if guard_drop:signals.append('guard bỏ số')
        if rid in inconsistent:signals.append('nhất quán lệch')
        label=''; evidence=''
        toprefs=set()
        for x in r.get('top5',[]):toprefs.update(references(x))
        if src_missing:
            label='nguon_khong_nap'; evidence='Đáp án dẫn văn bản '+', '.join(str(n) for n,y in refs if n in unavailable)+' thuộc danh sách không nạp; loại khỏi lỗi hệ thống.'
        elif signals:
            if r['http']=='timeout':
                label='mô_hình'; evidence='HTTP timeout sau '+str(r['secs'])+'s; nghi llm, chưa đủ events để kết luận nguyên nhân.'
            elif guard_drop:
                label='guard'; evidence='answer_guard notes: '+str(notes)
            elif not run and intent_rule.intent=='general_knowledge':
                label='ý_định'; evidence='Không có pipeline run/top-5; chạy lại quy tắc classify_intent cục bộ cho kết quả '+intent_rule.intent+'/'+intent_rule.reason+' (không gọi LLM).'
            elif refs and not (set(refs)&toprefs):
                label='truy_hồi'; evidence='Top-5 không có văn bản dẫn trong đáp án tham khảo: '+str(refs)+'; top5='+str(r.get('top5',[]))
            elif rule=='thieu' and missing and all(k[0] in ('reference','article','clause') for k in missing):
                label='trình_bày'; evidence='Kiểm luật chỉ thiếu định danh/trích dẫn: '+'; '.join(missing.values())
            elif rule=='thieu' and absent_evidence and selected:
                label='truy_hồi'; evidence='Có văn bản nguồn nhưng các số/ngày thiếu cũng không có trong các đoạn selected: '+'; '.join(absent_evidence.values())
            elif any('version' in str(e.get('stage','')) and e.get('error') for e in events):
                label='phiên_bản'; evidence='Event phiên bản có lỗi: '+str([e for e in events if 'version' in str(e.get('stage',''))])
            else:
                label='mô_hình'; evidence=('Top-5 có văn bản nguồn; kiểm luật thiếu: '+'; '.join(missing.values())) if rule=='thieu' else 'Có nguồn trong top-5; tín hiệu: '+', '.join(signals)
        if label:classes.append({'id':rid,'nhan_chinh':label,'dau_hieu':'; '.join(signals),'bang_chung':evidence})
        metrics=run.get('metrics',{}); stages=[e.get('stage') for e in events]
        details.append({'id':rid,'run_id':run.get('run_id'),'metrics':metrics,'events':events,'suspect':('llm' if metrics.get('generation_latency_ms',0)>metrics.get('retrieval_latency_ms',0) else 'vanilla_retrieval') if r['secs']>26 else ''})
    writecsv(D/'kiem_luat.csv',checked,['id','nhan','kiem_luat','so_ngay_tham_khao','thieu'])
    writecsv(D/'phan_loai.csv',classes,['id','nhan_chinh','dau_hieu','bang_chung'])
    (D/'events_metrics.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    group_rows=[]
    groups.setdefault('tinh_toan',[])
    for k,rr in sorted(groups.items()):
        cc=Counter(x['kiem_luat'] for x in checked if x['nhan']==k)
        group_rows.append((k,len(rr),sum(x['http']=='timeout' for x in rr),round(statistics.mean(x['secs'] for x in rr),3) if rr else '—',cc['co_du'],cc['thieu']))
    (D/'theo_nhan.md').write_text(md(['Nhãn tham khảo','Câu','Timeout','Giây TB','kiểm luật co_du','kiểm luật thieu'],group_rows),encoding='utf-8')
    first=[r['id'] for r in dev.values() if not r['ma_chuoi'].strip() or r['luot'].strip()=='1'][:20]
    speed=[r['secs'] for r in records if r['id'] in first and r['http']==200]
    stats={'dev':len(records),'http':dict(Counter(str(r['http']) for r in records)),'kiem_luat':dict(Counter(x['kiem_luat'] for x in checked)), 'phan_loai':dict(Counter(x['nhan_chinh'] for x in classes)),'speed_first20':{'n':len(speed),'mean':statistics.mean(speed) if speed else None,'median':statistics.median(speed) if speed else None,'max':max(speed) if speed else None,'ids':first},'speed_all':{'mean':statistics.mean(r['secs'] for r in records),'median':statistics.median(r['secs'] for r in records),'max':max(r['secs'] for r in records)},'inconsistent_ids':sorted(inconsistent),'group_rows':group_rows}
    (D/'extra_stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
