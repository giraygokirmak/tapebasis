"""
HTML → dict parsers for the finviz.com document routes.

Everything here is pure and synchronous: give it the exact markup finviz.com
serves today and it returns plain Python data. Keeping parsing in one module
means a finviz redesign breaks exactly one file, and the services above it stay
readable.

Anchor notes (as of the redesign captured for this server)
----------------------------------------------------------
* ``div.quote-header``          : ticker, company, last/after-hours price,
                                   sector/industry/country/cap/exchange chips.
* ``table.js-snapshot-table``   : the 84-field fundamentals snapshot, split
                                   across 6 tables on one page. Each row holds
                                   label/value ``<td>`` pairs; the label cell
                                   carries ``data-boxover-html`` with the
                                   human-readable metric description.
* ``div.quote_profile-bio``     : company description paragraph.
* ``table.fullview-links``      : the Peers row; each peer is a
                                   ``span[data-boxover-ticker]``.
* ``table.news-table``          : 100-row headline table (also returned by
                                   ``/api/news/quote/{t}`` as ``{"html": ...}``).
* ``table.styled-table-new``    : insider trading rows (9 columns).
"""
from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Optional

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_tags(markup: str) -> str:
    """Remove tags and collapse whitespace, decoding HTML entities."""
    if not markup:
        return ""
    text = _TAG_RE.sub(" ", markup)
    text = html_lib.unescape(text).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def extract_script_json(html: str, script_id: str) -> Optional[Any]:
    """Return the parsed JSON payload of ``<script id="{script_id}">``.

    Finviz suffixes repeat blocks with an index (``route-init-data``,
    ``fa-init-data-0``), so the match is a *prefix* match on the id. Returns
    ``None`` when the block is absent or holds invalid JSON; callers decide
    whether that is fatal.
    """
    pattern = re.compile(
        r'<script[^>]*\bid="' + re.escape(script_id) + r'[^"]*"[^>]*>(.*?)</script>',
        re.S,
    )
    match = pattern.search(html)
    if not match:
        return None
    raw = match.group(1).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def extract_ssr_island(html: str) -> Optional[Any]:
    """Return the JSON inside the ``data-ssr-props`` screen island."""
    pattern = re.compile(
        r'<script([^>]*\bdata-ssr-props="[^"]*"[^>]*)>(.*?)</script>', re.S
    )
    match = pattern.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(2).strip())
    except ValueError:
        return None


# ── Quote header ──────────────────────────────────────────────────────────────


def _parse_price_block(block: str) -> dict[str, Any]:
    """Parse one ``div.quote-price`` block (last close or after-hours)."""
    label_match = re.search(r'<div class="sr-only">([^<]+)</div>', block)
    price_match = re.search(r'<strong class="quote-price_price">([^<]+)</strong>', block)
    # The date cell nests a muted separator span, so the capture has to run to
    # the change span rather than to the first closing tag.
    date_match = re.search(
        r'<span class="quote-price_date">(.*?)(?:<span class="quote-price_change|</div>)',
        block,
        re.S,
    )
    change_match = re.search(
        r'<span class="sr-only">Dollar change</span>\s*([-+]?[\d.,]+)', block
    )
    pct_match = re.search(
        r'<span class="sr-only">Percentage change</span>\s*\(?([-+]?[\d.,]+%?)\)?', block
    )

    def _num(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value.replace(",", "").rstrip("%"))
        except ValueError:
            return None

    pct_raw = pct_match.group(1) if pct_match else None
    return {
        "label": strip_tags(label_match.group(1)) if label_match else None,
        "price": _num(price_match.group(1)) if price_match else None,
        "price_raw": price_match.group(1).strip() if price_match else None,
        "date": strip_tags(date_match.group(1)) if date_match else None,
        "change": _num(change_match.group(1)) if change_match else None,
        "change_percent": _num(pct_raw),
    }


_CHIP_KINDS = {
    "sec_": "sector",
    # Finviz's industry filter is ``industry_<slug>``; the older ``ind_``
    # spelling is kept because both have appeared in the markup.
    "ind_": "industry",
    "industry_": "industry",
    "geo_": "country",
    "cap_": "market_cap_class",
    "exch_": "exchange",
    "idx_": "index",
    # ETFs carry no sector/industry in the usual sense; Finviz tags them with
    # ``etf_sectype_<kind>`` instead, which is the fund's own classification.
    "etf_": "etf_type",
}


def parse_quote_header(html: str) -> dict[str, Any]:
    """Parse the ticker header: identity, prices, and classification chips."""
    result: dict[str, Any] = {
        "ticker": None,
        "company": None,
        "website": None,
        "logo_url": None,
        "last_close": None,
        "after_hours": None,
        "sector": None,
        "industry": None,
        "country": None,
        "market_cap_class": None,
        "exchange": None,
        "etf_type": None,
    }

    ticker_match = re.search(
        r'<h1[^>]*class="[^"]*js-recent-quote-ticker[^"]*"[^>]*data-ticker="([^"]+)"', html
    )
    if not ticker_match:
        ticker_match = re.search(r'<h1[^>]*data-ticker="([^"]+)"', html)
    if ticker_match:
        result["ticker"] = html_lib.unescape(ticker_match.group(1)).strip().upper()

    company_match = re.search(
        r'<h2 class="quote-header_ticker-wrapper_company[^"]*">\s*'
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        html,
        re.S,
    )
    if company_match:
        result["website"] = html_lib.unescape(company_match.group(1)).strip()
        result["company"] = strip_tags(company_match.group(2))

    logo_match = re.search(r"--logo-url:\s*url\('([^']+)'\)", html)
    if logo_match:
        result["logo_url"] = logo_match.group(1)

    # Price blocks: the static header renders last close then after-hours,
    # separated by ``div.quote-price-divider``.
    static_prices = re.search(
        r'<div class="quote-header_right js-quote-price-static">(.*?)<div class="js-quote-price-root',
        html,
        re.S,
    )
    if static_prices:
        blocks = re.findall(r'<div class="quote-price">(.*?)</div>\s*</div>', static_prices.group(1), re.S)
        if not blocks:
            # Fallback: split on the divider so a minor markup change still works.
            blocks = [
                part
                for part in static_prices.group(1).split('<div class="quote-price-divider"></div>')
                if "quote-price_price" in part
            ]
        parsed_blocks = [_parse_price_block(b) for b in blocks]
        if parsed_blocks:
            result["last_close"] = parsed_blocks[0]
        if len(parsed_blocks) > 1:
            result["after_hours"] = parsed_blocks[1]

    # The classification chips ("Technology", "Consumer Electronics", "USA",
    # "Mega", "NASD") link to the screener with a ``f=<kind>_<value>`` filter.
    # Finviz used to emit ``screener?v=111&f=sec_technology`` and now emits
    # ``/screener/stocks?v=111&f=sec_technology``; the leading slash and the
    # ``/stocks`` path segment are accepted here so a markup move does not
    # silently blank out sector, industry, country and exchange again.
    for filter_key, label in re.findall(
        r'<a href="/?screener(?:/[a-z]+)?\?[^"]*?[&;]f=([^"&]+)"[^>]*'
        r'class="quote-header_category"[^>]*>(.*?)</a>',
        html,
        re.S,
    ):
        for prefix, field in _CHIP_KINDS.items():
            if filter_key.startswith(prefix) and result.get(field) is None:
                result[field] = strip_tags(label)
                break

    return result


# ── Snapshot table ────────────────────────────────────────────────────────────


def parse_snapshot(html: str) -> dict[str, Any]:
    """Parse the 84-field fundamentals snapshot.

    Returns:
        ``{"fields": {label: value}, "pairs": [...], "descriptions": {...}}``

    * ``fields`` maps label → value; values stay as the human-readable strings
      finviz renders ("0.56M", "-25.75% 32.62%") because converting them would
      silently change meaning for multi-value cells (past 3/5Y columns) and
      market-cap suffixes.
    * ``pairs`` is the same data in page order. It exists because finviz ships
      one label twice (``EPS next Y`` appears once as the estimate and once as
      the growth figure); the dict disambiguates the second as
      ``"EPS next Y (2)"`` while ``pairs`` keeps the original label and its own
      description so nothing is lost.
    * ``descriptions`` maps the (disambiguated) label to finviz's box-over text.
    """
    tables = re.findall(
        r'<table[^>]*class="[^"]*js-snapshot-table[^"]*"[^>]*>(.*?)</table>', html, re.S
    )
    fields: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    pairs: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    for table in tables:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
            index = 0
            while index < len(cells) - 1:
                attrs, inner = cells[index]
                label = strip_tags(inner)
                boxover = re.search(r'data-boxover-html="([^"]*)"', attrs)
                is_label = boxover is not None or "snapshot-td-label" in inner
                if not is_label or not label:
                    index += 1
                    continue
                value = strip_tags(cells[index + 1][1])
                description = (
                    html_lib.unescape(boxover.group(1)).strip() if boxover else None
                )

                seen[label] = seen.get(label, 0) + 1
                key = label if seen[label] == 1 else f"{label} ({seen[label]})"

                fields[key] = value
                if description:
                    descriptions[key] = description
                pairs.append(
                    {"label": label, "key": key, "value": value, "description": description}
                )
                index += 2

    return {"fields": fields, "pairs": pairs, "descriptions": descriptions}


def parse_profile(html: str) -> Optional[str]:
    """Return the company description paragraph."""
    match = re.search(r'<div class="quote_profile-bio">(.*?)</div>', html, re.S)
    if not match:
        return None
    text = strip_tags(match.group(1))
    return text or None


# ── Peers ─────────────────────────────────────────────────────────────────────


def parse_peers(html: str) -> list[dict[str, Any]]:
    """Parse the Peers row (``span[data-boxover-ticker]`` entries)."""
    peers: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<span[^>]*\bdata-boxover-ticker="([^"]+)"[^>]*'
        r'\bdata-boxover-company="([^"]*)"[^>]*'
        r'\bdata-boxover-industry="([^"]*)"[^>]*'
        r'\bdata-boxover-country="([^"]*)"[^>]*'
        r'\bdata-boxover-value="([^"]*)"',
        re.S,
    )
    for ticker, company, industry, country, cap in pattern.findall(html):
        peers.append(
            {
                "ticker": html_lib.unescape(ticker).strip().upper(),
                "company": html_lib.unescape(company).strip(),
                "industry": html_lib.unescape(industry).strip(),
                "country": html_lib.unescape(country).strip(),
                "market_cap": html_lib.unescape(cap).strip(),
            }
        )
    return peers


# ── News table ────────────────────────────────────────────────────────────────


def parse_news_rows(markup: str) -> list[dict[str, Any]]:
    """Parse news ``<tr>`` rows into headlines with day/next-day reactions.

    ``markup`` is either the full page or just the ``{"html": ...}`` body from
    ``/api/news/quote/{t}``; both contain the same row structure.
    """
    rows: list[dict[str, Any]] = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", markup, re.S):
        if "tab-link-news" not in row:
            continue
        date_match = re.search(r'<td[^>]*width="130"[^>]*>(.*?)</td>', row, re.S)
        link_match = re.search(
            r'<a class="tab-link-news"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', row, re.S
        )
        if not link_match:
            continue

        source = None
        right_index = row.find("news-link-right")
        if right_index > 0:
            right = row[right_index:]
            source_match = re.search(r"<span>\((.*?)\)</span>", right, re.S)
            if source_match:
                source = strip_tags(source_match.group(1))

        reactions: dict[str, Any] = {"day": None, "next_day": None}
        reactions["day"], reactions["next_day"] = _parse_news_labels(row)

        rows.append(
            {
                "datetime": strip_tags(date_match.group(1)) if date_match else None,
                "headline": strip_tags(link_match.group(2)),
                "source": source,
                "url": "https://finviz.com" + link_match.group(1)
                if link_match.group(1).startswith("/")
                else link_match.group(1),
                "reaction_day_percent": reactions["day"],
                "reaction_next_day_percent": reactions["next_day"],
            }
        )
    return rows


def _parse_news_labels(row: str) -> tuple[Optional[float], Optional[float]]:
    """Extract the day and next-day price reaction percentages beside a headline."""
    day: Optional[float] = None
    next_day: Optional[float] = None
    for match in re.finditer(r'<span class="fv-label[^"]*"([^>]*)>(.*?)</span>', row, re.S):
        attrs, inner = match.groups()
        text = strip_tags(inner)
        value_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", text)
        if not value_match:
            continue
        try:
            value = float(value_match.group(1))
        except ValueError:
            continue
        title = re.search(r'title="([^"]*)"', attrs)
        if title and next_day is None:
            next_day = value
        elif day is None:
            day = value
    return day, next_day


# ── Insider trading table ─────────────────────────────────────────────────────


def parse_insider_rows(html: str) -> list[dict[str, Any]]:
    """Parse the insider trading table (the styled table with an Insider Trading header)."""
    for table in re.findall(
        r'<table[^>]*class="[^"]*styled-table-new[^"]*"[^>]*>(.*?)</table>', html, re.S
    ):
        if "Insider Trading" not in table:
            continue
        rows: list[dict[str, Any]] = []
        for row in re.findall(r"<tr[^>]*>.*?</tr>", table, re.S):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
            if len(cells) < 9:
                continue
            values = [strip_tags(cell) for cell in cells]
            if values[0] == "Insider Trading":
                continue
            form_url = re.search(r'href="([^"]+)"', cells[8])
            profile_url = re.search(r'href="([^"]+)"', cells[0])
            rows.append(
                {
                    "insider": values[0],
                    "relationship": values[1],
                    "date": values[2],
                    "transaction": values[3],
                    "cost": values[4],
                    "shares": values[5],
                    "value_usd": values[6],
                    "shares_total": values[7],
                    "sec_form4": values[8],
                    "sec_form4_url": form_url.group(1) if form_url else None,
                    "profile_url": "https://finviz.com/" + profile_url.group(1)
                    if profile_url and profile_url.group(1).startswith("insidertrading")
                    else (profile_url.group(1) if profile_url else None),
                }
            )
        return rows
    return []


def parse_insider_rows_from_table(table_html: str) -> list[dict[str, Any]]:
    """Same as :func:`parse_insider_rows` for a pre-extracted table fragment."""
    return parse_insider_rows(f"<table class=\"styled-table-new\">{table_html}</table>")
