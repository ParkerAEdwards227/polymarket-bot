import pytest
import pytest_asyncio
from datetime import datetime

from core.database import Database
from core.models import Signal, Trade, Market


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def market():
    return Market(
        condition_id="0xtest123",
        question="Test market?",
        slug="test-market",
        tokens=[{"token_id": "tok_yes", "outcome": "Yes"}],
        end_date="2026-12-31",
        active=True,
        outcome_prices=(0.65, 0.35),
    )


@pytest.fixture
def signal(market):
    return Signal(
        strategy_name="test_strategy",
        market=market,
        side="BUY",
        token_id="tok_yes",
        target_price=0.65,
        size_usd=5.0,
        confidence=0.8,
        reason="Test signal",
    )


@pytest.mark.asyncio
async def test_record_and_get_signal(db, signal):
    await db.record_signal(signal, approved=True)
    cursor = await db._db.execute("SELECT * FROM signals WHERE id = ?", (signal.id,))
    row = await cursor.fetchone()
    assert row is not None
    assert dict(row)["strategy_name"] == "test_strategy"


@pytest.mark.asyncio
async def test_record_trade(db, signal):
    trade = Trade(
        signal=signal,
        order_id="order_123",
        status="dry_run",
        fill_price=0.65,
        fill_size=7.69,
        fees=0.0,
    )
    await db.record_trade(trade)
    trades = await db.get_trades_today()
    assert len(trades) == 1
    assert trades[0]["order_id"] == "order_123"


@pytest.mark.asyncio
async def test_position_tracking(db):
    await db.update_position("mkt1", "tok1", 10.0, 0.50)
    positions = await db.get_positions()
    assert len(positions) == 1
    assert positions[0]["size"] == 10.0

    # Update position
    await db.update_position("mkt1", "tok1", 15.0, 0.55)
    positions = await db.get_positions()
    assert len(positions) == 1
    assert positions[0]["size"] == 15.0

    # Close position
    await db.update_position("mkt1", "tok1", 0, 0)
    positions = await db.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_daily_pnl(db):
    await db.update_daily_pnl(5.0, True)
    await db.update_daily_pnl(-2.0, False)

    pnl = await db.get_daily_pnl()
    assert pnl is not None
    assert pnl["realized_pnl"] == pytest.approx(3.0)
    assert pnl["total_trades"] == 2
    assert pnl["winning_trades"] == 1
