import pytest
from unittest.mock import MagicMock

from core.models import Market
from strategies.resolution_hunting.market_scanner import MarketScanner


def make_market(condition_id, yes_price, liquidity=5000, category="politics", active=True):
    return Market(
        condition_id=condition_id,
        question=f"Test market {condition_id}",
        slug=f"test-{condition_id}",
        tokens=[
            {"token_id": f"yes_{condition_id}", "outcome": "Yes"},
            {"token_id": f"no_{condition_id}", "outcome": "No"},
        ],
        end_date="2026-06-30",
        active=active,
        volume_24h=1000,
        liquidity=liquidity,
        category=category,
        outcome_prices=(yes_price, 1 - yes_price),
    )


def test_finds_near_certain_yes():
    market_data = MagicMock()
    market_data.markets = [make_market("m1", 0.96)]

    scanner = MarketScanner(market_data, min_probability=0.93, min_edge_pct=0.03)
    results = scanner.scan()

    assert len(results) == 1
    assert results[0]["outcome"] == "YES"
    assert results[0]["edge"] == pytest.approx(0.04, abs=0.01)


def test_finds_near_certain_no():
    market_data = MagicMock()
    market_data.markets = [make_market("m1", 0.03)]  # NO is at 0.97

    scanner = MarketScanner(market_data, min_probability=0.93, min_edge_pct=0.03)
    results = scanner.scan()

    assert len(results) == 1
    assert results[0]["outcome"] == "NO"


def test_skips_uncertain_markets():
    market_data = MagicMock()
    market_data.markets = [make_market("m1", 0.50)]

    scanner = MarketScanner(market_data, min_probability=0.93, min_edge_pct=0.03)
    results = scanner.scan()

    assert len(results) == 0


def test_skips_excluded_categories():
    market_data = MagicMock()
    market_data.markets = [make_market("m1", 0.96, category="crypto")]

    scanner = MarketScanner(market_data, min_probability=0.93, exclude_categories=["crypto"])
    results = scanner.scan()

    assert len(results) == 0


def test_skips_low_liquidity():
    market_data = MagicMock()
    market_data.markets = [make_market("m1", 0.96, liquidity=10)]

    scanner = MarketScanner(market_data, min_probability=0.93, min_liquidity_usd=100)
    results = scanner.scan()

    assert len(results) == 0


def test_skips_inactive():
    market_data = MagicMock()
    market_data.markets = [make_market("m1", 0.96, active=False)]

    scanner = MarketScanner(market_data, min_probability=0.93)
    results = scanner.scan()

    assert len(results) == 0
