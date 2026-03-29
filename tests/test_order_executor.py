import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from core.config import BotConfig
from core.models import Signal, Market
from services.order_executor import OrderExecutor


@pytest.fixture
def market():
    return Market(
        condition_id="0xtest",
        question="Test?",
        slug="test",
        tokens=[{"token_id": "tok1", "outcome": "Yes"}],
        end_date="2026-12-31",
        active=True,
        outcome_prices=(0.5, 0.5),
    )


@pytest.fixture
def signal(market):
    return Signal(
        strategy_name="test",
        market=market,
        side="BUY",
        token_id="tok1",
        target_price=0.50,
        size_usd=5.0,
        confidence=0.8,
        reason="Test",
    )


@pytest.mark.asyncio
async def test_dry_run_execution(signal):
    config = BotConfig(mode="dry_run")
    clob = MagicMock()
    executor = OrderExecutor(clob, config)

    trade = await executor.execute(signal)

    assert trade.status == "dry_run"
    assert trade.fill_price == 0.50
    assert trade.fill_size == pytest.approx(10.0)  # 5.0 / 0.50
    assert trade.fees == 0.0
    assert trade.order_id == "dry_run"
    # CLOB should NOT be called in dry run
    clob.create_and_post_limit_order.assert_not_called()


@pytest.mark.asyncio
async def test_live_limit_order(signal):
    config = BotConfig(mode="live")
    clob = MagicMock()
    clob.create_and_post_limit_order.return_value = {"orderID": "order_abc"}
    executor = OrderExecutor(clob, config)

    trade = await executor.execute(signal, use_market_order=False)

    assert trade.status == "pending"
    assert trade.order_id == "order_abc"
    assert trade.fees == 0.0  # maker = 0%
    clob.create_and_post_limit_order.assert_called_once()


@pytest.mark.asyncio
async def test_live_market_order(signal):
    config = BotConfig(mode="live")
    clob = MagicMock()
    clob.create_and_post_market_order.return_value = {"orderID": "order_fok"}
    executor = OrderExecutor(clob, config)

    trade = await executor.execute(signal, use_market_order=True)

    assert trade.status == "filled"
    assert trade.fees > 0  # taker fees
    clob.create_and_post_market_order.assert_called_once()


@pytest.mark.asyncio
async def test_execution_error_handling(signal):
    config = BotConfig(mode="live")
    clob = MagicMock()
    clob.create_and_post_limit_order.side_effect = Exception("API error")
    executor = OrderExecutor(clob, config)

    trade = await executor.execute(signal)

    assert trade.status == "cancelled"
    assert trade.fill_size == 0.0
