#!/usr/bin/env python3
"""Polymarket Hybrid Trading Bot — Entry Point."""

import argparse
import asyncio
import sys

from core.config import load_config
from core.logging_setup import setup_logging
from core.orchestrator import Orchestrator


def build_strategies(config, market_data, db):
    """Instantiate enabled strategies based on config."""
    strategies = []

    if config.resolution_hunting.enabled:
        from strategies.resolution_hunting.strategy import ResolutionHuntingStrategy
        strategies.append(ResolutionHuntingStrategy(config.resolution_hunting, market_data))

    if config.copy_trading.enabled:
        from strategies.copy_trading.strategy import CopyTradingStrategy
        strategies.append(CopyTradingStrategy(config.copy_trading, config, market_data, db))

    if config.sentiment.enabled:
        from strategies.sentiment.strategy import SentimentStrategy
        strategies.append(SentimentStrategy(config.sentiment, config, market_data))

    if config.arbitrage.enabled:
        from strategies.arbitrage.strategy import ArbitrageStrategy
        strategies.append(ArbitrageStrategy(config.arbitrage, market_data))

    return strategies


async def main():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--mode", choices=["dry_run", "live"], default=None,
                        help="Override bot mode (dry_run or live)")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.mode:
        config.mode = args.mode

    logger = setup_logging(config.log_level)
    logger.info("Starting Polymarket Bot (mode=%s)", config.mode)

    orchestrator = Orchestrator(config)

    # Build and register strategies
    strategies = build_strategies(config, orchestrator.market_data, orchestrator.db)
    for strat in strategies:
        orchestrator.register_strategy(strat)

    if not strategies:
        logger.warning("No strategies enabled! Check config.yaml")

    await orchestrator.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
        sys.exit(0)
