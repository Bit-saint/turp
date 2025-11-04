# Usage Guide

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd turp

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your API keys
```

### 2. API Keys Setup

You need two API keys:

#### Google Gemini API Key
1. Visit https://makersuite.google.com/app/apikey
2. Create a new API key
3. Add to `.env`: `GOOGLE_API_KEY=your-key-here`

#### Serper API Key (Google Search)
1. Visit https://serper.dev/
2. Sign up for a free account (2,500 free searches/month)
3. Get your API key from the dashboard
4. Add to `.env`: `SERPER_API_KEY=your-key-here`

### 3. Test Connection

```bash
python main.py --test
```

This will verify your API keys are working correctly.

## Basic Usage

### Generate Report with Default Topics

```bash
python main.py
```

This will analyze the default topics defined in the configuration and save a markdown report.

### Analyze Specific Topics

```bash
python main.py --topics "Wagner Group" "Black Sea Fleet"
```

### Use Custom Topics File

```bash
python main.py --topics-file config/topics.yaml
```

### Change Output Format

```bash
# Markdown (default)
python main.py --format markdown

# JSON
python main.py --format json

# HTML
python main.py --format html
```

### Custom Output Directory

```bash
python main.py --output ./my-reports
```

## Advanced Usage

### Custom Configuration

Create your own `config.yaml`:

```yaml
search:
  max_results: 15
  language: "en"
  country: "us"

report:
  output_dir: "./intelligence_reports"
  max_concurrent_topics: 3
```

Run with:
```bash
python main.py --config my_config.yaml
```

### Verbose Mode

```bash
python main.py --verbose
```

### Don't Save (Print Only)

```bash
python main.py --no-save
```

## Python API Usage

### Basic Example

```python
import asyncio
from src.core import GeminiClient, SearchClient, ReportGenerator
from src.models.topic import Topic, TopicCategory
from src.utils import Config, ReportFormatter

async def main():
    config = Config()

    # Initialize clients
    gemini = GeminiClient(config.google_api_key)
    search = SearchClient(config.serper_api_key)

    # Create topic
    topic = Topic(
        name="Wagner Group Activities",
        category=TopicCategory.SPECIAL_FORCES,
        keywords=["Wagner Group", "PMC"],
        priority=9
    )

    # Generate report
    generator = ReportGenerator(gemini, search)
    report = await generator.generate_report([topic])

    # Save report
    ReportFormatter.save_report(report, "./reports", "markdown")

asyncio.run(main())
```

### Process Multiple Topics in Parallel

```python
topics = [
    Topic(name="Topic 1", category=TopicCategory.MILITARY_OPERATIONS, ...),
    Topic(name="Topic 2", category=TopicCategory.NAVAL_FORCES, ...),
    Topic(name="Topic 3", category=TopicCategory.CYBER_OPERATIONS, ...),
]

generator = ReportGenerator(gemini, search, max_concurrent_topics=3)
report = await generator.generate_report(topics)
```

### Custom Search and Analysis

```python
# Custom search
search_results = await search.search(
    query="Russian military Syria",
    num_results=20,
    timeframe="past_week"
)

# Custom AI analysis
analysis = await gemini.analyze_intelligence(
    prompt="Analyze these findings...",
    context={"region": "Middle East"}
)
```

## Topics Configuration

### Topic Structure

```yaml
- name: "Topic Name"
  category: "category_name"  # See categories below
  keywords:
    - "keyword1"
    - "keyword2"
  priority: 8  # 1-10
  search_timeframe: "past_month"  # past_day, past_week, past_month, past_year
  focus_regions:
    - "Region 1"
    - "Region 2"
  analysis_depth: "comprehensive"  # basic, standard, comprehensive, deep
  exclude_terms:
    - "exclude1"
```

### Available Categories

- `military_operations`
- `intelligence_activity`
- `naval_forces`
- `air_forces`
- `ground_forces`
- `cyber_operations`
- `special_forces`
- `equipment`
- `personnel`
- `geopolitical`

### Priority Levels

- **10**: Critical - Immediate threat or high strategic importance
- **9**: High - Significant activity requiring attention
- **8**: Important - Notable developments
- **7**: Medium - Regular monitoring
- **6**: Normal - Routine intelligence
- **5**: Low - Background information

## Report Formats

### Markdown (.md)

Clean, readable format suitable for:
- GitHub/GitLab
- Documentation
- Quick review

### JSON (.json)

Structured data format suitable for:
- Further processing
- Integration with other tools
- Data analysis

### HTML (.html)

Styled web format suitable for:
- Presentations
- Web publishing
- Sharing with stakeholders

## Output Structure

### Report Contains

1. **Executive Summary** - High-level overview
2. **Topics Analysis** - Detailed analysis per topic
3. **Key Findings** - Important discoveries with confidence levels
4. **Detailed Analysis** - Comprehensive breakdown
5. **Confidence Assessment** - Reliability evaluation
6. **Geospatial Context** - Geographic information
7. **Timeline** - Chronological events
8. **Related Entities** - Organizations, units, individuals
9. **Intelligence Gaps** - Missing information
10. **Recommendations** - Suggested follow-up actions
11. **Sources** - All references with links

### Confidence Levels

- **High**: Multiple verified sources, corroborated information
- **Medium**: Credible sources, some verification
- **Low**: Single source or unverified claims
- **Unverified**: Speculation or rumors

## Best Practices

### Search Strategy

1. **Be Specific**: Use precise keywords
2. **Use Timeframes**: Focus on recent activity
3. **Exclude Noise**: Add exclusion terms
4. **Geographic Focus**: Specify regions

### Analysis Depth

- **Basic**: Quick overview, 1-2 sources
- **Standard**: Normal analysis, 5-10 sources
- **Comprehensive**: Detailed analysis, 10-15 sources
- **Deep**: Extensive research, 15+ sources

### Rate Limiting

- Serper free tier: 2,500 searches/month
- Gemini free tier: 60 requests/minute
- Consider batch processing for large topic lists

## Troubleshooting

### API Errors

```bash
# Test connections
python main.py --test

# Check verbose output
python main.py --verbose
```

### Common Issues

**"Missing GOOGLE_API_KEY"**
- Ensure `.env` file exists
- Check API key is valid
- Try setting environment variable directly: `export GOOGLE_API_KEY=your-key`

**"Search request timed out"**
- Check internet connection
- Reduce concurrent topics: `--config` with lower `max_concurrent_topics`

**"Rate limit exceeded"**
- Wait and retry
- Reduce number of topics
- Check API quotas

## Security Notes

- Never commit `.env` file
- Keep API keys secure
- Rotate keys regularly
- Use read-only API keys when possible

## Examples

See the `examples/` directory for:
- `quick_start.py` - Basic usage
- `custom_topics.py` - Custom topic creation
- More examples coming soon!

## Support

For issues or questions:
1. Check this guide
2. Review examples
3. Check API documentation
4. Open an issue on GitHub
