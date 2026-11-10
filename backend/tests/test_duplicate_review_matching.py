from app.quality.fingerprints import ImageFacts
from app.quality.report import duplicate_report
from app.quality.review_models import pair_key


def test_exact_group_keeps_reviewed_pair_and_reports_remaining_duplicate():
    names = ["a", "b", "c"]
    digest = "a" * 64
    reviews = {pair_key("a", "b", digest, digest): "keep_both"}
    result = duplicate_report([(name, name) for name in names], [ImageFacts(digest)] * 3,
                              image_ids=names, reviews=reviews)

    assert [(issue.image_id, issue.related_image_id, issue.review_status) for issue in result.issues] == [
        ("c", "a", "pending"), ("a", "b", "confirmed"),
    ]
    assert {item.label: item.value for item in result.items} == {
        "精确重复": 2, "待审核": 1, "无效图片": 0, "分析图片": 3, "已确认重复": 1,
    }


def test_old_perceptual_review_and_changed_file_do_not_confirm_exact_duplicate():
    paths = [("a", "a"), ("b", "b")]
    first, second = "a" * 64, "b" * 64
    old_review = {pair_key("a", "b", first, second): "keep_both"}
    distinct = duplicate_report(paths, [ImageFacts(first), ImageFacts(second)], image_ids=["a", "b"], reviews=old_review)
    assert distinct.issues == []

    matching = duplicate_report(paths, [ImageFacts(first)] * 2, image_ids=["a", "b"], reviews=old_review)
    assert matching.issues[0].review_status == "pending"
    exact_review = {pair_key("a", "b", first, first): "keep_both"}
    changed = duplicate_report(paths, [ImageFacts(first), ImageFacts(second)], image_ids=["a", "b"], reviews=exact_review)
    assert changed.issues == []
