#!/usr/bin/env python3
"""
Russian Military OSINT Intelligence Tool
Main entry point for intelligence report generation
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from src.core import GeminiClient, SearchClient, ReportGenerator
from src.utils import Config, ReportFormatter
from src.models.topic import Topic


console = Console()


async def main():
    """Main execution function"""
    parser = argparse.ArgumentParser(
        description="Russian Military OSINT Intelligence Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Generate report with default topics
  %(prog)s --topics "Wagner Group"            # Single topic
  %(prog)s --config config/topics.yaml        # Custom topics file
  %(prog)s --format html --output ./reports   # HTML output
  %(prog)s --test                             # Test API connections
        """
    )

    parser.add_argument(
        "--config",
        help="Path to configuration YAML file",
        type=str
    )

    parser.add_argument(
        "--topics",
        nargs="+",
        help="Specific topics to analyze (overrides config)",
        type=str
    )

    parser.add_argument(
        "--topics-file",
        help="Path to topics YAML file",
        type=str
    )

    parser.add_argument(
        "--format",
        choices=["json", "markdown", "html"],
        default="markdown",
        help="Output format (default: markdown)"
    )

    parser.add_argument(
        "--output",
        help="Output directory for reports",
        type=str
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Test API connections and exit"
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save report to file (print only)"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = Config(args.config)
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        return 1

    # Override output directory if specified
    if args.output:
        config.report_output_dir = args.output

    # Validate configuration
    is_valid, errors = config.validate()
    if not is_valid:
        console.print("[red]Configuration errors:[/red]")
        for error in errors:
            console.print(f"  - {error}")
        console.print("\n[yellow]Please check your .env file or environment variables[/yellow]")
        return 1

    # Create output directory
    config.create_output_directory()

    # Initialize clients
    console.print("\n[cyan]🔧 Initializing OSINT Intelligence Tool[/cyan]\n")

    gemini_client = GeminiClient(config.google_api_key)
    search_client = SearchClient(
        api_key=config.serper_api_key,
        max_results=config.max_search_results,
        language=config.search_language,
        country=config.search_country
    )

    # Test connections if requested
    if args.test:
        console.print("[cyan]Testing API connections...[/cyan]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task1 = progress.add_task("Testing Gemini API...", total=None)
            gemini_ok = gemini_client.test_connection()
            progress.update(task1, completed=True)

            task2 = progress.add_task("Testing Serper API...", total=None)
            search_ok = search_client.test_connection()
            progress.update(task2, completed=True)

        console.print(f"\n[{'green' if gemini_ok else 'red'}]Gemini API: {'✓ Connected' if gemini_ok else '✗ Failed'}[/]")
        console.print(f"[{'green' if search_ok else 'red'}]Serper API: {'✓ Connected' if search_ok else '✗ Failed'}[/]\n")

        return 0 if (gemini_ok and search_ok) else 1

    # Load topics
    topics = load_topics(config, args)

    if not topics:
        console.print("[red]No topics to analyze. Use --topics or --topics-file[/red]")
        return 1

    console.print(f"[green]✓ Loaded {len(topics)} topics for analysis[/green]\n")

    if args.verbose:
        for topic in topics:
            console.print(f"  • {topic.name} ({topic.category}) - Priority: {topic.priority}")
        console.print()

    # Generate report
    report_generator = ReportGenerator(
        gemini_client=gemini_client,
        search_client=search_client,
        max_concurrent_topics=config.max_concurrent_topics
    )

    console.print("[cyan]📊 Generating Intelligence Report...[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task(
            f"Analyzing {len(topics)} topics...",
            total=None
        )

        report = await report_generator.generate_report(
            topics=topics,
            report_title="Russian Military & Intelligence Activity Report"
        )

        progress.update(task, completed=True)

    # Display summary
    console.print("\n[green]✓ Report generation complete![/green]\n")
    ReportFormatter.print_summary(report)

    # Save report
    if not args.no_save:
        console.print(f"\n[cyan]💾 Saving report as {args.format}...[/cyan]")

        file_path = ReportFormatter.save_report(
            report=report,
            output_dir=config.report_output_dir,
            format=args.format
        )

        console.print(f"[green]✓ Report saved to: {file_path}[/green]\n")

    return 0


def load_topics(config: Config, args) -> List[Topic]:
    """Load topics from arguments or configuration"""
    topics = []

    if args.topics:
        # Create topics from command-line arguments
        from src.models.topic import TopicCategory

        for topic_name in args.topics:
            topic = Topic(
                name=topic_name,
                category=TopicCategory.MILITARY_OPERATIONS,
                keywords=[topic_name],
                priority=8,
                search_timeframe="past_month",
                analysis_depth="comprehensive"
            )
            topics.append(topic)

    elif args.topics_file:
        # Load from topics file
        topics = config.get_topics(args.topics_file)

    else:
        # Load default topics
        topics = config.get_topics()

    return topics


def run():
    """Entry point for the CLI"""
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
        return 130
    except Exception as e:
        console.print(f"\n[red]✗ Error: {e}[/red]")
        if "--verbose" in sys.argv or "-v" in sys.argv:
            import traceback
            console.print("\n[red]Traceback:[/red]")
            console.print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(run())
