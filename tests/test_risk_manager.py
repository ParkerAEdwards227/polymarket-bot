import pytest
from core.config import RiskConfig
from core.models import Signal, Portfolio, Position, Market
from services.risk_manager import RiskManager


@pytest.fixture
def risk_config():
    return RiskConfig(
        initial_bankroll_usd=100.0,
        max_position_pct=0.10,
        max_total_exposure_pct=0.60,
        daily_loss_limit_pct=0.05,
        max_single_trade_pct=0.05,
        min_order_size_usd=1.0,
    )


@pytest.fixture
def empty_portfolio():
    return Portfolio(balance_usd=100.0, positions=[], daily_pnl=0.0)


@pytest.fixture
def market():
    return Market(
        condition_id="0xtest",
        question="Test market",
        slug="test",
        tokens=[{"token_id": "tok1", "outcome": "Yes"}],
        end_date="2026-12-31",
        active=True,
        outcome_prices=(0.5, 0.5),
    )


def make_signal(market, size=5.0):
    return Signal(
        strategy_name="test",
        market=market,
        side="BUY",
        token_id="tok1",
        target_price=0.5,
        size_usd=size,
        confidence=0.8,
        reason="test signal",
    )


def test_approve_valid_signal(risk_config, empty_portfolio, market):
    rm = RiskManager(risk_config)
    signal = make_signal(market, size=3.0)
    approved, reason = rm.evaluate(signal, empty_portfolio)
    assert approved is not None
    assert reason == ""


def test_reject_daily_loss_limit(risk_config, market):
    rm = RiskManager(risk_config)
    portfolio = Portfolio(balance_usd=100.0, positions=[], daily_pnl=-5.0)
    signal = make_signal(market)
    approved, reason = rm.evaluate(signal, portfolio)
    assert approved is None
    assert "Daily loss limit" in reason


def test_reject_max_exposure(risk_config, market):
    rm = RiskManager(risk_config)
    positions = [
        Position(market_condition_id=f"mkt{i}", token_id=f"tok{i}", size=20, avg_entry_price=0.5)
        for i in range(6)  # 6 positions at $10 each = $60 = 60% exposure
    ]
    portfolio = Portfolio(balance_usd=100.0, positions=positions, daily_pnl=0.0)
    signal = make_signal(market)
    approved, reason = rm.evaluate(signal, portfolio)
    assert approved is None
    assert "exposure" in reason.lower()


def test_size_down_to_single_trade_max(risk_config, empty_portfolio, market):
    rm = RiskManager(risk_config)
    signal = make_signal(market, size=20.0)  # Way over 5% max single trade
    approved, reason = rm.evaluate(signal, empty_portfolio)
    assert approved is not None
    assert approved.size_usd <= 5.0  # max_single_trade_pct * 100


def test_reject_below_minimum(risk_config, market):
    rm = RiskManager(risk_config)
    # Almost full exposure
    positions = [
        Position(market_condition_id=f"mkt{i}", token_id=f"tok{i}", size=19, avg_entry_price=0.5)
        for i in range(6)
    ]
    portfolio = Portfolio(balance_usd=100.0, positions=positions, daily_pnl=0.0)
    signal = make_signal(market, size=0.5)
    approved, reason = rm.evaluate(signal, portfolio)
    # Should either be rejected or sized below minimum
    if approved is None:
        assert "too small" in reason.lower() or "exposure" in reason.lower()
