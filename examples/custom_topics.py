#!/usr/bin/env python3
"""
Custom Topics Example
Demonstrates creating custom intelligence topics
"""

import asyncio
from src.core import GeminiClient, SearchClient, ReportGenerator
from src.models.topic import Topic, TopicCategory
from src.utils import Config, ReportFormatter


async def main():
    """Custom topics example"""

    config = Config()

    # Initialize clients
    gemini = GeminiClient(config.google_api_key)
    search = SearchClient(config.serper_api_key)

    # Create custom topics with specific focus
    topics = [
        Topic(
            name="S-400 Deployment in Syria",
            category=TopicCategory.EQUIPMENT,
            keywords=["S-400", "Syria", "air defense", "Russian military"],
            priority=8,
            search_timeframe="past_month",
            focus_regions=["Syria", "Middle East"],
            analysis_depth="deep"
        ),

        Topic(
            name="Russian Naval Activity Near UK Waters",
            category=TopicCategory.NAVAL_FORCES,
            keywords=["Russian Navy", "UK waters", "North Sea", "warship"],
            priority=7,
            search_timeframe="past_week",
            focus_regions=["North Sea", "UK", "Norway"],
            analysis_depth="comprehensive"
        ),

        Topic(
            name="Sandworm APT Cyber Campaigns",
            category=TopicCategory.CYBER_OPERATIONS,
            keywords=["Sandworm", "Unit 74455", "Ukraine cyber", "GRU cyber"],
            priority=10,
            search_timeframe="past_month",
            focus_regions=["Ukraine", "Europe"],
            exclude_terms=["game", "sci-fi"],
            analysis_depth="deep"
        ),
    ]

    # Generate report
    print(f"Analyzing {len(topics)} custom topics...")

    report_generator = ReportGenerator(gemini, search, max_concurrent_topics=3)

    report = await report_generator.generate_report(
        topics=topics,
        report_title="Custom Intelligence Report - Focused Analysis"
    )

    # Display results
    ReportFormatter.print_summary(report)

    # Save in multiple formats
    for format_type in ["markdown", "json", "html"]:
        file_path = ReportFormatter.save_report(
            report=report,
            output_dir="./examples/output",
            format=format_type
        )
        print(f"Saved {format_type}: {file_path}")


if __name__ == "__main__":
    asyncio.run(main())
