"""カード名のあいまい照合(OCR結果→カード特定)のテスト."""
from svtracker.cards.card_database import CardDatabase
from svtracker.cards.models import Card
from svtracker.cards.name_matcher import NameMatcher, normalize_name, similarity


def _db() -> CardDatabase:
    db = CardDatabase()
    for cid, name in [
        ("1", "ストームブラスト"),
        ("2", "レ・フィーエの宝石"),
        ("3", "エターナルクリスタリア・ティア"),
        ("4", "二刀のゴブリン"),
    ]:
        db.add(Card(card_id=cid, name=name, clan="ニュートラル", cost=1, card_type="スペル"))
    return db


def test_normalize_removes_middot_and_space():
    assert normalize_name("レ・フィーエの宝石") == "レフィーエの宝石"
    assert normalize_name("エターナル クリスタリア・ティア") == "エターナルクリスタリアティア"


def test_exact_name_matches_with_ratio_1():
    matcher = NameMatcher(_db())
    result = matcher.match("ストームブラスト")
    assert result is not None
    assert result[0].card_id == "1"
    assert result[1] == 1.0


def test_ocr_with_missing_middot_still_matches():
    # OCRが中黒を落としても照合できる
    matcher = NameMatcher(_db())
    result = matcher.match("レフィーエの宝石")
    assert result is not None
    assert result[0].card_id == "2"


def test_ocr_with_minor_error_matches_closest():
    # 1文字誤読でも最も近いカードに一致する
    matcher = NameMatcher(_db())
    result = matcher.match("二刀のゴプリン")  # ブ→プ の誤読
    assert result is not None
    assert result[0].card_id == "4"


def test_unrelated_text_below_threshold_returns_none():
    matcher = NameMatcher(_db())
    assert matcher.match("まったく無関係な文字列xyz", min_ratio=0.6) is None


def test_too_short_query_returns_none():
    matcher = NameMatcher(_db())
    assert matcher.match("あ") is None
    assert matcher.match("") is None
    assert matcher.match(None) is None


def test_similarity_symmetric_and_bounded():
    assert similarity("ストームブラスト", "ストームブラスト") == 1.0
    assert 0.0 <= similarity("二刀のゴブリン", "レ・フィーエの宝石") < 1.0
