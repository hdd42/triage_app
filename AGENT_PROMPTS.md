# Agent and Prompt Design

Last updated: 2025-09-15

This document describes the triage agent’s responsibilities, decision flow, and prompt strategy at a high level. It is intended to be cloud- and framework-agnostic.

## Goals
- Accurately infer medical specialty from referral text
- Determine urgency using deterministic client rules (where possible)
- Produce auditable, structured outputs with evidence
- Remain portable across clouds and runtimes

## Responsibilities and Flow
1. Input normalization
   - Accepts: client_id, referral_text (array of strings), optional metadata
   - Normalizes whitespace, language hints, and removes presentation artifacts
2. Specialty detection (LLM)
   - Use the LLM to classify the most likely medical specialty based on clinical cues in the referral text
   - Constrain output to a known set of specialties whenever possible
3. Urgency assessment (rules-first)
   - Apply client rules of type "specialty_urgent_mapping" to the detected specialty to assess urgency and rationale
   - Keep the mapping human-readable and explainable for auditability
4. Output assembly
   - Return a structured object with: specialty, urgency (0/1), evidence/explanation, confidence, and metadata (prompt_version, model_id)

## Rule Types
- Active today
  - specialty_urgent_mapping: maps specialty to urgency criteria (e.g., Chest pain -> urgent cardiology)
- Planned/Extensible
  - triage_rules: richer clinical predicates (age, vitals, red flags) with deterministic evaluation
  - custom: hooks to domain-specific decision logic or third-party services

Note: Today’s production logic only consumes specialty_urgent_mapping. The other types are present in client config for future growth without breaking the model.

## Prompt Strategy (High Level)
- Strict, role-based system prompt to constrain scope
- Minimal, explicit task instructions with examples
- Ask for structured JSON output only (no extra prose)
- Encourage citing evidence extracted directly from the referral text
- Avoid speculative diagnoses; prefer "UNKNOWN" or low confidence when unclear

### Example: System Prompt (sketch)
```text path=null start=null
You are a clinical triage assistant. Your task is to:
1) Identify the most relevant medical specialty for the referral.
2) Provide concise evidence from the referral text supporting your choice.
3) Do not speculate beyond the provided text. If unclear, state UNKNOWN and lower confidence.
Output only JSON following the requested schema. No additional commentary.
```

### Example: Instruction Template (sketch)
```text path=null start=null
Referral (lines):
{{joined_referral_lines}}

Allowed specialties: {{allowed_specialties_csv}}

Respond using the schema:
{
  "specialty": "<one of allowed specialties or UNKNOWN>",
  "evidence": "<short quote/rationale from the referral>",
  "confidence": <0.0-1.0>
}
```

### Example: Expected Model Output
```json path=null start=null
{
  "specialty": "CARDIOLOGY",
  "evidence": "Reports exertional chest pain with shortness of breath",
  "confidence": 0.88
}
```

## From LLM Output to Final Triage Result
- The agent converts the model’s specialty output into a final triage decision:
  - specialty: directly from the LLM, validated against allowed set
  - urgency: computed via specialty_urgent_mapping rules for the current client
  - evidence: taken from model output and/or rules rationale
  - confidence: model’s reported confidence, optionally calibrated

## Safety and Auditability
- Log prompt version, model ID, and rule version used
- Redact or minimize PHI in logs; store only what’s necessary for audit
- Provide deterministic rule application separate from the LLM for explainability
- Ensure temperature and sampling are configured for stability (e.g., low temperature)

## Extensibility Notes
- Specialty taxonomy: Maintain a canonical list and client-specific aliases
- triage_rules: Introduce a small rule DSL or JSON schema capturing red flags, age bands, duration, etc.
- custom: Adapter interface for custom decision modules (e.g., stroke pathways, fall risk)
- Tooling: Add optional tools for data enrichment (e.g., patient history lookup) with strict timeouts

### Hypothetical Agent Initialization (illustrative only)
```python path=null start=null
from typing import List

class TriageInput(BaseModel):
    client_id: str
    referral_text: List[str]

# Initialize agent with prompt templates and allowed specialties
agent = TriageAgent(
    system_prompt=SYSTEM_PROMPT,
    instruction_template=INSTRUCTION_TEMPLATE,
    allowed_specialties=CANONICAL_SPECIALTIES,
)

result = agent.run_sync(TriageInput(
    client_id="hospital_a",
    referral_text=["45M with exertional chest pain and dyspnea"]
))

# result.specialty -> "CARDIOLOGY"
# result.urgency   -> 1 (based on specialty_urgent_mapping)
# result.evidence  -> short rationale string
```

## Versioning and Observability
- Include prompt_version, rules_version, and model_id in the agent’s output metadata
- Emit OpenTelemetry spans around LLM calls and rule evaluation
- Record counters for specialties detected and urgency distributions to monitor drift

## What Not to Log
- Full, raw referral text containing PHI (unless justified and protected)
- Secrets or API keys
- Full chain-of-thought; retain only the final structured outputs and minimal evidence quotes

## Summary
- Rules-first urgency with LLM specialty classification
- Portable prompts and interfaces for multi-cloud and on-prem deployments
- Clear path to richer rules (triage_rules) and custom clinical logic
