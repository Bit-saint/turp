"""Report data models for intelligence outputs"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime
from enum import Enum


class ConfidenceLevel(str, Enum):
    """Confidence levels for intelligence assessments"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"


class SourceType(str, Enum):
    """Types of intelligence sources"""
    NEWS_MEDIA = "news_media"
    SOCIAL_MEDIA = "social_media"
    GOVERNMENT = "government"
    THINK_TANK = "think_tank"
    ACADEMIC = "academic"
    OPEN_DATABASE = "open_database"
    SATELLITE_IMAGERY = "satellite_imagery"
    OTHER = "other"


class Source(BaseModel):
    """Represents a source of information"""

    url: str
    title: str
    snippet: Optional[str] = None
    source_type: SourceType = SourceType.OTHER
    published_date: Optional[datetime] = None
    reliability: Optional[str] = None
    accessed_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class Finding(BaseModel):
    """Represents a key intelligence finding"""

    title: str
    description: str
    confidence: ConfidenceLevel
    sources: List[Source] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    geolocation: Optional[str] = None
    timestamp: Optional[datetime] = None

    class Config:
        use_enum_values = True


class IntelligenceReport(BaseModel):
    """Complete intelligence report structure"""

    topic_name: str
    category: str
    executive_summary: str
    key_findings: List[Finding] = Field(default_factory=list)
    detailed_analysis: str
    confidence_assessment: Dict[str, Any] = Field(default_factory=dict)
    geospatial_context: Optional[str] = None
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    related_entities: List[str] = Field(default_factory=list)
    intelligence_gaps: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_overall_confidence(self) -> ConfidenceLevel:
        """Calculate overall confidence level from findings"""
        if not self.key_findings:
            return ConfidenceLevel.UNVERIFIED

        confidence_scores = {
            ConfidenceLevel.HIGH: 3,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.LOW: 1,
            ConfidenceLevel.UNVERIFIED: 0
        }

        avg_score = sum(
            confidence_scores.get(f.confidence, 0)
            for f in self.key_findings
        ) / len(self.key_findings)

        if avg_score >= 2.5:
            return ConfidenceLevel.HIGH
        elif avg_score >= 1.5:
            return ConfidenceLevel.MEDIUM
        elif avg_score >= 0.5:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.UNVERIFIED


class Report(BaseModel):
    """Main report container"""

    title: str
    description: Optional[str] = None
    intelligence_reports: List[IntelligenceReport] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    total_sources: int = 0
    total_topics: int = 0

    def add_intelligence_report(self, report: IntelligenceReport):
        """Add an intelligence report"""
        self.intelligence_reports.append(report)
        self.total_sources += len(report.sources)
        self.total_topics = len(self.intelligence_reports)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics"""
        return {
            "title": self.title,
            "total_topics": self.total_topics,
            "total_sources": self.total_sources,
            "generated_at": self.generated_at.isoformat(),
            "categories": list(set(r.category for r in self.intelligence_reports)),
            "overall_confidence": self._calculate_overall_confidence()
        }

    def _calculate_overall_confidence(self) -> str:
        """Calculate overall confidence across all reports"""
        if not self.intelligence_reports:
            return "unverified"

        confidence_counts = {
            ConfidenceLevel.HIGH: 0,
            ConfidenceLevel.MEDIUM: 0,
            ConfidenceLevel.LOW: 0,
            ConfidenceLevel.UNVERIFIED: 0
        }

        for report in self.intelligence_reports:
            confidence_counts[report.get_overall_confidence()] += 1

        total = len(self.intelligence_reports)
        if confidence_counts[ConfidenceLevel.HIGH] / total >= 0.5:
            return "high"
        elif confidence_counts[ConfidenceLevel.MEDIUM] / total >= 0.5:
            return "medium"
        else:
            return "low"
