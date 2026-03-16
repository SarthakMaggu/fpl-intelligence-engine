"""
News Agent — scrapes FPL news from multiple free sources.

Sources (no API token needed):
  - BBC Sport RSS
  - Sky Sports RSS
  - The Guardian football RSS
  - Premier League official RSS
  - Fantasy Football Scout (HTML scrape — free articles)
  - FPL Review blog (RSS/HTML)
  - Reddit r/FantasyPL (via PRAW or JSON API fallback)

Features:
  - Injury + availability keyword detection
  - Player sentiment scoring (positive/negative/neutral per player)
  - Form signals (hat-tricks, blanks, price changes mentioned)
  - Caches in Redis with TTL; stores structured articles in news:articles
"""
import asyncio
import feedparser
import re
import json
from datetime import datetime
from typing import Optional
from loguru import logger
from core.config import settings
from core.redis_client import redis_client

REDDIT_SUBREDDIT = "FantasyPL"
BBC_SPORT_RSS = "https://feeds.bbci.co.uk/sport/football/rss.xml"
SKY_SPORTS_RSS = "https://www.skysports.com/rss/12040"
GUARDIAN_FOOTBALL_RSS = "https://www.theguardian.com/football/rss"
PREMIERLEAGUE_RSS = "https://www.premierleague.com/rss/news"
FPL_REVIEW_RSS = "https://fplreview.com/feed/"
PLANET_FPL_RSS = "https://www.planetfpl.com/feed/"
FFS_RSS = "https://www.fantasyfootballscout.co.uk/feed/"  # Fantasy Football Scout

NEWS_CACHE_KEY = "news:injuries"
ARTICLES_CACHE_KEY = "news:articles"
SENTIMENT_CACHE_KEY = "news:sentiment"
NEWS_TTL = 3600  # 1h — alerts
ARTICLE_TTL = 86400  # 24h — full article list

INJURY_KEYWORDS = [
    "injury", "injured", "doubt", "ruled out", "suspended", "suspension",
    "knock", "concern", "fitness test", "unavailable", "out", "miss",
    "hamstring", "ankle", "knee", "muscle", "illness", "covid",
    "fractured", "surgery", "ban", "yellow card", "red card", "limped off",
    "substituted off", "withdrew", "withdraws", "not training",
]

POSITIVE_KEYWORDS = [
    "returns", "fit", "training", "available", "start", "captain",
    "hat-trick", "brace", "double", "assist", "clean sheet",
    "penalty taker", "set piece", "form", "on fire", "clinical",
    "goal", "goalscorer", "fixture", "good run", "in form",
]

NEGATIVE_KEYWORDS = [
    "blank", "benched", "substitute", "rotation risk", "poor form",
    "off form", "miss", "suspended", "banned", "not worth",
    "underperforming", "disappointing", "struggle",
]

FPL_SIGNAL_KEYWORDS = [
    "transfer", "price rise", "price fall", "differential",
    "must own", "captain pick", "triple captain", "bench boost",
    "wildcard", "free hit", "template", "mini-league",
    "ownership", "sell", "buy", "hold", "transfer in", "transfer out",
]


class NewsAgent:
    def __init__(self):
        self._reddit = None
        if settings.reddit_enabled:
            try:
                import praw
                self._reddit = praw.Reddit(
                    client_id=settings.REDDIT_CLIENT_ID,
                    client_secret=settings.REDDIT_CLIENT_SECRET,
                    user_agent=settings.REDDIT_USER_AGENT,
                    read_only=True,
                )
                logger.info("Reddit PRAW initialized")
            except Exception as e:
                logger.warning(f"Reddit init failed: {e}. Using JSON fallback.")

    # ── Reddit ────────────────────────────────────────────────────────────────

    async def get_reddit_posts(self, limit: int = 30) -> list[dict]:
        """Fetch hot posts from r/FantasyPL — PRAW first, JSON API fallback."""
        if self._reddit:
            loop = asyncio.get_event_loop()
            try:
                posts = await loop.run_in_executor(
                    None,
                    lambda: list(self._reddit.subreddit(REDDIT_SUBREDDIT).hot(limit=limit)),
                )
                return [
                    {
                        "id": p.id,
                        "source": "reddit",
                        "title": p.title,
                        "url": f"https://reddit.com{p.permalink}",
                        "score": p.score,
                        "created_utc": p.created_utc,
                        "flair": p.link_flair_text or "",
                        "body": (p.selftext or "")[:600],
                    }
                    for p in posts
                ]
            except Exception as e:
                logger.error(f"Reddit PRAW failed: {e}")

        # JSON API fallback (no auth needed)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(
                    f"https://www.reddit.com/r/{REDDIT_SUBREDDIT}/hot.json?limit={limit}",
                    headers={"User-Agent": "FPL Intelligence Bot 1.0"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return [
                        {
                            "id": p["data"]["id"],
                            "source": "reddit",
                            "title": p["data"]["title"],
                            "url": f"https://reddit.com{p['data']['permalink']}",
                            "score": p["data"]["score"],
                            "created_utc": p["data"]["created_utc"],
                            "flair": p["data"].get("link_flair_text") or "",
                            "body": (p["data"].get("selftext") or "")[:600],
                        }
                        for p in data.get("data", {}).get("children", [])
                    ]
        except Exception as e:
            logger.warning(f"Reddit JSON fallback failed: {e}")
        return []

    # ── RSS helpers ──────────────────────────────────────────────────────────

    async def _fetch_rss(self, url: str, source_name: str, limit: int = 25) -> list[dict]:
        """Generic RSS feed fetcher."""
        loop = asyncio.get_event_loop()
        try:
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            return [
                {
                    "id": entry.get("id", getattr(entry, "link", url)),
                    "source": source_name,
                    "title": entry.title,
                    "url": getattr(entry, "link", url),
                    "body": entry.get("summary", "")[:600],
                    "created_utc": entry.get("published_parsed", None),
                    "score": 0,
                    "flair": "",
                }
                for entry in feed.entries[:limit]
                if hasattr(entry, "title")
            ]
        except Exception as e:
            logger.warning(f"{source_name} RSS fetch failed: {e}")
            return []

    async def get_bbc_sport_feed(self) -> list[dict]:
        return await self._fetch_rss(BBC_SPORT_RSS, "bbc_sport")

    async def get_sky_sports_feed(self) -> list[dict]:
        return await self._fetch_rss(SKY_SPORTS_RSS, "sky_sports")

    async def get_guardian_feed(self) -> list[dict]:
        return await self._fetch_rss(GUARDIAN_FOOTBALL_RSS, "guardian")

    async def get_premierleague_feed(self) -> list[dict]:
        return await self._fetch_rss(PREMIERLEAGUE_RSS, "premier_league")

    async def get_fpl_review_feed(self) -> list[dict]:
        return await self._fetch_rss(FPL_REVIEW_RSS, "fpl_review")

    async def get_fantasy_football_scout_feed(self) -> list[dict]:
        return await self._fetch_rss(FFS_RSS, "fantasy_football_scout")

    async def get_planet_fpl_feed(self) -> list[dict]:
        return await self._fetch_rss(PLANET_FPL_RSS, "planet_fpl")

    # ── Sentinel scoring ──────────────────────────────────────────────────────

    def score_sentiment(self, text: str) -> float:
        """
        Returns a sentiment score for FPL context:
          +1.0  very positive (fit, captain, hat-trick)
           0.0  neutral
          -1.0  very negative (injured, ruled out, blank)
        """
        text_lower = text.lower()
        pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
        neg = sum(1 for kw in NEGATIVE_KEYWORDS + INJURY_KEYWORDS if kw in text_lower)
        if pos + neg == 0:
            return 0.0
        return round((pos - neg) / (pos + neg), 2)

    def extract_fpl_signals(self, text: str) -> list[str]:
        """Extract FPL strategy signals from article text."""
        text_lower = text.lower()
        return [kw for kw in FPL_SIGNAL_KEYWORDS if kw in text_lower]

    # ── Injury alerts ────────────────────────────────────────────────────────

    def extract_injury_alerts(
        self,
        posts: list[dict],
        player_names: list[str],
    ) -> list[dict]:
        """
        Scan posts for player name mentions + injury keywords.
        Returns list of {player_name, alert, source, url, timestamp, sentiment, signals}.
        """
        alerts = []
        name_set = {n.lower(): n for n in player_names}

        for post in posts:
            title_lower = post["title"].lower()
            body_lower = post.get("body", "").lower()
            combined = f"{title_lower} {body_lower}"

            has_injury_keyword = any(kw in combined for kw in INJURY_KEYWORDS)
            if not has_injury_keyword:
                continue

            for name_lower, name_orig in name_set.items():
                if name_lower in combined:
                    alerts.append({
                        "player_name": name_orig,
                        "alert": post["title"],
                        "source": post["source"],
                        "url": post["url"],
                        "timestamp": datetime.utcnow().isoformat(),
                        "sentiment": self.score_sentiment(combined),
                        "signals": self.extract_fpl_signals(combined),
                    })
                    break

        return alerts

    def extract_player_news(
        self,
        posts: list[dict],
        player_names: list[str],
    ) -> dict[str, list[dict]]:
        """
        Build a per-player news map with sentiment + FPL signals.
        Returns {player_name: [article_summary, ...]}
        Used for richer xPts adjustments and UI display.
        """
        player_news: dict[str, list[dict]] = {}
        name_set = {n.lower(): n for n in player_names}

        for post in posts:
            combined = f"{post['title'].lower()} {post.get('body', '').lower()}"
            sentiment = self.score_sentiment(combined)
            signals = self.extract_fpl_signals(combined)

            for name_lower, name_orig in name_set.items():
                if name_lower in combined:
                    if name_orig not in player_news:
                        player_news[name_orig] = []
                    player_news[name_orig].append({
                        "title": post["title"],
                        "source": post["source"],
                        "url": post["url"],
                        "sentiment": sentiment,
                        "signals": signals,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

        return player_news

    # ── Persistence ──────────────────────────────────────────────────────────

    async def store_alerts(self, alerts: list[dict]) -> None:
        """Store injury alerts in Redis sorted set (score = unix timestamp)."""
        if not alerts:
            return
        import orjson
        import time
        pipe = redis_client.pipeline()
        for alert in alerts:
            pipe.zadd(NEWS_CACHE_KEY, {orjson.dumps(alert).decode(): time.time()})
        pipe.expire(NEWS_CACHE_KEY, NEWS_TTL)
        await pipe.execute()
        logger.info(f"Stored {len(alerts)} injury alerts in Redis")

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from article body text."""
        import re
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"&[a-z#0-9]+;", " ", clean)  # HTML entities
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:280]

    async def store_articles(self, posts: list[dict], current_gw_id: int | None = None) -> None:
        """Store all articles (not just injuries) for UI display.
        Also pushes to a GW-scoped key (news:gw:{gw_id}:articles) for per-GW sentiment.
        """
        import orjson
        # Keep last 200 articles; cap at 200 via LTRIM
        pipe = redis_client.pipeline()
        for post in posts[:200]:
            try:
                body_clean = self._strip_html(post.get("body", ""))
                combined = f"{post['title']} {body_clean}"
                article_json = orjson.dumps({
                    "title": post["title"],
                    "source": post["source"],
                    "url": post["url"],
                    "body": body_clean,
                    "sentiment": self.score_sentiment(combined),
                    "signals": self.extract_fpl_signals(combined),
                    "timestamp": datetime.utcnow().isoformat(),
                }).decode()
                pipe.lpush(ARTICLES_CACHE_KEY, article_json)
                # GW-window key — stores all articles from GW start → deadline
                if current_gw_id:
                    gw_key = f"news:gw:{current_gw_id}:articles"
                    pipe.lpush(gw_key, article_json)
                    pipe.ltrim(gw_key, 0, 499)     # cap at 500 articles
                    pipe.expire(gw_key, 7 * 86400)  # 7 days TTL
            except Exception:
                pass
        pipe.ltrim(ARTICLES_CACHE_KEY, 0, 199)
        pipe.expire(ARTICLES_CACHE_KEY, ARTICLE_TTL)
        await pipe.execute()

    async def get_gw_articles(self, gw_id: int, limit: int = 100) -> list[dict]:
        """Retrieve all articles stored during a specific GW's window."""
        import orjson
        raw = await redis_client.lrange(f"news:gw:{gw_id}:articles", 0, limit - 1)
        return [orjson.loads(r) for r in raw if r]

    async def store_gw_window_sentiment(self, gw_id: int) -> None:
        """
        Aggregate sentiment from all GW-window articles into a GW-specific sentiment map.
        Stored in news:gw:{gw_id}:sentiment with 8-day TTL.
        """
        import orjson
        from collections import defaultdict

        articles = await self.get_gw_articles(gw_id, limit=500)
        if not articles:
            return

        player_articles: dict[str, list] = defaultdict(list)
        for art in articles:
            combined = f"{art.get('title', '')} {art.get('body', '')}"
            for player_name, _ in self._player_mentions.items() if hasattr(self, '_player_mentions') else []:
                if player_name.lower() in combined.lower():
                    player_articles[player_name].append(art)

        if not player_articles:
            return

        gw_sentiment_map = {}
        for player, arts in player_articles.items():
            avg_sent = sum(a.get("sentiment", 0.0) for a in arts) / len(arts)
            gw_sentiment_map[player] = {
                "sentiment": round(avg_sent, 2),
                "article_count": len(arts),
                "gw_id": gw_id,
            }

        await redis_client.set(
            f"news:gw:{gw_id}:sentiment",
            orjson.dumps(gw_sentiment_map).decode(),
            ex=8 * 86400,
        )
        logger.info(f"GW{gw_id} window sentiment stored: {len(gw_sentiment_map)} players")

    async def store_player_sentiment(self, player_news: dict[str, list[dict]]) -> None:
        """Store per-player sentiment map in Redis for xPts model consumption."""
        import orjson
        # Aggregate: average sentiment per player across all recent mentions
        sentiment_map: dict[str, dict] = {}
        for player, articles in player_news.items():
            if not articles:
                continue
            avg_sentiment = sum(a["sentiment"] for a in articles) / len(articles)
            all_signals = list({s for a in articles for s in a.get("signals", [])})
            sentiment_map[player] = {
                "sentiment": round(avg_sentiment, 2),
                "article_count": len(articles),
                "signals": all_signals,
                "latest_title": articles[0]["title"] if articles else "",
                "latest_source": articles[0]["source"] if articles else "",
                "updated_at": datetime.utcnow().isoformat(),
            }
        if sentiment_map:
            await redis_client.set(
                SENTIMENT_CACHE_KEY,
                orjson.dumps(sentiment_map).decode(),
                ex=ARTICLE_TTL,
            )
            logger.info(f"Stored sentiment for {len(sentiment_map)} players")

    async def get_recent_alerts(self, limit: int = 20) -> list[dict]:
        """Retrieve most recent injury alerts from Redis."""
        import orjson
        raw = await redis_client.zrevrange(NEWS_CACHE_KEY, 0, limit - 1)
        return [orjson.loads(r) for r in raw]

    async def get_recent_articles(self, limit: int = 50) -> list[dict]:
        """Retrieve recent articles from Redis list."""
        import orjson
        raw = await redis_client.lrange(ARTICLES_CACHE_KEY, 0, limit - 1)
        return [orjson.loads(r) for r in raw if r]

    async def get_player_sentiment(self, player_name: Optional[str] = None) -> dict:
        """Get player sentiment map (or single player if name given)."""
        import orjson
        raw = await redis_client.get(SENTIMENT_CACHE_KEY)
        if not raw:
            return {}
        data = orjson.loads(raw)
        if player_name:
            return data.get(player_name, {})
        return data

    # ── Main pipeline ─────────────────────────────────────────────────────────

    async def run(self, player_names: list[str], current_gw_id: int | None = None) -> list[dict]:
        """
        Full news pipeline:
          1. Fetch from 7+ sources in parallel
          2. Extract injury alerts + player sentiment + FPL signals
          3. Store all in Redis (rolling 24h + GW-scoped window)
          4. Return alerts list
        """
        results = await asyncio.gather(
            self.get_reddit_posts(),
            self.get_bbc_sport_feed(),
            self.get_sky_sports_feed(),
            self.get_guardian_feed(),
            self.get_premierleague_feed(),
            self.get_fpl_review_feed(),
            self.get_fantasy_football_scout_feed(),
            self.get_planet_fpl_feed(),
            return_exceptions=True,
        )
        all_posts: list[dict] = []
        for r in results:
            if isinstance(r, list):
                all_posts.extend(r)

        logger.info(f"News pipeline: {len(all_posts)} posts from {len(results)} sources")

        # Extract structured data
        alerts = self.extract_injury_alerts(all_posts, player_names)
        player_news = self.extract_player_news(all_posts, player_names)

        # Store everything (pass current_gw_id for GW-window storage)
        await asyncio.gather(
            self.store_alerts(alerts),
            self.store_articles(all_posts, current_gw_id=current_gw_id),
            self.store_player_sentiment(player_news),
        )

        logger.info(
            f"News pipeline complete: {len(all_posts)} posts → "
            f"{len(alerts)} injury alerts · {len(player_news)} players with news"
            + (f" · GW{current_gw_id} window updated" if current_gw_id else "")
        )
        return alerts
