"""Report formatting utilities"""

import json
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from ..models.report import Report, IntelligenceReport


class ReportFormatter:
    """Formatter for intelligence reports in various formats"""

    @staticmethod
    def to_json(report: Report, indent: int = 2) -> str:
        """
        Format report as JSON

        Args:
            report: Report object
            indent: JSON indentation

        Returns:
            JSON string
        """
        return report.model_dump_json(indent=indent)

    @staticmethod
    def to_markdown(report: Report) -> str:
        """
        Format report as Markdown

        Args:
            report: Report object

        Returns:
            Markdown formatted string
        """
        md = f"""# {report.title}

**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Version:** {report.version}
**Topics Analyzed:** {report.total_topics}
**Total Sources:** {report.total_sources}

---

## Executive Summary

{ReportFormatter._generate_executive_summary(report)}

---

"""

        # Add each intelligence report
        for i, intel_report in enumerate(report.intelligence_reports, 1):
            md += ReportFormatter._intelligence_report_to_markdown(intel_report, i)
            md += "\n---\n\n"

        # Add footer
        md += f"""
## Report Metadata

- **Generation Time:** {report.generated_at.isoformat()}
- **Total Topics:** {report.total_topics}
- **Total Sources:** {report.total_sources}
- **Report Version:** {report.version}

---

*This report was generated using OSINT (Open Source Intelligence) methods and AI-assisted analysis.*
*All information is based on publicly available sources and should be verified independently.*
"""

        return md

    @staticmethod
    def _generate_executive_summary(report: Report) -> str:
        """Generate executive summary for the report"""
        summary = report.get_summary()

        summary_text = f"""This intelligence report analyzes **{summary['total_topics']} topics** related to Russian military and intelligence activities, drawing from **{summary['total_sources']} sources**.

**Categories Covered:** {', '.join(summary['categories'])}

**Overall Confidence Level:** {summary['overall_confidence'].upper()}

### Key Highlights

"""
        # Add top findings from each report
        for intel_report in report.intelligence_reports[:3]:  # Top 3
            summary_text += f"- **{intel_report.topic_name}:** {intel_report.executive_summary}\n"

        return summary_text

    @staticmethod
    def _intelligence_report_to_markdown(intel_report: IntelligenceReport, index: int) -> str:
        """Format a single intelligence report as markdown"""
        md = f"""## {index}. {intel_report.topic_name}

**Category:** {intel_report.category}
**Generated:** {intel_report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Overall Confidence:** {intel_report.get_overall_confidence().value.upper()}

### Executive Summary

{intel_report.executive_summary}

### Key Findings

"""

        # Add findings
        for i, finding in enumerate(intel_report.key_findings, 1):
            md += f"""
#### Finding {i}: {finding.title}

**Confidence:** {finding.confidence.value.upper()}
**Tags:** {', '.join(finding.tags) if finding.tags else 'None'}

{finding.description}

"""
            if finding.sources:
                md += "**Sources:**\n"
                for source in finding.sources[:3]:
                    md += f"- [{source.title}]({source.url})\n"
                md += "\n"

        # Detailed Analysis
        md += f"""
### Detailed Analysis

{intel_report.detailed_analysis}

"""

        # Confidence Assessment
        if intel_report.confidence_assessment:
            md += f"""
### Confidence Assessment

**Level:** {intel_report.confidence_assessment.get('level', 'unknown').upper()}

{intel_report.confidence_assessment.get('reasoning', 'No assessment provided')}

"""

        # Geospatial Context
        if intel_report.geospatial_context:
            md += f"""
### Geospatial Context

{intel_report.geospatial_context}

"""

        # Timeline
        if intel_report.timeline:
            md += """
### Timeline

"""
            for event in intel_report.timeline:
                if 'date' in event:
                    md += f"- **{event['date']}:** {event['event']}\n"
                else:
                    md += f"- {event.get('event', event.get('raw', ''))}\n"
            md += "\n"

        # Related Entities
        if intel_report.related_entities:
            md += f"""
### Related Entities

{', '.join(intel_report.related_entities)}

"""

        # Intelligence Gaps
        if intel_report.intelligence_gaps:
            md += """
### Intelligence Gaps

"""
            for gap in intel_report.intelligence_gaps:
                md += f"- {gap}\n"
            md += "\n"

        # Recommendations
        if intel_report.recommendations:
            md += """
### Recommendations

"""
            for rec in intel_report.recommendations:
                md += f"- {rec}\n"
            md += "\n"

        # Sources
        if intel_report.sources:
            md += f"""
### Sources ({len(intel_report.sources)} total)

"""
            for i, source in enumerate(intel_report.sources[:10], 1):  # Top 10
                md += f"{i}. [{source.title}]({source.url})\n"
                if source.snippet:
                    md += f"   > {source.snippet[:150]}...\n"
                md += f"   *Type: {source.source_type}*\n\n"

        return md

    @staticmethod
    def to_html(report: Report) -> str:
        """
        Format report as HTML

        Args:
            report: Report object

        Returns:
            HTML formatted string
        """
        # Convert markdown to HTML-friendly format
        md_content = ReportFormatter.to_markdown(report)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report.title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background-color: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 8px;
        }}
        h3 {{
            color: #7f8c8d;
            margin-top: 20px;
        }}
        .metadata {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .confidence-high {{
            color: #27ae60;
            font-weight: bold;
        }}
        .confidence-medium {{
            color: #f39c12;
            font-weight: bold;
        }}
        .confidence-low {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .finding {{
            background-color: #f9f9f9;
            padding: 15px;
            margin: 15px 0;
            border-left: 4px solid #3498db;
            border-radius: 4px;
        }}
        .source {{
            font-size: 0.9em;
            color: #7f8c8d;
            margin: 5px 0;
        }}
        .tag {{
            display: inline-block;
            background-color: #3498db;
            color: white;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            margin-right: 5px;
        }}
        hr {{
            border: none;
            border-top: 2px solid #ecf0f1;
            margin: 30px 0;
        }}
        a {{
            color: #3498db;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <pre style="white-space: pre-wrap;">{md_content}</pre>
    </div>
</body>
</html>
"""
        return html

    @staticmethod
    def save_report(
        report: Report,
        output_dir: str,
        format: str = "markdown"
    ) -> Path:
        """
        Save report to file

        Args:
            report: Report object
            output_dir: Output directory
            format: Format (json, markdown, html)

        Returns:
            Path to saved file
        """
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"intelligence_report_{timestamp}"

        if format == "json":
            file_path = output_path / f"{filename}.json"
            content = ReportFormatter.to_json(report)
        elif format == "html":
            file_path = output_path / f"{filename}.html"
            content = ReportFormatter.to_html(report)
        else:  # markdown
            file_path = output_path / f"{filename}.md"
            content = ReportFormatter.to_markdown(report)

        # Write file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return file_path

    @staticmethod
    def print_summary(report: Report):
        """Print colored summary to console"""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel

            console = Console()

            # Create summary panel
            summary = report.get_summary()
            summary_text = f"""
[bold]Topics Analyzed:[/bold] {summary['total_topics']}
[bold]Total Sources:[/bold] {summary['total_sources']}
[bold]Overall Confidence:[/bold] {summary['overall_confidence'].upper()}
[bold]Generated:[/bold] {summary['generated_at']}
"""
            console.print(Panel(summary_text, title=f"[bold cyan]{report.title}[/bold cyan]", border_style="cyan"))

            # Create topics table
            table = Table(title="Topics Analyzed")
            table.add_column("Topic", style="cyan")
            table.add_column("Category", style="magenta")
            table.add_column("Findings", style="green")
            table.add_column("Confidence", style="yellow")

            for intel_report in report.intelligence_reports:
                confidence = intel_report.get_overall_confidence().value
                table.add_row(
                    intel_report.topic_name,
                    intel_report.category,
                    str(len(intel_report.key_findings)),
                    confidence.upper()
                )

            console.print(table)

        except ImportError:
            # Fallback to simple print
            print(f"\n{report.title}")
            print("=" * 80)
            print(f"Topics: {report.total_topics}")
            print(f"Sources: {report.total_sources}")
            print(f"Generated: {report.generated_at}")
            print("\nTopics Analyzed:")
            for intel_report in report.intelligence_reports:
                print(f"  - {intel_report.topic_name} ({intel_report.category})")
