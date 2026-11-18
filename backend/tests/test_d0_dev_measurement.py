from scripts.measure_d0_dev import old_article, scoring
from app.core.types import SourceChunk


def test_controlled_article_and_filename_matchers():
    chunk = SourceChunk('c', 's', 'abc.txt', 'Theo Điều 3 văn bản cũ', 0,
                        provenance={'section_path': 'Điều 12. Quy định'})
    gold = [{'tệp': 'abc.pdf', 'Điều': 12}]
    assert old_article(chunk) == 3
    assert scoring([chunk], gold, ['abc.txt'])['10'] == 1
    assert scoring([chunk], gold, ['abc.txt'], heading=False)['10'] == 0
    assert scoring([chunk], gold, ['abc.txt'], alias=False)['10'] == 0


def test_ambiguous_filename_alias_cannot_score():
    chunk = SourceChunk('c', 's', 'abc.txt', 'Điều 12', 0)
    assert scoring([chunk], [{'tệp': 'abc.pdf', 'Điều': 12}], ['abc.txt', 'abc.docx'])['20'] == 0
