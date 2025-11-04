"""Google Search integration using Serper API"""

import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from ..models.report import Source, SourceType


class SearchClient:
    """Client for performing Google searches via Serper API"""

    def __init__(
        self,
        api_key: str,
        max_results: int = 10,
        language: str = "en",
        country: str = "us"
    ):
        """
        Initialize search client

        Args:
            api_key: Serper API key
            max_results: Maximum number of results per query
            language: Search language
            country: Search country
        """
        self.api_key = api_key
        self.max_results = max_results
        self.language = language
        self.country = country
        self.base_url = "https://google.serper.dev/search"

    async def search(
        self,
        query: str,
        num_results: Optional[int] = None,
        timeframe: Optional[str] = None,
        search_type: str = "search"
    ) -> Dict[str, Any]:
        """
        Perform a Google search

        Args:
            query: Search query
            num_results: Number of results (defaults to max_results)
            timeframe: Time filter (past_day, past_week, past_month, past_year)
            search_type: Type of search (search, news, images)

        Returns:
            Search results dictionary
        """
        num_results = num_results or self.max_results

        payload = {
            "q": query,
            "num": num_results,
            "gl": self.country,
            "hl": self.language,
        }

        # Add time filter if specified
        if timeframe:
            timeframe_map = {
                "past_day": "qdr:d",
                "past_week": "qdr:w",
                "past_month": "qdr:m",
                "past_year": "qdr:y"
            }
            if timeframe in timeframe_map:
                payload["tbs"] = timeframe_map[timeframe]

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "query": query,
                            "results": self._parse_results(data),
                            "metadata": {
                                "total_results": len(data.get("organic", [])),
                                "search_time": data.get("searchParameters", {}).get("time", 0),
                                "timestamp": datetime.utcnow().isoformat()
                            }
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}",
                            "query": query
                        }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Search request timed out",
                "query": query
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Search failed: {str(e)}",
                "query": query
            }

    def _parse_results(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse search API response into structured results"""
        results = []

        # Parse organic results
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "position": item.get("position", 0),
                "date": item.get("date"),
            })

        # Parse news results if available
        for item in data.get("news", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": item.get("source", ""),
                "date": item.get("date"),
                "type": "news"
            })

        return results

    async def search_multiple(
        self,
        queries: List[str],
        max_concurrent: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Perform multiple searches concurrently

        Args:
            queries: List of search queries
            max_concurrent: Maximum concurrent requests

        Returns:
            List of search result dictionaries
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def search_with_semaphore(query):
            async with semaphore:
                return await self.search(query)

        tasks = [search_with_semaphore(q) for q in queries]
        results = await asyncio.gather(*tasks)

        return results

    def results_to_sources(self, results: Dict[str, Any]) -> List[Source]:
        """
        Convert search results to Source objects

        Args:
            results: Search results dictionary

        Returns:
            List of Source objects
        """
        if not results.get("success"):
            return []

        sources = []
        for result in results.get("results", []):
            source_type = SourceType.NEWS_MEDIA if result.get("type") == "news" else SourceType.OTHER

            # Determine source type from URL
            url = result.get("url", "")
            if any(domain in url for domain in ["twitter.com", "x.com", "facebook.com", "telegram.org"]):
                source_type = SourceType.SOCIAL_MEDIA
            elif any(domain in url for domain in [".gov", "government"]):
                source_type = SourceType.GOVERNMENT
            elif any(domain in url for domain in ["edu", "academic", "arxiv"]):
                source_type = SourceType.ACADEMIC

            source = Source(
                url=url,
                title=result.get("title", ""),
                snippet=result.get("snippet"),
                source_type=source_type,
                published_date=self._parse_date(result.get("date")),
            )
            sources.append(source)

        return sources

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime"""
        if not date_str:
            return None

        try:
            # Try common date formats
            for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d %b %Y"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass

        return None

    def format_results_for_analysis(self, results: Dict[str, Any]) -> str:
        """
        Format search results for LLM analysis

        Args:
            results: Search results dictionary

        Returns:
            Formatted string for analysis
        """
        if not results.get("success"):
            return f"Search failed: {results.get('error', 'Unknown error')}"

        formatted = f"Search Query: {results.get('query')}\n"
        formatted += f"Total Results: {results.get('metadata', {}).get('total_results', 0)}\n\n"
        formatted += "=" * 80 + "\n\n"

        for i, result in enumerate(results.get("results", []), 1):
            formatted += f"[Result {i}]\n"
            formatted += f"Title: {result.get('title')}\n"
            formatted += f"URL: {result.get('url')}\n"
            if result.get('date'):
                formatted += f"Date: {result.get('date')}\n"
            formatted += f"Snippet: {result.get('snippet')}\n"
            formatted += "-" * 80 + "\n\n"

        return formatted

    async def search_with_context(
        self,
        base_query: str,
        context_terms: List[str],
        max_queries: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Perform contextual searches with related terms

        Args:
            base_query: Base search query
            context_terms: Additional context terms to combine
            max_queries: Maximum number of query variations

        Returns:
            Combined search results
        """
        queries = [base_query]

        # Add context variations
        for term in context_terms[:max_queries - 1]:
            queries.append(f"{base_query} {term}")

        results = await self.search_multiple(queries, max_concurrent=2)
        return results

    def test_connection(self) -> bool:
        """Test connection to Serper API"""
        try:
            # Use asyncio.run for testing
            result = asyncio.run(self.search("test", num_results=1))
            return result.get("success", False)
        except Exception:
            return False
