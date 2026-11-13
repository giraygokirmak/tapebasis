"""Tests for the token-free local sentiment scorer (no network, no API key)."""
from __future__ import annotations

import pytest

from tapebasis import sentiment


# ── lexicon behaviour ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "headline,expected_sign",
    [
        ("Apple beats estimates, raises guidance, shares surge", 1),
        ("Analysts downgrade Apple on iPhone demand concerns", -1),
        ("Apple stock drops on weak margin forecast", -1),
        ("Apple announces $100B buyback, dividend raised 4%", 1),
        ("Apple plunges after recall and lawsuit", -1),
        ("Apple Q4 earnings beat, revenue tops expectations", 1),
    ],
)
def test_finance_vocabulary_gets_the_direction_right(headline, expected_sign):
    """Plain VADER scores most of these neutral; the overlay must not."""
    score = sentiment.score_text(headline)
    assert score != 0.0
    assert (score > 0) is (expected_sign > 0)


def test_neutral_headline_stays_neutral():
    assert sentiment.score_text("Apple: 3 Key Takeaways for Long-Term Investors") == pytest.approx(0.0)


def test_empty_input_scores_zero_instead_of_raising():
    assert sentiment.score_text("") == 0.0
    assert sentiment.score_text("   ") == 0.0
    assert sentiment.score_text(None) == 0.0


def test_scoring_is_deterministic():
    headline = "Nvidia surges after blowout quarter, analysts upgrade"
    assert sentiment.score_text(headline) == sentiment.score_text(headline)


@pytest.mark.parametrize(
    "score,label",
    [
        (0.9, "Strongly Bullish"),
        (0.1, "Bullish"),
        (0.0, "Neutral"),
        (-0.1, "Bearish"),
        (-0.9, "Strongly Bearish"),
    ],
)
def test_labels_match_the_documented_buckets(score, label):
    assert sentiment.label_for(score) == label


# ── aggregation ─────────────────────────────────────────────────────────────


def _rows():
    return [
        {"headline": "Apple beats estimates and raises guidance", "source": "A", "url": "u1"},
        {"headline": "Apple stock plunges on weak margins", "source": "B", "url": "u2"},
        {"headline": "Apple: 3 Key Takeaways for Long-Term Investors", "source": "C", "url": "u3"},
    ]


def test_aggregate_reports_counts_that_add_up():
    result = sentiment.score_headlines(
        _rows(), symbol="aapl", source_label="test feed"
    )
    assert result["symbol"] == "AAPL"
    assert result["posts_analyzed"] == 3
    total = (
        result["bullish_count"] + result["bearish_count"] + result["neutral_count"]
    )
    assert total == result["posts_analyzed"]


def test_aggregate_ranks_by_conviction_not_arrival_order():
    result = sentiment.score_headlines(
        _rows(), symbol="AAPL", source_label="test feed"
    )
    magnitudes = [abs(item["score"]) for item in result["top_posts"]]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_aggregate_is_explicit_that_scoring_is_local():
    result = sentiment.score_headlines(
        _rows(), symbol="AAPL", source_label="test feed"
    )
    assert result["provider"] == "local-vader"
    assert result["scoring"]["runs"] == "locally, no network, no API token"
    assert "vader" in result["scoring"]["engine"].lower()


def test_aggregate_of_only_neutral_headlines_is_neutral_not_unavailable():
    result = sentiment.score_headlines(
        [{"headline": "Apple: 3 Key Takeaways"}], symbol="AAPL", source_label="t"
    )
    assert result["sentiment_label"] == "Neutral"
    assert result["sentiment_score"] == pytest.approx(0.0)
    assert result["posts_analyzed"] == 1


def test_empty_headline_list_reports_zero_analyzed():
    result = sentiment.score_headlines([], symbol="AAPL", source_label="t")
    assert result["posts_analyzed"] == 0
    assert result["top_posts"] == []


def test_limit_is_respected():
    rows = [{"headline": f"Apple beats estimates {i}"} for i in range(10)]
    assert sentiment.score_headlines(rows, symbol="A", source_label="t", limit=3)["posts_analyzed"] == 3


def test_rows_without_a_title_are_skipped():
    rows = [{"headline": ""}, {"headline": None}, {"headline": "Apple beats estimates"}]
    assert sentiment.score_headlines(rows, symbol="A", source_label="t")["posts_analyzed"] == 1
