from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..config import Settings

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def fetch_url(
    url: str,
    settings: Settings,
    selector: str | None = None,
    max_chars: int | None = None,
) -> str:
    response = requests.get(
        url,
        timeout=settings.web_timeout,
        headers=DEFAULT_HEADERS,
    )
    response.raise_for_status()
    if selector:
        text = _extract_text_by_selector(response.text, selector)
    else:
        text = _extract_text(response.text)
    if max_chars and max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rsplit(" ", 1)[0] + "..."
    return text


def search(
    query: str,
    settings: Settings,
    limit: int = 5,
    country: str | None = None,
    search_lang: str | None = None,
    freshness: str | None = None,
    result_filter: str | None = None,
) -> list[dict[str, Any]]:
    if is_url(query):
        return [{"title": query, "url": query, "snippet": ""}]

    if not settings.brave_api_key:
        return [
            {
                "title": "Brave API key missing",
                "url": "",
                "snippet": "Set BRAVE_API_KEY in .env to enable web search.",
            }
        ]

    return _brave_search(
        query,
        settings,
        limit,
        country=country,
        search_lang=search_lang,
        freshness=freshness,
        result_filter=result_filter,
    )


def news_search(
    query: str,
    settings: Settings,
    limit: int = 5,
    country: str | None = None,
    search_lang: str | None = None,
    freshness: str | None = None,
) -> list[dict[str, Any]]:
    if is_url(query):
        return [{"title": query, "url": query, "snippet": ""}]
    if not settings.brave_api_key:
        return [
            {
                "title": "Brave API key missing",
                "url": "",
                "snippet": "Set BRAVE_API_KEY in .env to enable news search.",
            }
        ]
    return _brave_news_search(
        query,
        settings,
        limit,
        country=country,
        search_lang=search_lang,
        freshness=freshness,
    )


def summarize_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = []
    for result in results:
        title = (result.get("title") or "").strip()
        url = (result.get("url") or "").strip()
        snippet = (result.get("snippet") or "").strip()
        if url:
            line = f"- [{title or url}]({url})"
        else:
            line = f"- {title or 'Result'}"
        if snippet:
            line = f"{line} — {snippet}"
        lines.append(line)
    return "Sources:\n" + "\n".join(lines)


def _parse_html_results(html: str, limit: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    for item in soup.select(".result"):
        link = item.select_one("a.result__a") or item.select_one("a.result__url")
        snippet = (
            item.select_one(".result__snippet")
            or item.select_one(".result__extras")
            or item.select_one(".result__content")
        )
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        href = link.get("href")
        if not href:
            continue
        results.append(
            {
                "title": title,
                "url": href,
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            }
        )
        if len(results) >= limit:
            break
    return results


def _parse_lite_results(html: str, limit: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    for item in soup.select("table.result"):
        link = item.select_one("a.result-link")
        snippet = item.select_one("td.result-snippet")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        href = link.get("href")
        if not href:
            continue
        results.append(
            {
                "title": title,
                "url": href,
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            }
        )
        if len(results) >= limit:
            break
    return results


def _brave_search(
    query: str,
    settings: Settings,
    limit: int,
    country: str | None = None,
    search_lang: str | None = None,
    freshness: str | None = None,
    result_filter: str | None = None,
) -> list[dict[str, Any]]:
    endpoint = "https://api.search.brave.com/res/v1/web/search"
    params: dict[str, Any] = {
        "q": query,
        "count": min(limit, 20),
        "result_filter": result_filter or "web",
        "safesearch": "moderate",
    }
    if freshness:
        params["freshness"] = freshness
    if country or settings.brave_country:
        params["country"] = country or settings.brave_country
    if search_lang or settings.brave_search_lang:
        params["search_lang"] = search_lang or settings.brave_search_lang

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": settings.brave_api_key,
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
    }
    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=headers,
            timeout=settings.web_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return [
            {
                "title": "Web search failed",
                "url": "",
                "snippet": str(exc),
            }
        ]

    try:
        payload = response.json()
    except ValueError:
        return [
            {
                "title": "Web search failed",
                "url": "",
                "snippet": "Invalid JSON response from Brave.",
            }
        ]

    if isinstance(payload, dict) and payload.get("error"):
        error = payload.get("error") or {}
        message = error.get("message") or "Brave API error."
        return [
            {
                "title": "Web search failed",
                "url": "",
                "snippet": message,
            }
        ]

    web = payload.get("web") or {}
    results = web.get("results") or []
    if not results:
        return []
    parsed: list[dict[str, Any]] = []
    for item in results[:limit]:
        title = item.get("title") or ""
        url = item.get("url") or ""
        description = item.get("description") or ""
        extra_snippets = item.get("extra_snippets") or []
        if not description and extra_snippets:
            description = " ".join(extra_snippets[:1])
        parsed.append(
            {
                "title": title,
                "url": url,
                "snippet": description,
            }
        )
    return parsed


def _brave_news_search(
    query: str,
    settings: Settings,
    limit: int,
    country: str | None = None,
    search_lang: str | None = None,
    freshness: str | None = None,
) -> list[dict[str, Any]]:
    endpoint = "https://api.search.brave.com/res/v1/news/search"
    params: dict[str, Any] = {
        "q": query,
        "count": min(limit, 50),
        "safesearch": "moderate",
    }
    if freshness:
        params["freshness"] = freshness
    if country or settings.brave_country:
        params["country"] = country or settings.brave_country
    if search_lang or settings.brave_search_lang:
        params["search_lang"] = search_lang or settings.brave_search_lang

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": settings.brave_api_key,
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
    }
    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=headers,
            timeout=settings.web_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return [
            {
                "title": "News search failed",
                "url": "",
                "snippet": str(exc),
            }
        ]

    try:
        payload = response.json()
    except ValueError:
        return [
            {
                "title": "News search failed",
                "url": "",
                "snippet": "Invalid JSON response from Brave.",
            }
        ]

    if isinstance(payload, dict) and payload.get("error"):
        error = payload.get("error") or {}
        message = error.get("message") or "Brave API error."
        return [
            {
                "title": "News search failed",
                "url": "",
                "snippet": message,
            }
        ]

    results = payload.get("results") or payload.get("news", {}).get("results") or []
    if not results:
        return []
    parsed: list[dict[str, Any]] = []
    for item in results[:limit]:
        title = item.get("title") or ""
        url = item.get("url") or item.get("provider_url") or ""
        description = item.get("description") or item.get("snippet") or ""
        source = item.get("source") or ""
        if source and description:
            description = f"{source} — {description}"
        elif source:
            description = source
        parsed.append(
            {
                "title": title,
                "url": url,
                "snippet": description,
            }
        )
    return parsed


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_text_by_selector(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    matches = soup.select(selector)
    if not matches:
        return _extract_text(html)
    parts = []
    for item in matches:
        parts.append(item.get_text(" ", strip=True))
    text = " ".join(part for part in parts if part)
    return re.sub(r"\s+", " ", text)
