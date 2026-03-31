import logging
from dataclasses import dataclass
from typing import Literal

from strategies.crypto_scalper.exchange_feed import Candle

logger = logging.getLogger("polybot.crypto_scalper.ta")


@dataclass
class TASignal:
    direction: Literal["bullish", "bearish", "neutral"]
    strength: float  # 0.0-1.0
    rsi: float  # 0-100
    macd_histogram: float
    macd_cross: Literal["bullish_cross", "bearish_cross", "none"]
    vwap: float
    vwap_deviation: float  # (close - vwap) / vwap
    bb_position: float  # 0.0=lower band, 0.5=middle, 1.0=upper
    bb_width: float  # volatility proxy


class TechnicalAnalyzer:
    """Pure computation — takes candle data, returns TA indicators. No I/O."""

    def analyze(self, candles_1m: list[Candle], candles_5m: list[Candle]) -> TASignal:
        closes_1m = [c.close for c in candles_1m]
        closes_5m = [c.close for c in candles_5m]

        rsi = self.compute_rsi(closes_1m)
        macd_line, signal_line, histogram = self.compute_macd(closes_1m)

        # Detect MACD cross
        if len(closes_1m) >= 2:
            prev_hist = self._compute_macd_at(closes_1m[:-1])
            if prev_hist <= 0 and histogram > 0:
                macd_cross = "bullish_cross"
            elif prev_hist >= 0 and histogram < 0:
                macd_cross = "bearish_cross"
            else:
                macd_cross = "none"
        else:
            macd_cross = "none"

        vwap = self.compute_vwap(candles_5m) if candles_5m else closes_5m[-1] if closes_5m else 0
        current = closes_1m[-1] if closes_1m else 0
        vwap_dev = (current - vwap) / vwap if vwap > 0 else 0

        bb_lower, bb_mid, bb_upper = self.compute_bollinger(closes_5m)
        bb_range = bb_upper - bb_lower
        bb_position = (current - bb_lower) / bb_range if bb_range > 0 else 0.5
        bb_position = max(0.0, min(1.0, bb_position))
        bb_width = bb_range / bb_mid if bb_mid > 0 else 0

        direction, strength = self._composite_direction(rsi, histogram, macd_cross, vwap_dev, bb_position)

        return TASignal(
            direction=direction,
            strength=strength,
            rsi=rsi,
            macd_histogram=histogram,
            macd_cross=macd_cross,
            vwap=vwap,
            vwap_deviation=vwap_dev,
            bb_position=bb_position,
            bb_width=bb_width,
        )

    def compute_rsi(self, closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0  # neutral default

        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        # Wilder's smoothing (EMA)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def compute_macd(self, closes: list[float]) -> tuple[float, float, float]:
        """Returns (macd_line, signal_line, histogram)."""
        if len(closes) < 26:
            return 0, 0, 0

        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        macd_line = ema12 - ema26

        # For signal line, compute MACD series then EMA(9) of it
        macd_series = []
        for i in range(26, len(closes) + 1):
            e12 = self._ema(closes[:i], 12)
            e26 = self._ema(closes[:i], 26)
            macd_series.append(e12 - e26)

        signal_line = self._ema(macd_series, 9) if len(macd_series) >= 9 else macd_line
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def compute_vwap(self, candles: list[Candle]) -> float:
        if not candles:
            return 0
        total_vp = sum((c.high + c.low + c.close) / 3 * c.volume for c in candles)
        total_vol = sum(c.volume for c in candles)
        return total_vp / total_vol if total_vol > 0 else 0

    def compute_bollinger(self, closes: list[float], period: int = 20, std_dev: float = 2.0) -> tuple[float, float, float]:
        """Returns (lower, middle, upper)."""
        if len(closes) < period:
            mid = closes[-1] if closes else 0
            return mid, mid, mid

        recent = closes[-period:]
        middle = sum(recent) / period
        variance = sum((x - middle) ** 2 for x in recent) / period
        std = variance ** 0.5
        return middle - std_dev * std, middle, middle + std_dev * std

    def _ema(self, values: list[float], period: int) -> float:
        if not values:
            return 0
        if len(values) < period:
            return sum(values) / len(values)

        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for val in values[period:]:
            ema = (val - ema) * multiplier + ema
        return ema

    def _compute_macd_at(self, closes: list[float]) -> float:
        """Compute just the MACD histogram for a given close series."""
        if len(closes) < 26:
            return 0
        _, _, hist = self.compute_macd(closes)
        return hist

    def _composite_direction(
        self, rsi: float, macd_hist: float, macd_cross: str, vwap_dev: float, bb_pos: float,
    ) -> tuple[str, float]:
        """Weighted voting system for overall direction and strength."""
        score = 0.0  # positive = bullish, negative = bearish
        total_weight = 0.0

        # RSI (weight: 3)
        w = 3.0
        total_weight += w
        if rsi > 70:
            score -= w * 0.8  # overbought → bearish (mean reversion)
        elif rsi > 60:
            score += w * 0.4  # bullish momentum
        elif rsi < 30:
            score += w * 0.8  # oversold → bullish (mean reversion)
        elif rsi < 40:
            score -= w * 0.4  # bearish momentum

        # MACD (weight: 3)
        w = 3.0
        total_weight += w
        if macd_cross == "bullish_cross":
            score += w * 1.0
        elif macd_cross == "bearish_cross":
            score -= w * 1.0
        elif macd_hist > 0:
            score += w * 0.3
        elif macd_hist < 0:
            score -= w * 0.3

        # VWAP deviation (weight: 2)
        w = 2.0
        total_weight += w
        if vwap_dev > 0.002:
            score += w * min(vwap_dev / 0.01, 1.0)
        elif vwap_dev < -0.002:
            score -= w * min(abs(vwap_dev) / 0.01, 1.0)

        # Bollinger position (weight: 2)
        w = 2.0
        total_weight += w
        if bb_pos > 0.85:
            score -= w * 0.6  # near upper band → mean reversion bearish
        elif bb_pos < 0.15:
            score += w * 0.6  # near lower band → mean reversion bullish

        # Normalize
        normalized = score / total_weight if total_weight > 0 else 0
        strength = min(abs(normalized), 1.0)

        if normalized > 0.15:
            return "bullish", strength
        elif normalized < -0.15:
            return "bearish", strength
        return "neutral", strength
