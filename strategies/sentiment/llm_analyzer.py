import logging
import json
from dataclasses import dataclass

import anthropic

logger = logging.getLogger("polybot.sentiment.llm")


@dataclass
class ProbabilityEstimate:
    probability: float  # 0.0-1.0
    confidence: float   # 0.0-1.0
    reasoning: str


class LLMAnalyzer:
    """Uses Claude to assess event probabilities based on news."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

    async def assess_probability(
        self,
        market_question: str,
        current_price: float,
        headlines: list[str],
    ) -> ProbabilityEstimate | None:
        if not self._client:
            return None

        headlines_text = "\n".join(f"- {h}" for h in headlines[:15])

        prompt = f"""You are a prediction market analyst. Assess the probability of the following event.

EVENT: {market_question}
CURRENT MARKET PRICE (implied probability): {current_price:.1%}

RECENT NEWS HEADLINES:
{headlines_text}

Based on the news and your knowledge, estimate the TRUE probability of this event.

Respond in JSON format ONLY:
{{
    "probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0, how confident you are in your estimate>,
    "reasoning": "<brief explanation>"
}}"""

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            # Extract JSON from response
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            data = json.loads(text)
            estimate = ProbabilityEstimate(
                probability=float(data["probability"]),
                confidence=float(data["confidence"]),
                reasoning=data.get("reasoning", ""),
            )
            logger.info(
                "LLM estimate for '%s': %.1%% (confidence: %.1%%) — %s",
                market_question[:40],
                estimate.probability * 100,
                estimate.confidence * 100,
                estimate.reasoning[:80],
            )
            return estimate

        except Exception as e:
            logger.error("LLM analysis failed: %s", e)
            return None
