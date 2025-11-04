"""Configuration management"""

import os
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv

from ..models.topic import Topic, TopicCategory


class Config:
    """Configuration manager for OSINT tool"""

    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration

        Args:
            config_file: Path to YAML config file
        """
        # Load environment variables
        load_dotenv()

        self.config_file = config_file
        self.config_data = {}

        if config_file and Path(config_file).exists():
            self.load_config(config_file)

        # Load API keys from environment
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.serper_api_key = os.getenv("SERPER_API_KEY")

        # Load settings
        self.max_search_results = int(os.getenv("MAX_SEARCH_RESULTS", "10"))
        self.search_language = os.getenv("SEARCH_LANGUAGE", "en")
        self.search_country = os.getenv("SEARCH_COUNTRY", "us")
        self.max_concurrent_topics = int(os.getenv("MAX_CONCURRENT_TOPICS", "5"))
        self.report_output_dir = os.getenv("REPORT_OUTPUT_DIR", "./reports")

    def load_config(self, config_file: str):
        """Load configuration from YAML file"""
        with open(config_file, 'r') as f:
            self.config_data = yaml.safe_load(f)

    def get_topics(self, topics_file: Optional[str] = None) -> List[Topic]:
        """
        Load topics from configuration file

        Args:
            topics_file: Path to topics YAML file

        Returns:
            List of Topic objects
        """
        if topics_file and Path(topics_file).exists():
            with open(topics_file, 'r') as f:
                topics_data = yaml.safe_load(f)
        elif "topics" in self.config_data:
            topics_data = self.config_data["topics"]
        else:
            # Return default topics if no config
            return self.get_default_topics()

        topics = []
        for topic_data in topics_data:
            topic = Topic(**topic_data)
            topics.append(topic)

        return topics

    def get_default_topics(self) -> List[Topic]:
        """Get default intelligence topics"""
        return [
            Topic(
                name="Wagner Group Activities",
                category=TopicCategory.SPECIAL_FORCES,
                keywords=["Wagner Group", "PMC Wagner", "Prigozhin", "mercenary"],
                priority=9,
                search_timeframe="past_month",
                focus_regions=["Africa", "Syria", "Ukraine", "Middle East"],
                analysis_depth="comprehensive"
            ),
            Topic(
                name="Black Sea Fleet Operations",
                category=TopicCategory.NAVAL_FORCES,
                keywords=["Black Sea Fleet", "Russian Navy", "Sevastopol", "Novorossiysk"],
                priority=8,
                search_timeframe="past_week",
                focus_regions=["Black Sea", "Crimea", "Mediterranean"],
                analysis_depth="comprehensive"
            ),
            Topic(
                name="GRU Intelligence Operations",
                category=TopicCategory.INTELLIGENCE_ACTIVITY,
                keywords=["GRU", "Main Intelligence Directorate", "military intelligence", "Unit 29155"],
                priority=10,
                search_timeframe="past_month",
                focus_regions=["Europe", "Eastern Europe"],
                analysis_depth="deep"
            ),
            Topic(
                name="Russian Air Force Deployments",
                category=TopicCategory.AIR_FORCES,
                keywords=["VKS", "Russian Air Force", "Su-57", "Su-35", "bomber deployments"],
                priority=7,
                search_timeframe="past_week",
                focus_regions=["Syria", "Arctic", "Baltic"],
                analysis_depth="standard"
            ),
            Topic(
                name="Cyber Operations and APT Groups",
                category=TopicCategory.CYBER_OPERATIONS,
                keywords=["APT28", "APT29", "Fancy Bear", "Cozy Bear", "Russian hackers"],
                priority=9,
                search_timeframe="past_month",
                focus_regions=["Global"],
                analysis_depth="comprehensive"
            ),
            Topic(
                name="T-14 Armata Tank Deployment",
                category=TopicCategory.EQUIPMENT,
                keywords=["T-14 Armata", "Russian tank", "armored vehicle", "new equipment"],
                priority=6,
                search_timeframe="past_month",
                focus_regions=["Ukraine", "Russia"],
                analysis_depth="standard"
            ),
        ]

    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate configuration

        Returns:
            Tuple of (is_valid, list of errors)
        """
        errors = []

        if not self.google_api_key:
            errors.append("Missing GOOGLE_API_KEY environment variable")

        if not self.serper_api_key:
            errors.append("Missing SERPER_API_KEY environment variable")

        if not Path(self.report_output_dir).parent.exists():
            errors.append(f"Invalid report output directory: {self.report_output_dir}")

        return len(errors) == 0, errors

    def create_output_directory(self):
        """Create output directory if it doesn't exist"""
        Path(self.report_output_dir).mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as dictionary"""
        return {
            "max_search_results": self.max_search_results,
            "search_language": self.search_language,
            "search_country": self.search_country,
            "max_concurrent_topics": self.max_concurrent_topics,
            "report_output_dir": self.report_output_dir,
            "has_google_api_key": bool(self.google_api_key),
            "has_serper_api_key": bool(self.serper_api_key),
        }
