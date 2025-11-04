"""Gemini Flash 2.5 API client for intelligence analysis"""

import google.generativeai as genai
from typing import Optional, Dict, Any
import asyncio
from datetime import datetime
import json


class GeminiClient:
    """Client for interacting with Google's Gemini Flash 2.5 model"""

    def __init__(self, api_key: str):
        """
        Initialize Gemini client

        Args:
            api_key: Google API key for Gemini
        """
        self.api_key = api_key
        genai.configure(api_key=api_key)

        # Configure Gemini Flash 2.5 (experimental)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-exp",  # Flash 2.5 model
            generation_config={
                "temperature": 0.3,  # Lower temperature for factual analysis
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
            },
            safety_settings={
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            }
        )

    async def analyze_intelligence(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze intelligence information using Gemini

        Args:
            prompt: Analysis prompt
            context: Optional additional context

        Returns:
            Analysis results as structured data
        """
        try:
            # Prepare the full prompt with context
            full_prompt = self._prepare_prompt(prompt, context)

            # Generate response
            response = await asyncio.to_thread(
                self.model.generate_content,
                full_prompt
            )

            # Parse and structure the response
            analysis = self._parse_response(response)

            return {
                "success": True,
                "analysis": analysis,
                "model": "gemini-2.0-flash-exp",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "prompt_tokens": getattr(response, "usage_metadata", {}).get("prompt_token_count", 0),
                    "completion_tokens": getattr(response, "usage_metadata", {}).get("candidates_token_count", 0),
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def _prepare_prompt(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Prepare the full prompt with context"""
        system_context = """You are an expert OSINT analyst with specialized knowledge in:
- Russian military doctrine and organization
- Intelligence community operations
- Geopolitical analysis
- Source verification and reliability assessment
- Operational security considerations

Your analysis should be:
- Factual and evidence-based
- Clearly structured with appropriate sections
- Confidence-rated where applicable
- Source-attributed for all claims
- Objective and unbiased
"""

        full_prompt = f"{system_context}\n\n{prompt}"

        if context:
            context_str = "\n\nAdditional Context:\n"
            for key, value in context.items():
                context_str += f"- {key}: {value}\n"
            full_prompt += context_str

        return full_prompt

    def _parse_response(self, response) -> Dict[str, Any]:
        """Parse Gemini response into structured format"""
        try:
            # Get the text from response
            text = response.text

            # Try to extract structured sections
            analysis = {
                "raw_text": text,
                "sections": self._extract_sections(text),
                "structured_data": self._extract_structured_data(text)
            }

            return analysis

        except Exception as e:
            return {
                "raw_text": str(response),
                "error": f"Failed to parse response: {str(e)}"
            }

    def _extract_sections(self, text: str) -> Dict[str, str]:
        """Extract numbered sections from analysis"""
        sections = {}
        current_section = None
        current_content = []

        for line in text.split('\n'):
            # Check if line starts a new section
            if any(marker in line for marker in [
                "EXECUTIVE SUMMARY",
                "KEY FINDINGS",
                "DETAILED ANALYSIS",
                "CONFIDENCE ASSESSMENT",
                "GEOSPATIAL CONTEXT",
                "TIMELINE",
                "RELATED ENTITIES",
                "INTELLIGENCE GAPS",
                "RECOMMENDATIONS"
            ]):
                # Save previous section
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()

                # Start new section
                current_section = line.strip().rstrip(':').strip('0123456789. ')
                current_content = []
            elif current_section:
                current_content.append(line)

        # Save last section
        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    def _extract_structured_data(self, text: str) -> Dict[str, Any]:
        """Extract structured data from text"""
        structured = {
            "key_points": [],
            "entities": [],
            "locations": [],
            "dates": []
        }

        # Extract bullet points (key findings)
        lines = text.split('\n')
        for line in lines:
            if line.strip().startswith(('•', '-', '*')):
                point = line.strip().lstrip('•-* ').strip()
                if point:
                    structured["key_points"].append(point)

        return structured

    async def batch_analyze(
        self,
        prompts: list[str],
        max_concurrent: int = 3
    ) -> list[Dict[str, Any]]:
        """
        Analyze multiple intelligence prompts in batch

        Args:
            prompts: List of analysis prompts
            max_concurrent: Maximum concurrent requests

        Returns:
            List of analysis results
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def analyze_with_semaphore(prompt):
            async with semaphore:
                return await self.analyze_intelligence(prompt)

        tasks = [analyze_with_semaphore(prompt) for prompt in prompts]
        results = await asyncio.gather(*tasks)

        return results

    def test_connection(self) -> bool:
        """Test connection to Gemini API"""
        try:
            response = self.model.generate_content("Hello, please respond with 'Connection successful'")
            return "success" in response.text.lower() or len(response.text) > 0
        except Exception:
            return False
