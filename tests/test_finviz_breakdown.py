"""Finviz page data that used to be downloaded and thrown away.

Two payloads on the *same* ``/stock?t=X`` page were being discarded:

* the ``income-breakdown-init-data-0`` island (revenue/expense table plus the
  product / region / segment revenue split), and
* the classification chips (sector, industry, country, market-cap class,
  exchange) whose markup finviz moved from ``screener?v=111&f=...`` to
  ``/screener/stocks?v=111&f=...``, silently blanking five fields per quote.

Both are pure parsers, so these tests use recorded markup and island payloads
rather than the network.
"""
from __future__ import annotations

import json

import pytest

from tapebasis.providers.finviz.core.errors import FinvizServiceError
from tapebasis.providers.finviz.core.services import quote_service
from tapebasis.providers.finviz.core.services.html_utils import parse_quote_header

# ── income-breakdown island ───────────────────────────────────────────────────


def _island(**revenue_axes):
    """A realistic island: statement in millions, revenue axes in dollars."""
    return {
        "statement": {
            "currency": "USD",
            "data": {
                "Period": ["2026FY", "2025FY"],
                "Total Revenue": ["478,834.00", "416,161.00"],
                "Gross Profit": ["233,602.00", "195,201.00"],
                "Operating Income": ["158,063.00", "133,050.00"],
                "Interest Expense": ["", ""],
            },
        },
        "revenue": revenue_axes
        or {
            "segment": {
                "unit": "USD",
                "converted": False,
                "revenues": {
                    "Americas": [
                        {"fiscal_year": "2025", "value": 178353000000},
                        {"fiscal_year": "2026", "value": 198083000000},
                    ],
                    "Europe": [
                        {"fiscal_year": "2025", "value": 111032000000},
                        {"fiscal_year": "2026", "value": 127604000000},
                    ],
                    "Greater China": [
                        {"fiscal_year": "2025", "value": 64377000000},
                        {"fiscal_year": "2026", "value": 82378000000},
                    ],
                    "Japan": [
                        {"fiscal_year": "2025", "value": 28703000000},
                        {"fiscal_year": "2026", "value": 30908000000},
                    ],
                    "Rest of Asia Pacific": [
                        {"fiscal_year": "2025", "value": 33696000000},
                        {"fiscal_year": "2026", "value": 39861000000},
                    ],
                },
            }
        },
    }


def test_statement_is_scaled_to_absolute_units():
    """The statement ships in millions; the island is served in one unit.

    Serving the raw ``"478,834.00"`` next to a segment reading of
    ``198083000000`` would hand an agent two figures for the same company that
    differ by six orders of magnitude.
    """
    shaped = quote_service.shape_income_breakdown(_island())
    assert shaped["statement"]["scale_applied"] == 1_000_000.0
    row = next(r for r in shaped["statement"]["rows"] if r["label"] == "Total Revenue")
    assert row["values"] == [478_834_000_000.0, 416_161_000_000.0]
    # It now agrees with the segment axis total for the same fiscal year.
    segment = shaped["revenue"]["axes"]["segment"]["series"]
    assert sum(v["2026"] for v in segment.values()) == pytest.approx(
        row["values"][0], rel=0.01
    )


def test_statement_and_revenue_share_one_scale_and_currency():
    shaped = quote_service.shape_income_breakdown(_island())
    assert shaped["statement"]["currency"] == "USD"
    assert shaped["statement"]["periods"] == ["2026FY", "2025FY"]
    assert shaped["revenue"]["axes"]["segment"]["unit"] == "USD"
    # Every year present anywhere is listed newest first.
    assert shaped["revenue"]["years"] == ["2026", "2025"]


def test_empty_cells_become_null_not_zero():
    """``""`` is "finviz had no number", which is not the same as 0."""
    shaped = quote_service.shape_income_breakdown(_island())
    row = next(
        r for r in shaped["statement"]["rows"] if r["label"] == "Interest Expense"
    )
    assert row["values"] == [None, None]


def test_bank_shaped_filer_keeps_its_own_row_set():
    """Banks have no Total Revenue row; the rows are served as they arrive."""
    island = {
        "statement": {
            "currency": "USD",
            "data": {
                "Period": ["2025FY", "2024FY"],
                "Operating Income": ["72,956.00", "75,821.00"],
                "Net Income": ["55,681.00", "56,868.00"],
                "Interest Income": ["193,341.00", "193,933.00"],
                "Loan Loss Provision": ["14,212.00", "10,678.00"],
                "Non-Interest Expense": ["94,003.00", "90,834.00"],
            },
        }
    }
    shaped = quote_service.shape_income_breakdown(island)
    labels = [r["label"] for r in shaped["statement"]["rows"]]
    assert "Total Revenue" not in labels
    assert "Loan Loss Provision" in labels
    assert "statement" in shaped
    assert "revenue" not in shaped


def test_converted_revenue_axes_stay_labelled():
    """``converted`` means finviz FX-converted the amounts; it must be visible."""
    island = _island(
        regions={
            "unit": "USD",
            "converted": True,
            "revenues": {
                "China": [
                    {"fiscal_year": "2024", "value": 11030690396.0},
                    {"fiscal_year": "2025", "value": 10737439080.66},
                ]
            },
        }
    )
    shaped = quote_service.shape_income_breakdown(island)
    axis = shaped["revenue"]["axes"]["regions"]
    assert axis["converted"] is True
    assert axis["unit"] == "USD"
    assert axis["series"]["China"]["2025"] == pytest.approx(10737439080.66)


def test_only_the_axes_finviz_sent_are_reported():
    """Apple has three axes, ASML two, JPM two, TD none. Nothing is invented."""
    island = _island(
        products_and_services={
            "unit": "USD",
            "converted": False,
            "revenues": {
                "Product": [{"fiscal_year": "2025", "value": 27604998612.54}]
            },
        }
    )
    shaped = quote_service.shape_income_breakdown(island)
    assert set(shaped["revenue"]["axes"]) == {"products_and_services"}


def test_unknown_axis_names_are_ignored_not_guessed():
    island = _island()
    island["revenue"]["something_new"] = {
        "unit": "USD",
        "converted": False,
        "revenues": {"X": [{"fiscal_year": "2026", "value": 5}]},
    }
    shaped = quote_service.shape_income_breakdown(island)
    assert "something_new" not in shaped["revenue"]["axes"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"statement": None, "revenue": None},
        {"statement": {"data": {}}, "revenue": {}},
        # An ETF: the island either is absent or carries nothing usable.
        {"revenue": {"segment": {"revenues": {}}}},
    ],
)
def test_absent_or_empty_island_returns_none(payload):
    """``None`` means "finviz has no breakdown", which is not an empty one."""
    assert quote_service.shape_income_breakdown(payload) is None


def test_malformed_entries_are_skipped_not_fatal():
    island = {
        "statement": {
            "currency": "USD",
            "data": {
                "Period": ["2026FY"],
                "Total Revenue": ["478,834.00"],
                "Broken": "not-a-list",
            },
        },
        "revenue": {
            "segment": {
                "unit": "USD",
                "converted": False,
                "revenues": {
                    "Good": [{"fiscal_year": "2026", "value": 1}],
                    "Bad": "not-a-list",
                    "Pointless": [{"no_year": True}, "junk"],
                },
            }
        },
    }
    shaped = quote_service.shape_income_breakdown(island)
    assert [r["label"] for r in shaped["statement"]["rows"]] == ["Total Revenue"]
    assert set(shaped["revenue"]["axes"]["segment"]["series"]) == {"Good"}


def test_suffix_in_a_statement_cell_is_not_silently_scaled():
    """A ``478.8B`` cell would be a format change; better to drop than guess."""
    island = _island()
    island["statement"]["data"]["Total Revenue"] = ["478.8B", "416,161.00"]
    shaped = quote_service.shape_income_breakdown(island)
    row = next(r for r in shaped["statement"]["rows"] if r["label"] == "Total Revenue")
    assert row["values"][0] is None
    assert row["values"][1] == 416_161_000_000.0


def test_parse_money_accepts_real_cell_shapes():
    assert quote_service._parse_money("1,234.50") == 1234.5
    assert quote_service._parse_money("-321.00") == -321.0
    assert quote_service._parse_money("") is None
    assert quote_service._parse_money("-") is None
    assert quote_service._parse_money(42) == 42.0
    assert quote_service._parse_money("n/a") is None


# ── the island reaches both quote tools ──────────────────────────────────────


class _FakePage:
    """Minimal page whose only meaningful content is the island."""

    def __init__(self, island):
        self.html = (
            '<h1 class="js-recent-quote-ticker" data-ticker="AAPL">AAPL</h1>'
            '<table class="js-snapshot-table"><tr>'
            '<td class="snapshot-td-label" data-boxover-html="Market cap">Market Cap</td>'
            "<td>4975.38B</td></tr></table>"
            + (
                '<script id="income-breakdown-init-data-0" type="application/json">'
                + json.dumps(island)
                + "</script>"
                if island is not None
                else ""
            )
        )


@pytest.fixture
def fake_page(monkeypatch):
    from tapebasis.providers.finviz.core.services import finviz_client

    state = {"page": _FakePage(_island())}

    async def fetch_html(url, **kwargs):
        return state["page"].html

    monkeypatch.setattr(finviz_client, "fetch_html", fetch_html)
    return state


@pytest.mark.asyncio
async def test_quote_carries_the_breakdown(fake_page):
    payload = await quote_service.get_quote("AAPL")
    breakdown = payload["income_breakdown"]
    assert breakdown["statement"]["scale_applied"] == 1_000_000.0
    assert "segment" in breakdown["revenue"]["axes"]


@pytest.mark.asyncio
async def test_snapshot_carries_the_breakdown_from_the_same_page(fake_page):
    """The fundamentals-only tool reads the island without a second request."""
    payload = await quote_service.get_snapshot("AAPL")
    assert payload["income_breakdown"]["revenue"]["axes"]


@pytest.mark.asyncio
async def test_quote_without_the_island_still_serves_the_quote(fake_page):
    """An ETF has no breakdown; the quote must not fail because of that."""
    fake_page["page"] = _FakePage(None)
    payload = await quote_service.get_quote("SPY")
    assert payload["income_breakdown"] is None
    assert payload["ticker"] == "AAPL"  # page header still parsed


# ── classification chips ─────────────────────────────────────────────────────

_CHIPS = (
    '<div class="quote-header_categories">'
    '<a href="/screener/stocks?v=111&f=sec_technology" class="quote-header_category">'
    "Technology</a>"
    '<a href="/screener/stocks?v=111&f=industry_consumerelectronics" '
    'class="quote-header_category" title="Consumer Electronics">'
    '<span class="min-w-0 truncate">Consumer Electronics</span></a>'
    '<a href="/screener/stocks?v=111&f=geo_usa" class="quote-header_category">USA</a>'
    '<a href="/screener/stocks?v=111&f=cap_mega" class="quote-header_category">Mega</a>'
    '<a href="/screener/stocks?v=111&f=exch_nasd" class="quote-header_category">NASD</a>'
    "</div>"
)


def test_current_chip_markup_is_parsed():
    """finviz moved the chips to ``/screener/stocks?...``; both forms are read."""
    header = parse_quote_header(_CHIPS)
    assert header["sector"] == "Technology"
    assert header["industry"] == "Consumer Electronics"
    assert header["country"] == "USA"
    assert header["market_cap_class"] == "Mega"
    assert header["exchange"] == "NASD"


def test_legacy_chip_markup_still_parses():
    legacy = (
        '<a href="screener?v=111&amp;f=sec_energy" class="quote-header_category">'
        "Energy</a>"
    )
    assert parse_quote_header(legacy)["sector"] == "Energy"


def test_etf_chip_is_its_own_field_not_a_sector():
    """An ETF is classified ``etf_sectype_*``; that is not a sector."""
    markup = (
        '<a href="/screener/etf?v=181&f=etf_sectype_exchangetradedfund" '
        'class="quote-header_category" title="Exchange Traded Fund">'
        '<span class="min-w-0 truncate">Exchange Traded Fund</span></a>'
    )
    header = parse_quote_header(markup)
    assert header["etf_type"] == "Exchange Traded Fund"
    assert header["sector"] is None


# ── dilution no longer impersonates a breakdown ──────────────────────────────


@pytest.mark.asyncio
async def test_dilution_refuses_to_substitute_an_income_statement(monkeypatch):
    """``stock_dilution`` used to answer with revenue data for 29 of 30 tickers."""
    from tapebasis.providers.finviz.core.services import finviz_client

    html = (
        '<script id="income-breakdown-init-data-0" type="application/json">'
        + json.dumps(_island())
        + "</script>"
    )

    async def fetch_html(url, **kwargs):
        return html

    monkeypatch.setattr(finviz_client, "fetch_html", fetch_html)
    with pytest.raises(FinvizServiceError) as excinfo:
        await quote_service.get_dilution("AAPL")
    assert excinfo.value.code.value == "NO_DATA"
    assert "income_breakdown" in str(excinfo.value)


@pytest.mark.asyncio
async def test_dilution_still_serves_a_real_model(monkeypatch):
    from tapebasis.providers.finviz.core.services import finviz_client

    model = {"schema_version": 1, "ticker": "CHPT", "company": {"shares_outstanding": 1}}
    html = (
        '<script id="route-init-data" type="application/json">'
        + json.dumps(model)
        + "</script>"
    )

    async def fetch_html(url, **kwargs):
        return html

    monkeypatch.setattr(finviz_client, "fetch_html", fetch_html)
    data = await quote_service.get_dilution("CHPT")
    assert data["model_available"] is True
    assert data["company"]["shares_outstanding"] == 1


@pytest.mark.asyncio
async def test_dilution_tool_reports_none_with_the_reason(monkeypatch):
    """A tool named for dilution must not answer with revenue data."""
    from tapebasis import fv_access, tools_finviz
    from tapebasis.providers_state import NoDataError

    async def no_model(symbol):
        # This is the shape ``fv_access.dilution`` actually raises: it translates
        # the provider's ``NO_DATA`` into ``NoDataError``. The tool must carry
        # that through as ``NO_DATA``, not degrade it to ``PROVIDER_ERROR``.
        raise NoDataError(
            "FINVIZ",
            "finviz.com has no dilution model for AAPL: it only builds one for "
            "companies whose share count it considers dilution-prone.",
        )

    monkeypatch.setattr(fv_access, "dilution", no_model)
    result = await tools_finviz.stock_dilution("AAPL")
    assert result["data_provider"] == "NONE"
    assert result["data"] is None
    assert result["errors"][0]["code"] == "NO_DATA"
    assert "dilution model" in result["errors"][0]["message"]
