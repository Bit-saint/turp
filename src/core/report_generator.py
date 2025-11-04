"""Intelligence report generation engine"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import re

from ..models.topic import Topic
from ..models.report import (
    IntelligenceReport,
    Report,
    Finding,
    Source,
    ConfidenceLevel
)
from .gemini_client import GeminiClient
from .search_client import SearchClient


class ReportGenerator:
    """Generates intelligence reports from topics using search and AI analysis"""

    def __init__(
        self,
        gemini_client: GeminiClient,
        search_client: SearchClient,
        max_concurrent_topics: int = 5
    ):
        """
        Initialize report generator

        Args:
            gemini_client: Gemini AI client
            search_client: Google Search client
            max_concurrent_topics: Maximum topics to process concurrently
        """
        self.gemini = gemini_client
        self.search = search_client
        self.max_concurrent_topics = max_concurrent_topics

    async def generate_report(
        self,
        topics: List[Topic],
        report_title: str = "Russian Military & Intelligence Activity Report"
    ) -> Report:
        """
        Generate complete intelligence report for multiple topics

        Args:
            topics: List of topics to research
            report_title: Title for the report

        Returns:
            Complete Report object
        """
        report = Report(
            title=report_title,
            description=f"OSINT Intelligence Report covering {len(topics)} topics"
        )

        # Process topics with concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent_topics)

        async def process_with_semaphore(topic):
            async with semaphore:
                return await self.generate_intelligence_report(topic)

        # Process all topics
        tasks = [process_with_semaphore(topic) for topic in topics]
        intelligence_reports = await asyncio.gather(*tasks)

        # Add successful reports
        for intel_report in intelligence_reports:
            if intel_report:
                report.add_intelligence_report(intel_report)

        return report

    async def generate_intelligence_report(
        self,
        topic: Topic
    ) -> Optional[IntelligenceReport]:
        """
        Generate intelligence report for a single topic

        Args:
            topic: Topic to research

        Returns:
            IntelligenceReport or None if failed
        """
        try:
            # Step 1: Perform search
            search_query = topic.get_search_query()
            search_results = await self.search.search(
                query=search_query,
                timeframe=topic.search_timeframe
            )

            if not search_results.get("success"):
                print(f"❌ Search failed for topic '{topic.name}': {search_results.get('error')}")
                return None

            # Step 2: Format search results for analysis
            formatted_results = self.search.format_results_for_analysis(search_results)

            # Step 3: Generate AI analysis
            analysis_prompt = topic.get_analysis_prompt(formatted_results)
            analysis_result = await self.gemini.analyze_intelligence(
                prompt=analysis_prompt,
                context={
                    "topic_name": topic.name,
                    "category": topic.category,
                    "priority": topic.priority
                }
            )

            if not analysis_result.get("success"):
                print(f"❌ Analysis failed for topic '{topic.name}': {analysis_result.get('error')}")
                return None

            # Step 4: Parse analysis into structured report
            analysis = analysis_result.get("analysis", {})
            sections = analysis.get("sections", {})

            # Extract sources
            sources = self.search.results_to_sources(search_results)

            # Parse key findings
            key_findings = self._extract_findings(
                sections.get("KEY FINDINGS", ""),
                sources
            )

            # Build intelligence report
            intelligence_report = IntelligenceReport(
                topic_name=topic.name,
                category=topic.category,
                executive_summary=sections.get("EXECUTIVE SUMMARY", "No summary available"),
                key_findings=key_findings,
                detailed_analysis=sections.get("DETAILED ANALYSIS", "No detailed analysis available"),
                confidence_assessment=self._parse_confidence_assessment(
                    sections.get("CONFIDENCE ASSESSMENT", "")
                ),
                geospatial_context=sections.get("GEOSPATIAL CONTEXT"),
                timeline=self._parse_timeline(sections.get("TIMELINE", "")),
                related_entities=self._parse_list(sections.get("RELATED ENTITIES", "")),
                intelligence_gaps=self._parse_list(sections.get("INTELLIGENCE GAPS", "")),
                recommendations=self._parse_list(sections.get("RECOMMENDATIONS", "")),
                sources=sources,
                metadata={
                    "topic_priority": topic.priority,
                    "search_query": search_query,
                    "total_search_results": len(search_results.get("results", [])),
                    "analysis_model": analysis_result.get("model", "unknown"),
                    "analysis_tokens": analysis_result.get("metadata", {}),
                }
            )

            return intelligence_report

        except Exception as e:
            print(f"❌ Error generating report for topic '{topic.name}': {str(e)}")
            return None

    def _extract_findings(self, findings_text: str, sources: List[Source]) -> List[Finding]:
        """Extract structured findings from text"""
        findings = []

        # Split by bullet points or numbers
        lines = findings_text.split('\n')
        current_finding = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if it's a new finding (starts with bullet or number)
            if line.startswith(('•', '-', '*', '1.', '2.', '3.', '4.', '5.')):
                # Save previous finding
                if current_finding:
                    finding_text = ' '.join(current_finding)
                    findings.append(self._create_finding(finding_text, sources))

                # Start new finding
                current_finding = [line.lstrip('•-*0123456789. ')]
            else:
                current_finding.append(line)

        # Save last finding
        if current_finding:
            finding_text = ' '.join(current_finding)
            findings.append(self._create_finding(finding_text, sources))

        return findings

    def _create_finding(self, text: str, sources: List[Source]) -> Finding:
        """Create a Finding object from text"""
        # Determine confidence based on language used
        confidence = ConfidenceLevel.MEDIUM

        if any(word in text.lower() for word in ['confirmed', 'verified', 'multiple sources']):
            confidence = ConfidenceLevel.HIGH
        elif any(word in text.lower() for word in ['reported', 'alleged', 'possibly', 'may']):
            confidence = ConfidenceLevel.LOW
        elif any(word in text.lower() for word in ['unconfirmed', 'rumored', 'speculation']):
            confidence = ConfidenceLevel.UNVERIFIED

        # Extract title (first sentence or first 100 chars)
        sentences = text.split('.')
        title = sentences[0][:100] if sentences else text[:100]

        # Extract tags (simple keyword extraction)
        tags = self._extract_tags(text)

        return Finding(
            title=title,
            description=text,
            confidence=confidence,
            sources=sources[:3],  # Top 3 sources
            tags=tags
        )

    def _extract_tags(self, text: str) -> List[str]:
        """Extract relevant tags from text"""
        # Simple keyword extraction
        keywords = [
            "military", "naval", "air force", "intelligence", "cyber",
            "Wagner", "GRU", "FSB", "SVR", "Black Sea", "Ukraine",
            "deployment", "operation", "equipment", "personnel"
        ]

        tags = []
        text_lower = text.lower()
        for keyword in keywords:
            if keyword in text_lower:
                tags.append(keyword)

        return tags[:5]  # Max 5 tags

    def _parse_confidence_assessment(self, text: str) -> Dict[str, Any]:
        """Parse confidence assessment into structured format"""
        confidence_data = {
            "level": "medium",
            "reasoning": text,
            "factors": []
        }

        text_lower = text.lower()

        if "high confidence" in text_lower:
            confidence_data["level"] = "high"
        elif "low confidence" in text_lower:
            confidence_data["level"] = "low"

        # Extract factors
        if "multiple sources" in text_lower:
            confidence_data["factors"].append("multiple_sources")
        if "verified" in text_lower:
            confidence_data["factors"].append("verified")
        if "corroborate" in text_lower:
            confidence_data["factors"].append("corroborated")

        return confidence_data

    def _parse_timeline(self, text: str) -> List[Dict[str, Any]]:
        """Parse timeline events from text"""
        events = []
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to extract date patterns
            date_match = re.search(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b', line)
            if date_match:
                events.append({
                    "date": date_match.group(0),
                    "event": line,
                    "raw": line
                })
            elif line.startswith(('•', '-', '*')):
                events.append({
                    "event": line.lstrip('•-* '),
                    "raw": line
                })

        return events

    def _parse_list(self, text: str) -> List[str]:
        """Parse bulleted/numbered list into array"""
        items = []
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Remove bullet points and numbers
            cleaned = line.lstrip('•-*0123456789. ').strip()
            if cleaned:
                items.append(cleaned)

        return items

    async def generate_summary_report(
        self,
        report: Report,
        output_file: Optional[str] = None
    ) -> str:
        """
        Generate executive summary of the full report

        Args:
            report: Complete report
            output_file: Optional file to save summary

        Returns:
            Summary text
        """
        summary_prompt = f"""Generate a concise executive summary for this intelligence report.

Report Details:
- Title: {report.title}
- Total Topics: {report.total_topics}
- Total Sources: {report.total_sources}

Topics covered:
{self._format_topics_for_summary(report)}

Provide a 3-5 paragraph executive summary highlighting:
1. Most critical findings
2. Overall threat assessment
3. Key trends and patterns
4. Priority areas for attention
"""

        result = await self.gemini.analyze_intelligence(summary_prompt)

        if result.get("success"):
            summary = result.get("analysis", {}).get("raw_text", "")

            if output_file:
                with open(output_file, 'w') as f:
                    f.write(summary)

            return summary
        else:
            return "Failed to generate summary"

    def _format_topics_for_summary(self, report: Report) -> str:
        """Format topics list for summary generation"""
        formatted = ""
        for intel_report in report.intelligence_reports:
            formatted += f"- {intel_report.topic_name} ({intel_report.category})\n"
            formatted += f"  Summary: {intel_report.executive_summary[:200]}...\n"
        return formatted
