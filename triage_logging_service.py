"""
Dedicated logging service for triage analysis.
"""

from __future__ import annotations

import uuid
import time
from typing import Optional, Dict, Any, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from triage_models import TriageLog
from db import get_session
from encryption import encrypt_health_data, decrypt_health_data_json, decrypt_health_data

logger = logging.getLogger(__name__)


class TriageLogger:
    """Service for logging detailed triage analysis data."""
    
    def __init__(self):
        pass
    
    async def log_triage_analysis(
        self,
        # Request metadata
        request_id: Optional[str] = None,
        client_id: str = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        
        # Input data
        referral_text: List[str] = None,
        
        # Timing data
        agent_init_time_ms: Optional[float] = None,
        llm_call_time_ms: Optional[float] = None,
        rule_processing_time_ms: Optional[float] = None,
        total_analysis_time_ms: Optional[float] = None,
        
        # Tool usage
        tools_used: Optional[List[str]] = None,
        patient_history_used: Optional[bool] = None,
        insurance_validated: Optional[bool] = None,
        
        # LLM interaction
        llm_prompt: Optional[str] = None,
        llm_response: str = None,
        llm_model: Optional[str] = None,
        
        # Results
        detected_specialty: str = None,
        urgency_result: int = None,
        confidence_score: float = None,
        evidence: str = None,
        
        # Rule matching
        matched_rules: Optional[Dict[str, Any]] = None,
        rule_match_reasoning: Optional[str] = None,
        
        # Quality metrics
        ambiguity_score: Optional[float] = None,
        complexity_score: Optional[float] = None,
        
        # Status
        success: bool = True,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        
        # Human validation
        human_validated: bool = False,
        human_specialty: Optional[str] = None,
        human_urgency: Optional[int] = None,
        human_notes: Optional[str] = None,
        
    ) -> Optional[int]:
        """
        Log a complete triage analysis to the database.
        
        Returns:
            The ID of the created log entry, or None if logging failed
        """
        try:
            async for session in get_session():
                # Calculate additional metrics
                referral_pages = len(referral_text) if referral_text else 0
                referral_word_count = sum(len(page.split()) for page in referral_text) if referral_text else 0
                tool_call_count = len(tools_used) if tools_used else 0
                
                # Generate request ID if not provided
                if not request_id:
                    request_id = str(uuid.uuid4())[:8]
                
                # Encrypt sensitive data
                referral_text_encrypted = encrypt_health_data(referral_text) if referral_text else None
                llm_prompt_encrypted = encrypt_health_data(llm_prompt) if llm_prompt else None
                llm_response_encrypted = encrypt_health_data(llm_response) if llm_response else None
                evidence_encrypted = encrypt_health_data(evidence) if evidence else None
                
                triage_log = TriageLog(
                    # Request metadata
                    request_id=request_id,
                    client_id=client_id,
                    client_ip=client_ip,
                    user_agent=user_agent[:500] if user_agent else None,
                    
                    # Input data (encrypted)
                    referral_text_encrypted=referral_text_encrypted,
                    referral_pages=referral_pages,
                    referral_word_count=referral_word_count,
                    
                    # Timing
                    agent_init_time_ms=agent_init_time_ms,
                    llm_call_time_ms=llm_call_time_ms,
                    rule_processing_time_ms=rule_processing_time_ms,
                    total_analysis_time_ms=total_analysis_time_ms,
                    
                    # Tool usage
                    tools_used=tools_used,
                    tool_call_count=tool_call_count,
                    patient_history_used=patient_history_used,
                    insurance_validated=insurance_validated,
                    
                    # LLM interaction (encrypted)
                    llm_prompt_encrypted=llm_prompt_encrypted,
                    llm_response_encrypted=llm_response_encrypted,
                    llm_model=llm_model,
                    
                    # Results
                    detected_specialty=detected_specialty,
                    urgency_result=urgency_result,
                    confidence_score=confidence_score,
                    evidence_encrypted=evidence_encrypted,
                    
                    # Rule matching
                    matched_rules=matched_rules,
                    rule_match_reasoning=rule_match_reasoning,
                    
                    # Quality metrics
                    ambiguity_score=ambiguity_score,
                    complexity_score=complexity_score,
                    
                    # Status
                    success=success,
                    error_type=error_type,
                    error_message=error_message[:1000] if error_message else None,
                    
                    # Human validation
                    human_validated=human_validated,
                    human_specialty=human_specialty,
                    human_urgency=human_urgency,
                    human_notes=human_notes,
                )
                
                session.add(triage_log)
                await session.commit()
                await session.refresh(triage_log)
                
                logger.info(f"Logged triage analysis: ID={triage_log.id}, specialty={detected_specialty}, urgency={urgency_result}")
                return triage_log.id
                
        except Exception as e:
            logger.error(f"Failed to log triage analysis: {e}")
            return None
    
    async def get_decrypted_triage_log(self, log_id: int) -> Optional[dict]:
        """
        Get a triage log with decrypted sensitive data.
        
        Args:
            log_id: ID of the triage log
            
        Returns:
            Dictionary with decrypted data, or None if not found
        """
        try:
            from sqlalchemy import select
            
            async for session in get_session():
                result = await session.execute(
                    select(TriageLog).where(TriageLog.id == log_id)
                )
                triage_log = result.scalar_one_or_none()
                
                if not triage_log:
                    return None
                
                # Decrypt sensitive data
                decrypted_data = {
                    'id': triage_log.id,
                    'request_id': triage_log.request_id,
                    'client_id': triage_log.client_id,
                    'client_ip': triage_log.client_ip,
                    'created_at': triage_log.created_at.isoformat(),
                    
                    # Decrypt sensitive fields
                    'referral_text': decrypt_health_data_json(triage_log.referral_text_encrypted) if triage_log.referral_text_encrypted else None,
                    'llm_prompt': decrypt_health_data(triage_log.llm_prompt_encrypted) if triage_log.llm_prompt_encrypted else None,
                    'llm_response': decrypt_health_data(triage_log.llm_response_encrypted) if triage_log.llm_response_encrypted else None,
                    'evidence': decrypt_health_data(triage_log.evidence_encrypted) if triage_log.evidence_encrypted else None,
                    
                    # Non-sensitive fields
                    'referral_pages': triage_log.referral_pages,
                    'detected_specialty': triage_log.detected_specialty,
                    'urgency_result': triage_log.urgency_result,
                    'confidence_score': triage_log.confidence_score,
                    'llm_model': triage_log.llm_model,
                    'success': triage_log.success,
                    'total_analysis_time_ms': triage_log.total_analysis_time_ms,
                }
                
                return decrypted_data
                
        except Exception as e:
            logger.error(f"Failed to get decrypted triage log: {e}")
            return None
    
    async def get_triage_stats(
        self, 
        hours: int = 24,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get triage analysis statistics.
        
        Args:
            hours: Number of hours to look back
            client_id: Optional client filter
            
        Returns:
            Dictionary with triage statistics
        """
        try:
            from sqlalchemy import select, func
            from datetime import datetime, timedelta
            
            async for session in get_session():
                # Calculate time threshold
                since = datetime.utcnow() - timedelta(hours=hours)
                
                # Base query
                base_query = select(TriageLog).where(TriageLog.created_at >= since)
                if client_id:
                    base_query = base_query.where(TriageLog.client_id == client_id)
                
                # Total analyses
                total_query = select(func.count(TriageLog.id)).where(TriageLog.created_at >= since)
                if client_id:
                    total_query = total_query.where(TriageLog.client_id == client_id)
                    
                total_result = await session.execute(total_query)
                total_count = total_result.scalar()
                
                # Success rate
                success_query = select(func.count(TriageLog.id)).where(
                    TriageLog.created_at >= since,
                    TriageLog.success == True
                )
                if client_id:
                    success_query = success_query.where(TriageLog.client_id == client_id)
                    
                success_result = await session.execute(success_query)
                success_count = success_result.scalar()
                
                # Specialty distribution
                specialty_query = select(
                    TriageLog.detected_specialty,
                    func.count(TriageLog.id)
                ).where(TriageLog.created_at >= since).group_by(TriageLog.detected_specialty)
                if client_id:
                    specialty_query = specialty_query.where(TriageLog.client_id == client_id)
                    
                specialty_result = await session.execute(specialty_query)
                specialty_distribution = dict(specialty_result.fetchall())
                
                # Urgency distribution
                urgency_query = select(
                    TriageLog.urgency_result,
                    func.count(TriageLog.id)
                ).where(TriageLog.created_at >= since).group_by(TriageLog.urgency_result)
                if client_id:
                    urgency_query = urgency_query.where(TriageLog.client_id == client_id)
                    
                urgency_result = await session.execute(urgency_query)
                urgency_distribution = dict(urgency_result.fetchall())
                
                # Average times
                avg_times_query = select(
                    func.avg(TriageLog.total_analysis_time_ms),
                    func.avg(TriageLog.llm_call_time_ms),
                    func.avg(TriageLog.confidence_score)
                ).where(TriageLog.created_at >= since, TriageLog.success == True)
                if client_id:
                    avg_times_query = avg_times_query.where(TriageLog.client_id == client_id)
                    
                avg_result = await session.execute(avg_times_query)
                avg_analysis_time, avg_llm_time, avg_confidence = avg_result.first()
                
                return {
                    'time_period_hours': hours,
                    'client_id': client_id,
                    'total_analyses': total_count or 0,
                    'successful_analyses': success_count or 0,
                    'success_rate': (success_count / total_count * 100) if total_count > 0 else 0,
                    'average_analysis_time_ms': round(avg_analysis_time, 2) if avg_analysis_time else 0,
                    'average_llm_time_ms': round(avg_llm_time, 2) if avg_llm_time else 0,
                    'average_confidence': round(avg_confidence, 3) if avg_confidence else 0,
                    'specialty_distribution': specialty_distribution,
                    'urgency_distribution': urgency_distribution,
                    'urgent_cases': urgency_distribution.get(1, 0),
                    'non_urgent_cases': urgency_distribution.get(0, 0),
                }
                
        except Exception as e:
            logger.error(f"Failed to get triage stats: {e}")
            return {
                'error': 'Failed to retrieve triage statistics',
                'time_period_hours': hours,
                'client_id': client_id,
            }


# Global instance
triage_logger = TriageLogger()