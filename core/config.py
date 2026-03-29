import os
from dataclasses import dataclass, field
from typing import Literal

import yaml
from dotenv import load_dotenv


@dataclass
class RiskConfig:
    initial_bankroll_usd: float = 50.0
    max_position_pct: float = 0.10
    max_total_exposure_pct: float = 0.60
    daily_loss_limit_pct: float = 0.05
    max_single_trade_pct: float = 0.05
    min_order_size_usd: float = 1.0


@dataclass
class CopyTradingConfig:
    enabled: bool = True
    allocation_pct: float = 0.30
    wallets: list[dict] = field(default_factory=list)
    max_delay_seconds: int = 300
    max_per_market_pct: float = 0.15
    use_market_orders: bool = True
    min_whale_trade_usd: float = 500


@dataclass
class ResolutionHuntingConfig:
    enabled: bool = True
    allocation_pct: float = 0.20
    min_probability: float = 0.93
    min_edge_pct: float = 0.03
    max_per_market_usd: float = 20.0
    scan_interval_seconds: int = 300
    min_liquidity_usd: float = 100
    exclude_categories: list[str] = field(default_factory=lambda: ["crypto"])


@dataclass
class SentimentConfig:
    enabled: bool = False
    allocation_pct: float = 0.25
    min_edge_pct: float = 0.10
    min_confidence: float = 0.7
    newsapi_poll_interval: int = 600
    categories: list[str] = field(default_factory=lambda: ["politics", "world"])
    claude_model: str = "claude-sonnet-4-20250514"
    max_per_market_usd: float = 15.0


@dataclass
class ArbitrageConfig:
    enabled: bool = False
    allocation_pct: float = 0.25
    min_spread_after_fees_pct: float = 0.03
    max_per_pair_usd: float = 25.0
    scan_interval_seconds: int = 600


@dataclass
class NotificationsConfig:
    telegram_enabled: bool = True
    notify_on_trade: bool = True
    notify_on_error: bool = True
    daily_summary: bool = True
    daily_summary_hour: int = 20


@dataclass
class BotConfig:
    # Bot settings
    mode: Literal["dry_run", "live"] = "dry_run"
    tick_interval_seconds: int = 60
    log_level: str = "INFO"

    # API hosts
    clob_host: str = "https://clob.polymarket.com"
    chain_id: int = 137
    gamma_host: str = "https://gamma-api.polymarket.com"
    gamma_cache_ttl: int = 300

    # Secrets (from .env)
    private_key: str = ""
    funder_address: str = ""
    signature_type: int = 0
    polygon_rpc_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    newsapi_key: str = ""
    anthropic_api_key: str = ""

    # Sub-configs
    risk: RiskConfig = field(default_factory=RiskConfig)
    copy_trading: CopyTradingConfig = field(default_factory=CopyTradingConfig)
    resolution_hunting: ResolutionHuntingConfig = field(default_factory=ResolutionHuntingConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    arbitrage: ArbitrageConfig = field(default_factory=ArbitrageConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)


def load_config(config_path: str = "config.yaml", env_path: str = ".env") -> BotConfig:
    load_dotenv(env_path)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    bot_raw = raw.get("bot", {})
    clob_raw = raw.get("clob", {})
    gamma_raw = raw.get("gamma", {})
    risk_raw = raw.get("risk", {})
    strats = raw.get("strategies", {})
    notif_raw = raw.get("notifications", {})

    return BotConfig(
        mode=bot_raw.get("mode", "dry_run"),
        tick_interval_seconds=bot_raw.get("tick_interval_seconds", 60),
        log_level=bot_raw.get("log_level", "INFO"),
        clob_host=clob_raw.get("host", "https://clob.polymarket.com"),
        chain_id=clob_raw.get("chain_id", 137),
        gamma_host=gamma_raw.get("host", "https://gamma-api.polymarket.com"),
        gamma_cache_ttl=gamma_raw.get("cache_ttl_seconds", 300),
        private_key=os.getenv("PRIVATE_KEY", ""),
        funder_address=os.getenv("FUNDER_ADDRESS", ""),
        signature_type=int(os.getenv("SIGNATURE_TYPE", "0")),
        polygon_rpc_url=os.getenv("POLYGON_RPC_URL", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        newsapi_key=os.getenv("NEWSAPI_KEY", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        risk=RiskConfig(**risk_raw) if risk_raw else RiskConfig(),
        copy_trading=CopyTradingConfig(**strats.get("copy_trading", {})),
        resolution_hunting=ResolutionHuntingConfig(**strats.get("resolution_hunting", {})),
        sentiment=SentimentConfig(**strats.get("sentiment", {})),
        arbitrage=ArbitrageConfig(**strats.get("arbitrage", {})),
        notifications=NotificationsConfig(**notif_raw) if notif_raw else NotificationsConfig(),
    )
