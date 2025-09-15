"""
Independent LLM-powered medical referral triage agent.

This package provides specialty detection and urgency determination
based on configurable client rules. Can be used in any Python runtime
(FastAPI, Flask, AWS Lambda, etc.).
"""

from .types import TriageInput, TriageResult
from .agent import TriageAgent
from .tools import TriageTools

__all__ = [
    "TriageInput",
    "TriageResult", 
    "TriageAgent",
    "TriageTools",
]

__version__ = "0.1.0"