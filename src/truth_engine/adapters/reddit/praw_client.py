from __future__ import annotations

from typing import Any

import praw  # type: ignore[import-untyped]

from truth_engine.config.settings import Settings
from truth_engine.services.logging import debug_adapter


class RedditSearchClient:
    def __init__(self, settings: Settings):
        client_id = settings.reddit_client_id
        client_secret = settings.reddit_client_secret
        if client_id is None or client_secret is None:
            raise ValueError(
                "Both TRUTH_ENGINE_REDDIT_CLIENT_ID and "
                "TRUTH_ENGINE_REDDIT_CLIENT_SECRET must be set."
            )
        self._reddit = praw.Reddit(
            client_id=client_id.get_secret_value(),
            client_secret=client_secret.get_secret_value(),
            user_agent=settings.reddit_user_agent,
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        subreddit: str | None = None,
    ) -> dict[str, Any]:
        try:
            target = self._reddit.subreddit(subreddit or "all")
            results = []
            for submission in target.search(query, limit=limit, sort="relevance"):
                results.append(
                    {
                        "title": submission.title,
                        "url": f"https://reddit.com{submission.permalink}",
                        "score": submission.score,
                        "num_comments": submission.num_comments,
                        "selftext_snippet": (submission.selftext or "")[:500],
                    }
                )
            debug_adapter(
                "reddit",
                "search",
                query=query,
                subreddit=subreddit or "all",
                results=len(results),
                status="ok",
            )
            return {"status": "ok", "query": query, "results": results}
        except Exception as exc:
            debug_adapter(
                "reddit",
                "search_error",
                query=query,
                error=str(exc),
            )
            return {
                "status": "error",
                "tool": "reddit_search",
                "reason": f"Reddit search failed: {exc}",
            }

    def fetch(self, url: str) -> dict[str, Any]:
        try:
            submission = self._reddit.submission(url=url)
            comments = []
            submission.comments.replace_more(limit=0)
            for comment in submission.comments[:20]:
                comments.append(
                    {
                        "author": str(comment.author or "[deleted]"),
                        "body": (comment.body or "")[:500],
                        "score": comment.score,
                    }
                )
            debug_adapter(
                "reddit",
                "fetch",
                url=url,
                comments=len(comments),
                status="ok",
            )
            return {
                "status": "ok",
                "url": url,
                "title": submission.title,
                "selftext": (submission.selftext or "")[:2000],
                "score": submission.score,
                "num_comments": submission.num_comments,
                "comments": comments,
            }
        except Exception as exc:
            debug_adapter(
                "reddit",
                "fetch_error",
                url=url,
                error=str(exc),
            )
            return {
                "status": "error",
                "tool": "reddit_fetch",
                "reason": f"Reddit fetch failed: {exc}",
            }
