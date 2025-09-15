"""
Async TriageAgent using pydantic-ai for specialty detection and rule-based urgency.
"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, Any, Optional
import logging

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic import BaseModel, Field

from .types import TriageInput, TriageResult, LLMSpecialtyResult, RuleMatchResult, Specialty
from .tools import TriageTools, get_client_rules, format_referral_data
from pydantic_ai import RunContext

logger = logging.getLogger(__name__)


class SpecialtyDetectionResult(BaseModel):
    """Pydantic model for LLM specialty detection response."""
    specialty: str = Field(..., description="Detected medical specialty (e.g., NEUROLOGY, CARDIOLOGY)")
    clinical_details: list[str] = Field(..., description="Key clinical details that led to specialty detection")
    reasoning: str = Field(..., description="Explanation of why this specialty was chosen")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in specialty detection")


class TriageAgent:
    """
    Independent async triage agent using pydantic-ai with tool calls.
    
    Flow:
    1. Tool call to pull correct rule mapping for client
    2. Tool call to format/transform referral text
    3. LLM call for specialty detection
    4. Apply rules to determine urgency
    """
    
    def __init__(
        self,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
        
    ):
        # Initialize tool tracking
        self._tools_called = []
        # Load .env file first
        load_dotenv()
        
        # Get API key first
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        
        # Auto-detect configuration based on API key validity
        if self.api_key and not self.api_key.startswith("dummy"):
            # Valid OpenAI API key detected - use OpenAI
            self.llm_provider = "openai"
            # Use GPT-4o-mini by default for OpenAI, ignore LLM_MODEL if it's a local model
            if llm_model:
                self.llm_model = llm_model
            elif os.getenv("LLM_MODEL") and not os.getenv("LLM_MODEL").startswith("qwen"):
                self.llm_model = os.getenv("LLM_MODEL")
            else:
                self.llm_model = "gpt-4o-mini"
            self.base_url = None  # Use official OpenAI API
            
            # Configure environment for OpenAI
            os.environ["OPENAI_API_KEY"] = self.api_key
            if "OPENAI_BASE_URL" in os.environ:
                del os.environ["OPENAI_BASE_URL"]
                
        elif os.getenv("LLM_BASE_URL") and self.api_key:
            # Local LLM configuration detected
            self.llm_provider = "local"
            self.llm_model = llm_model or os.getenv("LLM_MODEL", "qwen/qwen3-4b-thinking-2507")
            self.base_url = base_url or os.getenv("LLM_BASE_URL")
            
            # Configure environment for local LLM
            os.environ["OPENAI_API_KEY"] = self.api_key
            os.environ["OPENAI_BASE_URL"] = self.base_url
            
        else:
            # No valid configuration found
            raise ValueError(
                "No valid LLM configuration found. Either:\n"
                "1. Set OPENAI_API_KEY with a valid OpenAI API key, or\n"
                "2. Set both OPENAI_API_KEY and LLM_BASE_URL for local LLM"
            )
        
        # Create OpenAI model
        self.model = OpenAIChatModel(self.llm_model)
        
        # Create pydantic-ai agent with tools
        self.agent = Agent(
            self.model,
            system_prompt=self._get_system_prompt(),
            tools=[self._check_patient_history]
        )
        
        endpoint_info = self.base_url if self.base_url else "api.openai.com"
        logger.info(f"Initialized TriageAgent with {self.llm_provider}: {self.llm_model} at {endpoint_info}")
    
    async def analyze(self, input_data: TriageInput) -> TriageResult:
        """
        Main async entry point for pydantic-ai triage analysis with tool calls.
        
        Flow:
        1. Agent uses tool call to pull client rules
        2. Agent uses tool call to format referral data  
        3. Agent processes with LLM for specialty detection
        4. Apply urgency rules and return result
        """
        try:
            # Store input data for tool access
            self._current_input = input_data
            
            # Build user prompt with all the context
            user_prompt = self._build_comprehensive_prompt(input_data)
            
            # Run pydantic-ai agent
            agent_result = await self.agent.run(user_prompt)
            
            # Parse the LLM response to extract specialty info
            result_content = agent_result.output if hasattr(agent_result, 'output') else str(agent_result)
            logger.info(f"Raw agent result type: {type(result_content)}")
            logger.info(f"Raw agent result content: {result_content}")
            specialty_info = self._parse_llm_response(result_content)
            
            # Apply urgency rules
            urgency_result = await self._apply_urgency_rules(
                specialty_info,
                input_data.client_rules or {}
            )
            
            # Return final result
            return TriageResult(
                specialty=specialty_info['specialty'],
                urgency=1 if urgency_result else 0,
                evidence=specialty_info['reasoning'],
                confidence=specialty_info['confidence']
            )
            
        except Exception as e:
            logger.error(f"Triage analysis failed: {e}")
            # Fallback response
            return TriageResult(
                specialty="UNKNOWN",
                urgency=0,  # Default to non-urgent on error
                evidence=f"Analysis failed: {str(e)}",
                confidence=0.0
            )
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the pydantic-ai agent."""
        return """
You are a medical specialty detection AI that analyzes referral documents to determine the most appropriate medical specialty.

Your task:
1. Analyze the clinical content to detect the most appropriate medical specialty
2. If the referral is ambiguous or lacks sufficient detail, consider using check_patient_history to get additional context
3. Provide detailed reasoning and confidence score based on available information

When to use patient history tool:
- Ambiguous symptoms that could fit multiple specialties
- Limited information in referral
- Patient mentions previous episodes or treatments without details
- Need to understand medication history or previous diagnoses

Available specialties: NEUROLOGY, CARDIOLOGY, ORTHOPEDICS, ENDOCRINOLOGY, GASTROENTEROLOGY, GENERAL_SURGERY, GYNECOLOGY, OPHTHALMOLOGY, EAR_NOSE_AND_THROAT_OTOLARYNGOLOGY, INFECTIOUS_DISEASE, NUTRITION, OCCUPATIONAL_THERAPY, PHYSICAL_THERAPY, PULMONOLOGY_RESPIRATORY_AND_SLEEP_MEDICINE, SPEECH_THERAPY, WOUND_CARE, and others.
"""
    
    def _build_comprehensive_prompt(self, input_data: TriageInput) -> str:
        """Build comprehensive prompt with all context included."""
        # Get client rules manually
        client_rules = self._get_client_rules_sync(input_data.client_rules or {})
        
        # Format referral text
        formatted_text = "\n\n".join(f"Page {i+1}: {page}" for i, page in enumerate(input_data.referral_text))
        full_text = "\n\n".join(input_data.referral_text)
        
        # Extract keywords
        clinical_keywords = []
        keywords = ["seizure", "cardiac", "heart", "fracture", "bone", "diabetes", "hypertension", "fever", "pain"]
        for keyword in keywords:
            if keyword.lower() in full_text.lower():
                clinical_keywords.append(keyword)
        
        # Check if this case might benefit from patient history
        ambiguous_indicators = [
            'spacing out', 'episodes', 'intermittent', 'unclear', 'unknown history',
            'family history unknown', 'previous episodes', 'similar events', 'similar presentations',
            'loses time', 'blackouts', 'unclear etiology', 'atypical', 'varies',
            'multiple medical problems', 'further evaluation', 'history shows'
        ]
        
        is_potentially_ambiguous = any(indicator in full_text.lower() for indicator in ambiguous_indicators)
        
        history_suggestion = ""
        if is_potentially_ambiguous:
            history_suggestion = "\n\nNOTE: This case appears potentially ambiguous. Consider using the check_patient_history tool to get additional context about previous diagnoses, medications, or similar episodes before making your final determination."
        
        return f"""
You are a medical specialty detection AI. Analyze this referral and determine the most appropriate medical specialty.

Client: {input_data.client_id}
Available Client Rules: {client_rules.get('specialty_rules', {})}

Referral Text ({len(input_data.referral_text)} pages):
{formatted_text}

Detected Clinical Keywords: {', '.join(clinical_keywords) if clinical_keywords else 'None detected'}{history_suggestion}

Available specialties: NEUROLOGY, CARDIOLOGY, ORTHOPEDICS, ENDOCRINOLOGY, GASTROENTEROLOGY, GENERAL_SURGERY, GYNECOLOGY, OPHTHALMOLOGY, EAR_NOSE_AND_THROAT_OTOLARYNGOLOGY, INFECTIOUS_DISEASE, NUTRITION, OCCUPATIONAL_THERAPY, PHYSICAL_THERAPY, PULMONOLOGY_RESPIRATORY_AND_SLEEP_MEDICINE, SPEECH_THERAPY, WOUND_CARE

Please respond with:
1. SPECIALTY: [detected specialty]
2. REASONING: [CONCISE 1-2 sentence explanation focusing on key clinical indicators]
3. CONFIDENCE: [0.0-1.0]
4. CLINICAL_DETAILS: [key clinical findings]

IMPORTANT: Keep reasoning brief and focused - maximum 2 sentences highlighting the main clinical evidence.
"""
    
    def _get_client_rules_sync(self, client_rules: Dict[str, Any]) -> Dict[str, Any]:
        """Get client rules synchronously."""
        try:
            # Extract specialty urgency mapping rules
            rules = {}
            for rule in client_rules.get('rules', []):
                if rule.get('type') == 'specialty_urgent_mapping':
                    rules = rule.get('data', {})
                    break
            
            return {
                'specialty_rules': rules,
                'rule_count': len(rules)
            }
        except Exception as e:
            logger.error(f"Failed to get client rules: {e}")
            return {'error': str(e)}
    
    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response to extract specialty information."""
        try:
            # Extract specialty, reasoning, confidence from response
            specialty = "GENERAL_SURGERY"  # Default
            reasoning = response
            confidence = 0.5  # Default
            
            # Simple parsing - look for patterns in response (handle both plain and markdown format)
            specialty_patterns = ["**SPECIALTY:**", "**SPECIALTY**:", "SPECIALTY:"]
            specialty_pattern = None
            
            for pattern in specialty_patterns:
                if pattern in response:
                    specialty_pattern = pattern
                    break
                    
            if specialty_pattern:
                specialty_line = [line for line in response.split('\n') if specialty_pattern in line]
                if specialty_line:
                    # Extract just the specialty name (first word after pattern)
                    specialty_text = specialty_line[0].split(specialty_pattern)[1].strip()
                    specialty = specialty_text.split()[0]  # Get first word only
            
            # Also try to extract specialty from common patterns in reasoning
            else:
                # Look for common patterns like "Neurology is appropriate" or "necessitate cardiology"
                response_lower = response.lower()
                specialties_mentioned = {
                    'neurology': 'NEUROLOGY',
                    'cardiology': 'CARDIOLOGY', 
                    'orthopedics': 'ORTHOPEDICS',
                    'endocrinology': 'ENDOCRINOLOGY',
                    'gastroenterology': 'GASTROENTEROLOGY',
                    'surgery': 'GENERAL_SURGERY',
                    'gynecology': 'GYNECOLOGY',
                    'ophthalmology': 'OPHTHALMOLOGY',
                    'infectious': 'INFECTIOUS_DISEASE'
                }
                
                for term, spec in specialties_mentioned.items():
                    if term in response_lower:
                        specialty = spec
                        break
            
            # Handle confidence parsing for multiple formats
            confidence_patterns = ["**CONFIDENCE:**", "**CONFIDENCE**:", "CONFIDENCE:"]
            confidence_pattern = None
            
            for pattern in confidence_patterns:
                if pattern in response:
                    confidence_pattern = pattern
                    break
                    
            if confidence_pattern:
                conf_line = [line for line in response.split('\n') if confidence_pattern in line]
                if conf_line:
                    try:
                        confidence = float(conf_line[0].split(confidence_pattern)[1].strip())
                    except ValueError:
                        confidence = 0.5
            
            # Extract reasoning (handle multiple formats)
            reasoning_patterns = ["**REASONING:**", "**REASONING**:", "REASONING:"]
            reasoning_pattern = None
            
            for pattern in reasoning_patterns:
                if pattern in response:
                    reasoning_pattern = pattern
                    break
                    
            if reasoning_pattern:
                reasoning_lines = []
                found_reasoning = False
                for line in response.split('\n'):
                    if reasoning_pattern in line:
                        found_reasoning = True
                        reasoning_lines.append(line.split(reasoning_pattern)[1].strip())
                    elif found_reasoning and line.strip() and not any(keyword in line for keyword in ["SPECIALTY:", "CONFIDENCE:", "CLINICAL_DETAILS:", "**SPECIALTY:**", "**CONFIDENCE:**", "**CLINICAL_DETAILS:**"]):
                        reasoning_lines.append(line.strip())
                    elif found_reasoning and any(keyword in line for keyword in ["SPECIALTY:", "CONFIDENCE:", "CLINICAL_DETAILS:", "**SPECIALTY:**", "**CONFIDENCE:**", "**CLINICAL_DETAILS:**"]):
                        break
                
                if reasoning_lines:
                    reasoning = " ".join(reasoning_lines)
            
            return {
                'specialty': specialty,
                'reasoning': reasoning,
                'confidence': min(max(confidence, 0.0), 1.0),  # Clamp to 0-1
                'clinical_details': [reasoning]
            }
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return {
                'specialty': 'UNKNOWN',
                'reasoning': f"Response parsing failed: {str(e)}",
                'confidence': 0.0,
                'clinical_details': []
            }
    
    async def _apply_urgency_rules(
        self, 
        specialty_info: Dict[str, Any], 
        client_rules: Dict[str, Any]
    ) -> bool:
        """
        Apply client-specific rules to determine urgency based on detected specialty.
        """
        try:
            # Get specialty urgency rules from client config
            specialty_rules = {}
            for rule in client_rules.get('rules', []):
                if rule.get('type') == 'specialty_urgent_mapping':
                    specialty_rules = rule.get('data', {})
                    break
            
            # Check if detected specialty has urgent criteria
            specialty_key = specialty_info['specialty']
            urgency_criteria = specialty_rules.get(specialty_key, "No urgent diagnoses.")
            
            # Simple rule matching - if not "No urgent diagnoses", consider potentially urgent
            # In a real system, this would do more sophisticated matching against clinical details
            has_urgent_criteria = urgency_criteria != "No urgent diagnoses."
            
            # For NEUROLOGY with seizures, check if the evidence mentions seizures
            if specialty_key == "NEUROLOGY" and "seizure" in specialty_info['reasoning'].lower():
                has_urgent_criteria = True
            
            logger.info(
                f"Urgency evaluation for {specialty_key}: "
                f"criteria='{urgency_criteria}', urgent={has_urgent_criteria}"
            )
            
            return has_urgent_criteria
            
        except Exception as e:
            logger.error(f"Failed to apply urgency rules: {e}")
            return False  # Default to non-urgent on error
    
    async def _check_patient_history(self, patient_id: str = "DEMO_PATIENT") -> str:
        """Tool function to check patient history for additional context."""
        logger.info(f"*** TOOL CALLED: check_patient_history with patient_id={patient_id} ***")
        # Track tool usage
        self._tools_called.append(f"Patient history lookup (ID: {patient_id})")
        try:
            # Use stored input data
            input_data = self._current_input
            
            # Try to extract MRN from referral text if patient_id is default
            if patient_id == "DEMO_PATIENT" and input_data and input_data.referral_text:
                full_text = "\n".join(input_data.referral_text)
                # Look for MRN pattern
                import re
                mrn_match = re.search(r'MRN[:\s]*([A-Z0-9]+)', full_text, re.IGNORECASE)
                if mrn_match:
                    patient_id = mrn_match.group(1)
                    logger.info(f"Extracted patient_id from referral: {patient_id}")
            
            # Get client tools configuration  
            logger.info(f"Getting client tools config from input_data: {type(input_data)}")
            client_tools_config = input_data.client_rules.get('tools', []) if input_data else []
            logger.info(f"Client tools config: {client_tools_config}")
            enabled_tools = [tool for tool in client_tools_config if tool.get('name') == 'check_patient_history' and tool.get('enabled', False)]
            logger.info(f"Enabled tools: {enabled_tools}")
            
            if not enabled_tools:
                return "Patient history tool not available for this client."
            
            # Initialize tools system
            tools = TriageTools(client_tools_config)
            
            # Call the patient history tool
            result = await tools.execute_tool("check_patient_history", patient_id=patient_id)
            
            if result.success:
                history_data = result.data
                
                # Format the response for the LLM
                formatted_response = f"""Patient History Retrieved:
                
Patient ID: {history_data.get('patient_id', 'Unknown')}
Last Visit: {history_data.get('last_visit_date', 'Unknown')}
                
Recent Medical History:
{chr(10).join(f"- {entry.get('date', 'Unknown')}: {entry.get('diagnosis', 'Unknown')} ({entry.get('visit_type', 'Unknown')})" for entry in history_data.get('history_entries', []))}
                
Current Medications:
{chr(10).join(f"- {med}" for med in history_data.get('medications', []))}
                
Known Allergies:
{chr(10).join(f"- {allergy}" for allergy in history_data.get('allergies', []))}
                
This additional context should be considered when determining specialty and urgency."""
                
                logger.info(f"Patient history tool executed successfully for {patient_id}")
                logger.info(f"Tool response: {formatted_response[:500]}...")  # First 500 chars
                return formatted_response
            else:
                logger.warning(f"Patient history tool failed: {result.error}")
                return f"Unable to retrieve patient history: {result.error}"
                
        except Exception as e:
            logger.error(f"Patient history tool error: {e}")
            import traceback
            logger.error(f"Patient history tool traceback: {traceback.format_exc()}")
            return f"Error accessing patient history: {str(e)}"
    
    def run_sync(self, input_data: TriageInput) -> TriageResult:
        """Synchronous wrapper for the async analyze method."""
        return asyncio.run(self.analyze(input_data))
    
    @property
    def tools_called(self) -> list[str]:
        """Get list of tools that were called during analysis."""
        return self._tools_called.copy()
