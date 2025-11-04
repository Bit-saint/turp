#!/usr/bin/env python3
"""
Quick Start Example
Demonstrates basic usage of the OSINT tool
"""

import asyncio
from src.core import GeminiClient, SearchClient, ReportGenerator
from src.models.topic import Topic, TopicCategory
from src.utils import Config, ReportFormatter


async def main():
    """Quick start example"""

    # Load configuration
    config = Config()

    # Validate API keys
    is_valid, errors = config.validate()
    if not is_valid:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        return

    # Initialize clients
    print("Initializing clients...")
    gemini = GeminiClient(config.google_api_key)
    search = SearchClient(config.serper_api_key)

    # Create a simple topic
    topic = Topic(
        name="Wagner Group Recent Activities",
        category=TopicCategory.SPECIAL_FORCES,
        keywords=["Wagner Group", "PMC Wagner", "Africa"],
        priority=9,
        search_timeframe="past_week",
        analysis_depth="comprehensive"
    )

    # Generate report
    print(f"Analyzing topic: {topic.name}")

    report_generator = ReportGenerator(gemini, search)
    report = await report_generator.generate_report(
        topics=[topic],
        report_title="Wagner Group Intelligence Brief"
    )

    # Print summary
    print("\n" + "=" * 80)
    print(f"Report: {report.title}")
    print(f"Topics: {report.total_topics}")
    print(f"Sources: {report.total_sources}")
    print("=" * 80)

    # Save report
    file_path = ReportFormatter.save_report(
        report=report,
        output_dir="./examples/output",
        format="markdown"
    )

    print(f"\nReport saved to: {file_path}")


if __name__ == "__main__":
    asyncio.run(main())
