from PIL import Image, ImageDraw

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.card_matcher import CardMatcher
from svtracker.cards.hashing import compute_phash_hex
from svtracker.cards.models import Card


def make_card_image(seed: int, size: int = 128) -> Image.Image:
    """種ごとに構造の異なる合成画像を作る(実カード画像の代わり)."""
    img = Image.new("RGB", (size, size), color=((seed * 37) % 255, (seed * 91) % 255, (seed * 53) % 255))
    draw = ImageDraw.Draw(img)
    cx, cy = (seed * 17) % size, (seed * 29) % size
    draw.ellipse(
        [cx - 20, cy - 20, cx + 20, cy + 20],
        fill=((seed * 61) % 255, (seed * 13) % 255, (seed * 97) % 255),
    )
    draw.rectangle([10, size - 30, size - 10, size - 10], fill=((seed * 7) % 255, 10, 200))
    return img


def build_database(n: int = 5) -> tuple[CardDatabase, dict[int, Image.Image]]:
    db = CardDatabase()
    images = {}
    for i in range(n):
        image = make_card_image(i)
        images[i] = image
        card = Card(
            card_id=str(i),
            name=f"テストカード{i}",
            clan="ニュートラル",
            cost=i,
            card_type="フォロワー",
            phash=compute_phash_hex(image, hash_size=16),
        )
        db.add(card)
    return db, images


def test_exact_match_returns_correct_card():
    db, images = build_database()
    matcher = CardMatcher(db, hash_size=16, max_distance=14)

    result = matcher.best_match(images[2])

    assert result is not None
    assert result.card.card_id == "2"
    assert result.distance == 0
    assert result.confidence == 1.0


def test_slightly_distorted_image_still_matches():
    db, images = build_database()
    matcher = CardMatcher(db, hash_size=16, max_distance=14)

    # 画面キャプチャによる縮小/拡大を模したわずかな劣化
    distorted = images[3].resize((96, 96)).resize((128, 128))

    result = matcher.best_match(distorted)

    assert result is not None
    assert result.card.card_id == "3"


def test_unrelated_image_is_rejected_with_strict_threshold():
    db, _ = build_database()
    matcher = CardMatcher(db, hash_size=16, max_distance=2)

    noise = Image.effect_noise((128, 128), 60).convert("RGB")

    result = matcher.best_match(noise)

    assert result is None


def test_match_returns_ranked_candidates():
    db, images = build_database()
    matcher = CardMatcher(db, hash_size=16, max_distance=14)

    results = matcher.match(images[4], top_k=3)

    assert len(results) == 3
    assert results[0].card.card_id == "4"
    # 距離は昇順(=一致度が高い順)
    assert results[0].distance <= results[1].distance <= results[2].distance
