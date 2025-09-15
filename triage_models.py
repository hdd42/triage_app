"""
Dedicated models for triage logging and analytics.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, JSON, func
from db import Base


class TriageLog(Base):
    """Dedicated table for storing detailed triage analysis logs."""
    __tablename__ = "triage_logs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Request metadata
    request_id = Column(String(100), nullable=True, index=True)  # For correlating with RequestLog
    client_id = Column(String(100), nullable=False, index=True)
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    # Input data - store the actual referral content (ENCRYPTED)
    referral_text_encrypted = Column(Text, nullable=False)  # Encrypted JSON array
    referral_pages = Column(Integer, nullable=False, default=0)
    referral_word_count = Column(Integer, nullable=True)
    
    # LLM Analysis timing
    agent_init_time_ms = Column(Float, nullable=True)
    llm_call_time_ms = Column(Float, nullable=True)
    rule_processing_time_ms = Column(Float, nullable=True)
    total_analysis_time_ms = Column(Float, nullable=True)
    
    # Tool usage tracking
    tools_used = Column(JSON, nullable=True)  # List of tools called during analysis
    tool_call_count = Column(Integer, nullable=True, default=0)
    patient_history_used = Column(Boolean, nullable=True, default=False)
    insurance_validated = Column(Boolean, nullable=True, default=False)
    
    # LLM Request/Response (ENCRYPTED for sensitive data)
    llm_prompt_encrypted = Column(Text, nullable=True)  # Encrypted prompt sent to LLM
    llm_response_encrypted = Column(Text, nullable=False)  # Encrypted raw LLM response
    llm_model = Column(String(100), nullable=True)  # Model used (not encrypted)
    
    # Analysis results
    detected_specialty = Column(String(100), nullable=False, index=True)  # Not encrypted (for queries)
    urgency_result = Column(Integer, nullable=False, index=True)  # 0 or 1 (not encrypted)
    confidence_score = Column(Float, nullable=False)  # Not encrypted (for analytics)
    evidence_encrypted = Column(Text, nullable=False)  # Encrypted reasoning/evidence
    
    # Client rule matching
    matched_rules = Column(JSON, nullable=True)  # Which client rules were triggered
    rule_match_reasoning = Column(Text, nullable=True)
    
    # Quality metrics
    ambiguity_score = Column(Float, nullable=True)  # How ambiguous was the case (0.0-1.0)
    complexity_score = Column(Float, nullable=True)  # Clinical complexity (0.0-1.0)
    
    # Status and error tracking
    success = Column(Boolean, nullable=False, default=True, index=True)
    error_type = Column(String(50), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    
    # Optional: Human validation (for ML training)
    human_validated = Column(Boolean, nullable=True, default=False)
    human_specialty = Column(String(100), nullable=True)  # Human-validated specialty
    human_urgency = Column(Integer, nullable=True)  # Human-validated urgency
    human_notes = Column(Text, nullable=True)  # Human reviewer notes