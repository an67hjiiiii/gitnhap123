"""Offline checks for dev-only measurement identity and scope guards."""
import pytest
from scripts import measure_context_dev as measure
from app.core.types import SourceChunk


def test_gold_alias_requires_unique_exact_stem():
    row={'gold_pairs':'[{"tệp":"abc.pdf","Điều":5}]'}
    assert measure.gold_for(row,['abc.txt']) == {('abc.txt',5)}
    assert measure.gold_for(row,['abc.txt','abc.docx']) == {('abc.pdf',5)}


def test_article_uses_structural_heading_before_body_references():
    chunk=SourceChunk('c','s','x','Theo Điều 3 của văn bản cũ',0,
        provenance={'section_path':'Chương II > Điều 12. Quy định'})
    assert measure.article(chunk)==12


def test_immutable_manifest_accepts_identical_and_refuses_changed(tmp_path):
    path=tmp_path/'manifest.json'
    measure.write_once(path,{'config':'a'})
    before=path.read_bytes()
    measure.write_once(path,{'config':'a'})
    with pytest.raises(RuntimeError,match='Immutable evidence differs'):
        measure.write_once(path,{'config':'b'})
    assert path.read_bytes()==before


def test_independent_sample_excludes_followup_without_its_first_turn():
    rows=[{'id':'q1','ma_chuoi':'chain'},{'id':'q2','ma_chuoi':'chain'},
          {'id':'q3','ma_chuoi':''}]
    assert [r['id'] for r in measure.independent_rows(rows)]==['q1','q3']


@pytest.mark.parametrize('url',[
    'postgresql+psycopg://test:example@127.0.0.1:5432/dev',
    'postgresql+psycopg://test:example@127.0.0.1:55440/vtest_full',
])
def test_configuration_refuses_unapproved_database(monkeypatch,url):
    monkeypatch.setattr(measure.os,'environ',{'DATABASE_URL':url})
    with pytest.raises(RuntimeError,match='Only approved scratch database'):
        measure.configure()
