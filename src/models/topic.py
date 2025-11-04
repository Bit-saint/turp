"""Topic data models for OSINT intelligence gathering"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class TopicCategory(str, Enum):
    """Categories for intelligence topics"""
    MILITARY_OPERATIONS = "military_operations"
    INTELLIGENCE_ACTIVITY = "intelligence_activity"
    NAVAL_FORCES = "naval_forces"
    AIR_FORCES = "air_forces"
    GROUND_FORCES = "ground_forces"
    CYBER_OPERATIONS = "cyber_operations"
    SPECIAL_FORCES = "special_forces"
    EQUIPMENT = "equipment"
    PERSONNEL = "personnel"
    GEOPOLITICAL = "geopolitical"


class Topic(BaseModel):
    """Represents an intelligence topic to research"""

    name: str = Field(..., description="Name of the topic")
    category: TopicCategory = Field(..., description="Category of the topic")
    keywords: List[str] = Field(
        default_factory=list,
        description="Search keywords related to this topic"
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority level (1-10, higher is more important)"
    )
    search_timeframe: Optional[str] = Field(
        default="past_month",
        description="Timeframe for search (past_day, past_week, past_month, past_year)"
    )
    exclude_terms: List[str] = Field(
        default_factory=list,
        description="Terms to exclude from search"
    )
    focus_regions: List[str] = Field(
        default_factory=list,
        description="Geographic regions of focus"
    )
    analysis_depth: str = Field(
        default="comprehensive",
        description="Level of analysis (basic, standard, comprehensive, deep)"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True

    def get_search_query(self) -> str:
        """Generate optimized search query for this topic"""
        query_parts = [self.name]

        if self.keywords:
            query_parts.extend(self.keywords[:3])  # Top 3 keywords

        if self.focus_regions:
            query_parts.extend(self.focus_regions[:2])  # Top 2 regions

        query = " ".join(query_parts)

        # Add exclusions
        if self.exclude_terms:
            exclusions = " ".join([f'-"{term}"' for term in self.exclude_terms])
            query = f"{query} {exclusions}"

        return query

    def get_analysis_prompt(self, search_results: str) -> str:
        """Generate analysis prompt for Gemini"""
        return f"""You are an expert OSINT analyst specializing in Russian military and intelligence activities.

Topic: {self.name}
Category: {self.category}
Priority: {self.priority}/10
Analysis Depth: {self.analysis_depth}
{"Focus Regions: " + ", ".join(self.focus_regions) if self.focus_regions else ""}

Based on the following search results, provide a comprehensive intelligence analysis:

{search_results}

Please structure your analysis with:
1. EXECUTIVE SUMMARY (2-3 sentences)
2. KEY FINDINGS (bullet points, most important information)
3. DETAILED ANALYSIS (comprehensive breakdown)
4. CONFIDENCE ASSESSMENT (high/medium/low with justification)
5. GEOSPATIAL CONTEXT (if applicable)
6. TIMELINE (chronological events if applicable)
7. RELATED ENTITIES (organizations, units, individuals mentioned)
8. INTELLIGENCE GAPS (what information is missing or unclear)
9. RECOMMENDATIONS (for further investigation)

Prioritize:
- Factual accuracy and source verification
- Operational security considerations
- Strategic implications
- Tactical details when available
- Cross-referencing multiple sources

Be objective, cite specific sources, and clearly distinguish between confirmed information and speculation."""
