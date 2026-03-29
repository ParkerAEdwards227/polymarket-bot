import pytest
from core.models import Market


@pytest.fixture
def sample_market():
    return Market(
        condition_id="0xabc123",
        question="Will Bitcoin reach $100k by June 2026?",
        slug="btc-100k-june-2026",
        tokens=[
            {"token_id": "tok_yes_123", "outcome": "Yes"},
            {"token_id": "tok_no_456", "outcome": "No"},
        ],
        end_date="2026-06-30T00:00:00Z",
        active=True,
        volume_24h=50000,
        liquidity=25000,
        category="crypto",
        outcome_prices=(0.65, 0.35),
    )


@pytest.fixture
def near_certain_market():
    return Market(
        condition_id="0xdef456",
        question="Will the sun rise tomorrow?",
        slug="sun-rise-tomorrow",
        tokens=[
            {"token_id": "tok_yes_sun", "outcome": "Yes"},
            {"token_id": "tok_no_sun", "outcome": "No"},
        ],
        end_date="2026-03-30T00:00:00Z",
        active=True,
        volume_24h=10000,
        liquidity=5000,
        category="science",
        outcome_prices=(0.96, 0.04),
    )
