"""
Pydantic types for the triage agent.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Specialty(str, Enum):
    """Medical specialties enum."""
    ALLERGY = "ALLERGY"
    AUDIOLOGY = "AUDIOLOGY" 
    CARDIOLOGY = "CARDIOLOGY"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    EAR_NOSE_AND_THROAT_OTOLARYNGOLOGY = "EAR_NOSE_AND_THROAT_OTOLARYNGOLOGY"
    GASTROENTEROLOGY = "GASTROENTEROLOGY"
    GENERAL_SURGERY = "GENERAL_SURGERY"
    GENDER_CLINIC = "GENDER_CLINIC"
    HEMATOLOGY_ANDONCOLOGY = "HEMATOLOGY_ANDONCOLOGY"
    GENETICS = "GENETICS"
    GYNECOLOGY = "GYNECOLOGY"
    INFECTIOUS_DISEASE = "INFECTIOUS_DISEASE"
    NEUROLOGY = "NEUROLOGY"
    NUTRITION = "NUTRITION"
    OPHTHALMOLOGY = "OPHTHALMOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    OCCUPATIONAL_THERAPY = "OCCUPATIONAL_THERAPY"
    PULMONARY_FUNCTION_TESTING = "PULMONARY_FUNCTION_TESTING"
    PHYSICAL_THERAPY = "PHYSICAL_THERAPY"
    PULMONOLOGY_RESPIRATORY_AND_SLEEP_MEDICINE = "PULMONOLOGY_RESPIRATORY_AND_SLEEP_MEDICINE"
    SPEECH_THERAPY = "SPEECH_THERAPY"
    WOUND_CARE = "WOUND_CARE"


class TriageInput(BaseModel):
    """Input for triage agent."""
    client_id: str = Field(..., description="Client identifier for rule lookup")
    referral_text: List[str] = Field(..., description="List of page strings from referral document")
    client_rules: Optional[Dict[str, Any]] = Field(None, description="Client-specific rules (loaded externally)")


class TriageResult(BaseModel):
    """Result from triage agent - matches challenge specification."""
    specialty: str = Field(..., description="Detected medical specialty")
    urgency: int = Field(..., ge=0, le=1, description="Urgency status: 1 for urgent, 0 for not urgent") 
    evidence: str = Field(..., description="Supporting evidence/rationale from referral text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0")


class LLMSpecialtyResult(BaseModel):
    """Intermediate result from LLM specialty detection."""
    detected_specialty: Specialty = Field(..., description="Detected specialty")
    clinical_details: List[str] = Field(default_factory=list, description="Key clinical details extracted")
    reasoning: str = Field(..., description="LLM reasoning for specialty detection")
    confidence: float = Field(..., ge=0.0, le=1.0, description="LLM confidence in specialty detection")


class RuleMatchResult(BaseModel):
    """Result from rule matching engine."""
    matches_urgent_criteria: bool = Field(..., description="Whether clinical details match urgent criteria")
    matched_rules: List[str] = Field(default_factory=list, description="Specific rules that matched")
    evidence_snippets: List[str] = Field(default_factory=list, description="Evidence snippets supporting urgency")
    rule_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in rule matching")