"""Direct provider-specific recommendation counts without identity lookups."""
from tapebasis.analyst import rating_summary


def test_summary_keeps_selected_provider_population_and_zero_buckets():
    """Counts do not need names or borrow a total from another population."""
    assert rating_summary(
        {
            "rating_analyst_count": 73,
            "rating_period": "past 3 months",
            "rating_distribution": {
                "strong_buy": 49,
                "buy": 5,
                "hold": 17,
                "sell": 0,
                "strong_sell": 2,
            },
            "rating_distribution_method": "scanner_rating_buckets",
            "rating_label_counts": {
                "Strong Buy": 49, "Buy": 5, "Hold": 17, "Sell": 0, "Strong Sell": 2,
            },
        },
        count_key="rating_analyst_count",
        population="past_three_month_rating_analysts",
    ) == {
        "total": 73,
        "population": "past_three_month_rating_analysts",
        "distribution": {
            "strong_buy": 49,
            "buy": 5,
            "hold": 17,
            "sell": 0,
            "strong_sell": 2,
        },
        "label_counts": {
            "Strong Buy": 49, "Buy": 5, "Hold": 17, "Sell": 0, "Strong Sell": 2,
        },
        "unlabeled_row_count": None,
        "rating_period": "past 3 months",
        "includes_previous_ratings": None,
        "rating_distribution_method": "scanner_rating_buckets",
    }


def test_finviz_summary_counts_all_visible_rows_including_unclassified():
    """The visible-row total and every class match without naming a firm."""
    assert rating_summary(
        {
            "rating_action_count": 20,
            "rating_firm_count": 16,
            "rating_label_counts": {
                "Buy": 4, "Overweight": 3, "Hold": 8, "Mkt Perform": 2,
                "Sector Weight": 1, "In-line": 1, "Special New Rating": 1,
            },
            "unlabeled_row_count": 0,
            "rating_distribution": {
                "buy": 7,
                "hold": 12,
                "sell": 0,
                "no_rating": 0,
                "unclassified": 1,
            },
            "rating_distribution_method": "visible_rating_rows_final_labels",
            "includes_previous_ratings": True,
        },
        count_key="rating_action_count",
        population="visible_rating_rows_final_labels",
    ) == {
        "total": 20,
        "population": "visible_rating_rows_final_labels",
        "distribution": {
            "buy": 7,
            "hold": 12,
            "sell": 0,
            "no_rating": 0,
            "unclassified": 1,
        },
        "label_counts": {
            "Buy": 4, "Overweight": 3, "Hold": 8, "Mkt Perform": 2,
            "Sector Weight": 1, "In-line": 1, "Special New Rating": 1,
        },
        "unlabeled_row_count": 0,
        "rating_period": None,
        "includes_previous_ratings": True,
        "rating_distribution_method": "visible_rating_rows_final_labels",
    }


def test_empty_exact_labels_are_not_inferred_from_broad_categories():
    """Unlabeled Finviz rows remain blank rather than becoming invented labels."""
    summary = rating_summary(
        {
            "rating_action_count": 2,
            "rating_label_counts": {},
            "unlabeled_row_count": 2,
            "rating_distribution": {
                "buy": 0, "hold": 0, "sell": 0, "no_rating": 0, "unclassified": 2,
            },
            "rating_distribution_method": "visible_rating_rows_final_labels",
        },
        count_key="rating_action_count",
        population="visible_rating_rows_final_labels",
    )
    assert summary is not None
    assert summary["label_counts"] == {}
    assert summary["unlabeled_row_count"] == 2


def test_no_observation_is_not_fabricated_from_another_provider():
    """Missing or all-null provider observations never create a summary."""
    assert rating_summary(
        {}, count_key="rating_action_count", population="visible_rating_rows_final_labels"
    ) is None
    assert rating_summary(
        {"rating_distribution": {
            "strong_buy": None, "buy": None, "hold": None,
            "sell": None, "strong_sell": None,
        }},
        count_key="rating_analyst_count",
        population="past_three_month_rating_analysts",
    ) is None
