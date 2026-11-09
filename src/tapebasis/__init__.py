"""tapebasis: one MCP server, multiple market-data providers, cross-verified.

The server fans every overlapping request out to every upstream provider that
can serve it (TradingView, Finviz, Yahoo Finance, StockAnalysis and Bloomberg),
compares the answers, and labels each response with exactly one
:data:`data_provider` value:

``ALL``
    Every provider that was asked answered. This is a statement about
    *coverage*, not about agreement: agreement is reported separately in
    ``comparisons`` and summarised in ``notice``.
``TRADINGVIEW`` / ``FINVIZ`` / ``YAHOO`` / ``SA`` / ``BLOOMBERG``
    Only that provider produced data. Served, but explicitly single-source.
    Bloomberg's quote pages are exchange-delayed, so its payload carries the
    delay and a print time derived from the intraday series. StockAnalysis
    covers US equities and ETFs only, and serves the same consolidated tape
    Yahoo does, so that pair is weak corroboration.
``NONE``
    No provider produced data.

Each provider is fetched natively and independently: a leg that quietly proxied
another provider would be worthless as a cross-check. Symbols are resolved per
provider dynamically, and every provider call is paced by a shared rate limiter.

See :mod:`tapebasis.reconcile` for the fan-out/comparison engine,
:mod:`tapebasis.ratelimit` for pacing, and :mod:`tapebasis.health` for the
upstream schema-drift monitor.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
