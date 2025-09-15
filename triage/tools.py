"""
Dynamic tool calling system for triage agent.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime, timedelta
import json

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolResult(BaseModel):
    """Result from tool execution."""
    tool_name: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None


class InsuranceValidationResult(BaseModel):
    """Result from insurance validation tool."""
    patient_id: str
    insurance_id: str
    is_valid: bool
    coverage_type: str
    copay_amount: float
    notes: Optional[str] = None


class PatientHistoryResult(BaseModel):
    """Result from patient history tool."""
    patient_id: str
    history_entries: List[Dict[str, Any]] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    last_visit_date: Optional[str] = None


class TriageTools:
    """Dynamic tool execution system for triage agent."""
    
    def __init__(self, client_tools: List[Dict[str, Any]]):
        self.client_tools = {tool['name']: tool for tool in client_tools if tool.get('enabled', True)}
        logger.info(f"Initialized TriageTools with {len(self.client_tools)} enabled tools")
    
    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool dynamically based on client configuration."""
        start_time = datetime.now()
        
        try:
            if tool_name not in self.client_tools:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Tool '{tool_name}' not available or disabled for this client"
                )
            
            tool_config = self.client_tools[tool_name]
            
            # Route to appropriate tool implementation
            if tool_name == "validate_insurance":
                result_data = await self._validate_insurance(tool_config, **kwargs)
            elif tool_name == "check_patient_history":
                result_data = await self._check_patient_history(tool_config, **kwargs)
            else:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Unknown tool implementation: {tool_name}"
                )
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return ToolResult(
                tool_name=tool_name,
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def _validate_insurance(self, tool_config: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Placeholder insurance validation tool."""
        # Simulate API call delay
        await asyncio.sleep(0.1)
        
        patient_id = kwargs.get('patient_id', 'UNKNOWN')
        insurance_id = kwargs.get('insurance_id', 'INS-12345')
        
        # Placeholder logic - in reality this would call insurance API
        validation_result = InsuranceValidationResult(
            patient_id=patient_id,
            insurance_id=insurance_id,
            is_valid=True,  # Placeholder: always valid
            coverage_type="PPO",
            copay_amount=25.00,
            notes=f"Validated via {tool_config.get('description', 'insurance system')}"
        )
        
        return validation_result.model_dump()
    
    async def _check_patient_history(self, tool_config: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Placeholder patient history lookup tool."""
        # Simulate EHR query delay
        await asyncio.sleep(0.2)
        
        patient_id = kwargs.get('patient_id', 'UNKNOWN')
        max_years = tool_config.get('config', {}).get('max_history_years', 5)
        
        # Placeholder patient history data
        history_result = PatientHistoryResult(
            patient_id=patient_id,
            history_entries=[
                {
                    "date": (datetime.now() - timedelta(days=90)).isoformat()[:10],
                    "visit_type": "Annual Physical",
                    "diagnosis": "Routine checkup",
                    "provider": "Dr. Smith"
                },
                {
                    "date": (datetime.now() - timedelta(days=365)).isoformat()[:10],
                    "visit_type": "Urgent Care",
                    "diagnosis": "Upper respiratory infection",
                    "provider": "Dr. Johnson"
                }
            ],
            medications=["Lisinopril 10mg daily", "Metformin 500mg twice daily"],
            allergies=["Penicillin", "Shellfish"],
            last_visit_date=(datetime.now() - timedelta(days=90)).isoformat()[:10]
        )
        
        return history_result.model_dump()
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool names for this client."""
        return list(self.client_tools.keys())
    
    def get_tool_config(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific tool."""
        return self.client_tools.get(tool_name)


# Tool call formatting utilities for pydantic-ai
async def get_client_rules(client_id: str, client_config: Dict[str, Any]) -> Dict[str, Any]:
    """Tool call to pull correct rule mapping for client."""
    try:
        # Extract specialty urgency mapping rules
        rules = {}
        for rule in client_config.get('rules', []):
            if rule.get('type') == 'specialty_urgent_mapping':
                rules = rule.get('data', {})
                break
        
        return {
            'client_id': client_id,
            'specialty_rules': rules,
            'rule_count': len(rules)
        }
    except Exception as e:
        logger.error(f"Failed to get client rules: {e}")
        return {'error': str(e)}


async def format_referral_data(referral_text: List[str]) -> Dict[str, Any]:
    """Tool call to format/transform referral text into structured data."""
    try:
        # Join all pages
        full_text = "\n\n".join(referral_text)
        
        # Basic text analysis (placeholder for more sophisticated parsing)
        word_count = len(full_text.split())
        char_count = len(full_text)
        
        # Extract potential clinical keywords (placeholder)
        clinical_keywords = []
        keywords = ["seizure", "cardiac", "fracture", "diabetes", "hypertension", "fever", "pain"]
        for keyword in keywords:
            if keyword.lower() in full_text.lower():
                clinical_keywords.append(keyword)
        
        return {
            'formatted_text': full_text,
            'word_count': word_count,
            'char_count': char_count,
            'clinical_keywords': clinical_keywords,
            'page_count': len(referral_text)
        }
    except Exception as e:
        logger.error(f"Failed to format referral data: {e}")
        return {'error': str(e)}