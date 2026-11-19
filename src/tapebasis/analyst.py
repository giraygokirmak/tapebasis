"""Provider-scoped analyst rating summaries without shared populations."""
from __future__ import annotations

from typing import Any


def rating_summary(
    block: dict[str, Any], *, count_key: str, population: str
) -> dict[str, Any] | None:
    """Return one provider's total, exact label counts and grouped categories.

    ``label_counts`` preserves the provider's exact classes when supplied.
    TradingView's five scanner bucket keys serve as its label map only when no
    exact-label map is provided; Finviz keeps actual labels such as Overweight,
    In-line and Mkt Perform before its broad Buy,
    Hold and Sell grouping. ``unlabeled_row_count`` permits reconciliation for
    blank last labels and stays null where the provider offers no such concept.
    No institution or analyst name is needed to calculate or consume the result.

    The total belongs to the explicitly named population. It is never filled
    from another provider, inferred from categories or equated with a firm
    count. An absent rating observation, even an all-null scanner distribution,
    returns no summary rather than zeroes. Real zero buckets keep a summary.
    """
    total = block.get(count_key)
    distribution = block.get("rating_distribution")
    has_distribution = isinstance(distribution, dict) and any(
        value is not None for value in distribution.values()
    )
    if total is None and not has_distribution:
        return None
    label_counts = block.get("rating_label_counts")
    if label_counts is None:
        label_counts = distribution
    return {
        "total": total,
        "population": population,
        "distribution": distribution,
        "label_counts": label_counts,
        "unlabeled_row_count": block.get("unlabeled_row_count"),
        "rating_period": block.get("rating_period"),
        "includes_previous_ratings": block.get("includes_previous_ratings"),
        "rating_distribution_method": block.get("rating_distribution_method"),
    }
