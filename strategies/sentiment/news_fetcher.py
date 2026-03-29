import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("polybot.sentiment.news")


@dataclass
class NewsItem:
    title: str
    description: str
    source: str
    url: str
    published_at: str


class NewsFetcher:
    """Fetches headlines from NewsAPI."""

    BASE_URL = "https://newsapi.org/v2"

    def __init__(self, api_key: str, categories: list[str] | None = None, poll_interval: int = 600):
        self.api_key = api_key
        self.categories = categories or ["general"]
        self.poll_interval = poll_interval
        self._last_fetch: float = 0
        self._cache: list[NewsItem] = []

    async def fetch_headlines(self, query: str | None = None) -> list[NewsItem]:
        """Fetch top headlines, with optional keyword query."""
        now = time.time()
        if now - self._last_fetch < self.poll_interval and self._cache:
            return self._cache

        params = {
            "apiKey": self.api_key,
            "language": "en",
            "pageSize": 50,
        }

        if query:
            params["q"] = query
            endpoint = f"{self.BASE_URL}/everything"
            params["sortBy"] = "publishedAt"
        else:
            endpoint = f"{self.BASE_URL}/top-headlines"
            params["country"] = "us"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(endpoint, params=params)
                resp.raise_for_status()
                data = resp.json()

            articles = data.get("articles", [])
            self._cache = [
                NewsItem(
                    title=a.get("title", ""),
                    description=a.get("description", "") or "",
                    source=a.get("source", {}).get("name", ""),
                    url=a.get("url", ""),
                    published_at=a.get("publishedAt", ""),
                )
                for a in articles
                if a.get("title")
            ]
            self._last_fetch = now
            logger.info("Fetched %d news articles", len(self._cache))

        except Exception as e:
            logger.error("NewsAPI fetch failed: %s", e)

        return self._cache

    def extract_keywords(self, market_question: str) -> str:
        """Extract search keywords from a market question."""
        # Remove common question words
        stopwords = {"will", "the", "a", "an", "be", "is", "are", "was", "were",
                      "by", "in", "on", "at", "to", "for", "of", "with", "before",
                      "after", "during", "?", "how", "what", "when", "where"}
        words = market_question.lower().split()
        keywords = [w.strip("?.,!") for w in words if w.lower().strip("?.,!") not in stopwords]
        return " ".join(keywords[:5])
