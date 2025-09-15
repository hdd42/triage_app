# Agent Triage System Analysis

## Overview

This medical triage system uses **pydantic-ai** with OpenAI's GPT models to analyze medical referrals and determine:
1. The appropriate medical specialty
2. Urgency level (0 = not urgent, 1 = urgent)
3. Clinical evidence/reasoning
4. Confidence score (0.0-1.0)

## Architecture Flow

```
1. FastAPI receives triage request (/triage endpoint)
   ↓
2. TriageAgent initialized (with OpenAI or local LLM)
   ↓
3. Agent builds comprehensive prompt with client rules & referral text
   ↓
4. Pydantic-AI agent runs with system prompt + user prompt
   ↓
5. LLM analyzes and returns specialty detection
   ↓
6. Agent applies client-specific urgency rules
   ↓
7. Returns structured TriageResult
```

## Key Components

### 1. TriageAgent (`triage/agent.py`)
- Main orchestrator for the triage analysis
- Supports both OpenAI and local LLM models
- Uses pydantic-ai for structured LLM interactions
- Has tool capabilities (e.g., check_patient_history)

### 2. LLM Configuration
- **Primary**: OpenAI GPT-4o-mini (default)
- **Fallback**: Local LLM via OpenAI-compatible API
- Auto-detects configuration based on API key validity

### 3. Client-Specific Rules
Each client (clinic) has:
- Specialty urgency mappings
- Available tools configuration
- Custom prompts and rules

## Prompt Structure Analysis

### System Prompt (Lines 158-175 in agent.py)

```python
"""
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
```

### User Prompt Structure (Lines 207-227 in agent.py)

The user prompt is dynamically built with:

1. **Context Information**:
   - Client ID
   - Client-specific rules
   - Number of referral pages

2. **Referral Text**:
   - Formatted with page numbers
   - Full concatenated text

3. **Clinical Keywords Detection**:
   - Automatically extracted keywords (seizure, cardiac, heart, fracture, etc.)

4. **Ambiguity Detection**:
   - Checks for ambiguous indicators
   - Suggests using patient history tool when needed

5. **Response Format Instructions**:
   ```
   Please respond with:
   1. SPECIALTY: [detected specialty]
   2. REASONING: [CONCISE 1-2 sentence explanation focusing on key clinical indicators]
   3. CONFIDENCE: [0.0-1.0]
   4. CLINICAL_DETAILS: [key clinical findings]
   
   IMPORTANT: Keep reasoning brief and focused - maximum 2 sentences highlighting the main clinical evidence.
   ```

## Final Prompt Sent to LLM

The complete prompt sent to the LLM consists of:

### System Message:
```
You are a medical specialty detection AI that analyzes referral documents...
[Full system prompt as above]
```

### User Message Example:
```
You are a medical specialty detection AI. Analyze this referral and determine the most appropriate medical specialty.

Client: acme_childrens
Available Client Rules: {'NEUROLOGY': 'New onset seizure or seizure like events', ...}

Referral Text (3 pages):
Page 1: Patient John Doe, 5 years old, presents with new onset seizures.
Page 2: Episodes started 2 days ago, lasting 1-2 minutes each.
Page 3: Parents report 3 episodes in past 24 hours. No fever, no trauma history.

Detected Clinical Keywords: seizure

Available specialties: NEUROLOGY, CARDIOLOGY, ORTHOPEDICS, [etc...]

Please respond with:
1. SPECIALTY: [detected specialty]
2. REASONING: [CONCISE 1-2 sentence explanation]
3. CONFIDENCE: [0.0-1.0]
4. CLINICAL_DETAILS: [key clinical findings]

IMPORTANT: Keep reasoning brief and focused - maximum 2 sentences highlighting the main clinical evidence.
```

## Tool Capabilities

### Patient History Tool (`_check_patient_history`)
- Can be invoked by the LLM when ambiguous cases are detected
- Retrieves patient's medical history, medications, allergies
- Currently uses placeholder data but structure is ready for real EHR integration

## Response Processing

### LLM Response Parsing (Lines 247-347 in agent.py)
The agent parses the LLM response to extract:
1. **Specialty**: Looks for "SPECIALTY:" pattern or specialty mentions in text
2. **Confidence**: Extracts from "CONFIDENCE:" pattern
3. **Reasoning**: Extracts from "REASONING:" pattern
4. **Clinical Details**: Collected from the reasoning section

### Urgency Rule Application (Lines 349-386 in agent.py)
After specialty detection:
1. Retrieves client-specific urgency rules for the detected specialty
2. Applies rule matching based on clinical evidence
3. Special handling for specific conditions (e.g., NEUROLOGY + seizures = urgent)

## Key Features

1. **Multi-format Support**: Handles both plain text and markdown-formatted LLM responses
2. **Fallback Defaults**: Has sensible defaults if parsing fails
3. **Error Resilience**: Returns structured error responses on failure
4. **Timing Metrics**: Tracks performance at each stage
5. **Encryption**: Sensitive data is encrypted before database storage
6. **Logging**: Comprehensive logging for debugging and audit

## Prompt Modifications You're Working On

Based on the code, the prompts being modified are likely:

1. **System Prompt** (`_get_system_prompt` method):
   - Instructions for medical specialty detection
   - Tool usage guidelines
   - Available specialties list

2. **User Prompt** (`_build_comprehensive_prompt` method):
   - Client context inclusion
   - Referral text formatting
   - Response format specifications
   - Keyword detection and ambiguity handling

3. **Response Format Requirements**:
   - Emphasis on concise reasoning (max 2 sentences)
   - Structured output format
   - Confidence scoring guidelines

## Configuration Points

### Environment Variables:
- `OPENAI_API_KEY`: API key for OpenAI or local LLM
- `LLM_MODEL`: Model selection (default: gpt-4o-mini)
- `LLM_BASE_URL`: For local LLM endpoints
- `HEALTH_DATA_ENCRYPTION_KEY`: For encrypting sensitive data

### Client Configuration (`client_config.json`):
- Specialty urgency mappings per client
- Available tools per client
- Custom prompts and rules

## Testing & Development Notes

1. **Test Mode**: System has a test mode that returns mock responses when no OpenAI key is configured
2. **Admin Interface**: Available at `/ui/admin` for monitoring
3. **SQLAdmin**: Database admin at `/sqladmin`
4. **Encryption Test**: `/admin/encryption/test` endpoint

## Recommendations for Prompt Optimization

1. **Specificity**: The current prompts are quite detailed but could benefit from:
   - More examples of edge cases
   - Clearer disambiguation rules between similar specialties
   - Guidelines for confidence scoring thresholds

2. **Brevity**: The "2 sentence maximum" constraint for reasoning is good for efficiency

3. **Structure**: The structured response format (SPECIALTY, REASONING, etc.) helps with reliable parsing

4. **Context**: Good use of client-specific rules and keyword detection

5. **Tool Integration**: The patient history tool prompt integration is well-designed for ambiguous cases