# Russian Military OSINT Intelligence Tool

A sophisticated OSINT (Open Source Intelligence) tool for generating intelligence reports on Russian military and intelligence activity using Google's Gemini Flash 2.5 and integrated Google Search.

## Features

- **Multi-Topic Analysis**: Process multiple intelligence topics in parallel
- **Gemini Flash 2.5 Integration**: Advanced AI analysis using Google's latest model
- **Google Search Integration**: Real-time web search for current intelligence
- **Structured Reports**: Generate comprehensive, structured intelligence reports
- **Export Formats**: JSON, Markdown, and HTML report outputs
- **Confidence Scoring**: Automatic confidence and reliability assessment
- **Source Tracking**: Full citation and source verification

## Architecture

```
osint-tool/
├── src/
│   ├── core/
│   │   ├── gemini_client.py      # Gemini API integration
│   │   ├── search_client.py      # Google Search integration
│   │   └── report_generator.py   # Report generation engine
│   ├── models/
│   │   ├── topic.py              # Topic data models
│   │   └── report.py             # Report data models
│   └── utils/
│       ├── config.py             # Configuration management
│       └── formatters.py         # Output formatters
├── config/
│   ├── topics.yaml               # Intelligence topics configuration
│   └── config.yaml               # API and tool configuration
├── reports/                      # Generated reports output
├── main.py                       # Main entry point
└── requirements.txt              # Python dependencies
```

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

1. Set up your API keys:
```bash
export GOOGLE_API_KEY="your-gemini-api-key"
export SERPER_API_KEY="your-serper-api-key"  # For Google Search
```

2. Configure topics in `config/topics.yaml`

## Usage

```bash
# Generate reports for all configured topics
python main.py

# Generate report for specific topics
python main.py --topics "Wagner Group" "Black Sea Fleet"

# Export in specific format
python main.py --format markdown

# Set custom output directory
python main.py --output ./my-reports
```

## Report Structure

Each intelligence report includes:
- Executive Summary
- Key Findings
- Detailed Analysis
- Source Citations
- Confidence Assessment
- Geospatial Context
- Timeline of Events
- Related Entities

## Security & Ethics

This tool is designed for legitimate OSINT research and defensive security purposes:
- Only uses publicly available information
- Respects API rate limits and terms of service
- Includes source verification and confidence scoring
- Suitable for: threat intelligence, security research, journalism, academic research

## License

MIT License
