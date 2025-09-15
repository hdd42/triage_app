# LLM-Powered Medical Referral Triage System

<!-- We'll build this README step by step -->

## Overview

A **production-ready LLM-powered medical referral triage system** built with an **agentic architecture** that intelligently determines medical specialty and urgency from unstructured referral documents.

### 🎯 **Why Agentic Architecture?**

The core triage logic is built as an **independent AI agent** that:
- **Framework Agnostic**: Can run on FastAPI, Flask, AWS Lambda, or any Python environment
- **Tool-Enabled**: Uses dynamic tool calling for patient history lookup, insurance validation, etc.
- **Rule-Based Intelligence**: Applies client-specific medical urgency rules after LLM specialty detection
- **Composable**: Easy to integrate into existing healthcare systems

### 🚀 **Production Flexibility** 

The agent (`triage/`) operates independently of the web interface:
```python
# Use anywhere - FastAPI, Lambda, microservices, etc.
from triage import TriageAgent, TriageInput

agent = TriageAgent()
result = agent.run_sync(TriageInput(
    client_id="hospital_a",
    referral_text=["Patient presents with chest pain..."]
))
print(f"Specialty: {result.specialty}, Urgent: {result.urgency}")
```

## Features

### 🤖 **AI Agent Core**
- **LLM Specialty Detection**: Analyzes unstructured referral text to identify medical specialty
- **Rule-Based Urgency**: Applies client-specific clinical rules to determine urgency (0=routine, 1=urgent)
- **Dynamic Tool Calling**: Patient history lookup, insurance validation, clinical data enrichment
- **Multi-LLM Support**: Works with OpenAI GPT models or local LLMs (via OpenAI-compatible APIs)

### 🏥 **Multi-Client Architecture**  
- **Client Isolation**: Each healthcare organization has separate rules and configurations
- **Versioned Configurations**: Track changes to rules, prompts, and tools over time
- **Specialty Mapping**: Customizable urgency criteria per medical specialty per client

### 📊 **Production Web Interface**
- **Triage Testing UI**: Interactive form with pre-loaded test cases
- **Client Management**: Full CRUD operations for client configurations, rules, and tools
- **Admin Dashboard**: System monitoring, logs, and configuration management
- **API Documentation**: Built-in Swagger UI for integration

### 🔒 **Security & Observability**
- **PHI Encryption**: Sensitive medical data encrypted at rest in database
- **Request Logging**: Detailed audit trails with performance metrics
- **Database Admin**: Direct table access via SQLAdmin interface
- **Extensible**: Easy to add new tools, rules, and integrations

### LLM Compatibility and Models Used

- OpenAI-compatible interface: The agent communicates via an OpenAI-compatible API, so you can plug in local or hosted models interchangeably.
- Models used: Developed and tested locally with Qwen 3.1; published using GPT-4o-mini.
- Cost and limits: Free tiers (e.g., GPT-4o-mini) have rate/usage limits. Requiring candidates to use paid LLMs for a take-home can be costly and unfair; this project uses free-tier defaults for review convenience.
- Configuration: Swap providers using environment variables (e.g., LLM_BASE_URL, OPENAI_API_KEY) without code changes.

## Architecture

### 🏗️ **System Design**

```
┌────────────────────────┐
│    Web Interface (FastAPI)    │
│  📊 Triage UI 🏥 Admin UI     │
├────────────────────────┤
│   Independent AI Agent Core   │
│      🤖 TriageAgent          │  ← Can run anywhere!
│   (pydantic-ai + tools)      │     (Lambda, Flask, etc.)
├────────────────────────┤
│      Data & Config Layer      │
│  💾 SQLite  📄 JSON Config   │
└────────────────────────┘
```

### 🔧 **Framework Choices & Rationale**

#### **FastAPI** - Web Framework
**Why chosen:**
- ⚡ **Performance**: Async support, automatic validation, minimal overhead
- 📜 **Auto Documentation**: Built-in Swagger UI for API integration
- 🔍 **Type Safety**: Pydantic integration for request/response validation
- 🛠️ **Production Ready**: Battle-tested with healthcare applications

#### **pydantic-ai** - Agent Framework  
**Why chosen:**
- 🤖 **Agent-First Design**: Built specifically for LLM agents with tool calling
- 🔗 **Model Agnostic**: Works with OpenAI, local LLMs, or any OpenAI-compatible API
- ⚙️ **Type Safety**: Full Pydantic integration for structured outputs
- 🔄 **Async Native**: Perfect for production workloads

**vs. LangChain**: More focused, less bloated, better type safety  
**vs. Custom Implementation**: Handles LLM complexity, tool calling, retries

#### **Jinja2 + HTMX** - UI Layer
- Chosen for simplicity and speed: server-rendered templates with light interactivity, no heavy frontend build. Great fit for this take-home.

### 🎯 **Key Design Decisions**

1. **Agent Independence**: Core logic separated from web framework
2. **Tool Architecture**: Dynamic tool loading based on client configuration
3. **Rule Engine**: Medical rules separated from LLM for compliance/auditability  
4. **Client Isolation**: Multi-tenant architecture with configuration versioning

### 🧩 Rule Types and Current Usage

- Active today: specialty_urgent_mapping — maps detected specialty to urgency using client-specific criteria; used in triage decisions now.
- Extensible: triage_rules and custom — defined in client config for future rule engines and bespoke logic; not currently applied in the agent’s urgency calculation.

### 🧩 Interface-First, Cloud-Agnostic Design

- Observability: Use OpenTelemetry APIs for traces, metrics, and logs, then choose any exporter (CloudWatch, Azure Monitor, GCP Operations, Prometheus, Datadog, etc.). This keeps the code independent of vendor SDKs.
- Logging: Emit structured logs (JSON) with correlation via trace_id/span_id; route through your platform of choice.
- Secrets/config: Read via environment variables; bind to cloud secret stores (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager) at deploy time.
- Pluggable adapters: For provider services (object storage, message queues), define clear interfaces and provide adapters per platform.

This interface-first approach ensures the system can run on any public cloud or customer infrastructure, including on-prem.

## Quick Start

### 📺 **Prerequisites**

- Python 3.8+
- OpenAI API key (or local LLM endpoint)

### ⚡ **1. Installation**

```bash
# Clone the repository
git clone <your-repo-url>
cd intake_t

# Install dependencies
pip install -r requirements.txt
```

### 🔑 **2. Configuration** 

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your settings:
OPENAI_API_KEY=your_openai_api_key
# OR for local LLM:
LLM_BASE_URL=http://localhost:11434/v1  # Example: Ollama
OPENAI_API_KEY=dummy_key  # Required but unused for local
```

### 🚀 **3. Run the System**

```bash
# Start the web application
python main.py

# System will be available at:
# http://localhost:8000 - Triage Interface
# http://localhost:8000/ui/admin/clients - Client Management  
# http://localhost:8000/docs - API Documentation
```

### 🤖 **4. Use Agent Independently**

```python
# In any Python environment (Lambda, Flask, etc.)
from triage import TriageAgent, TriageInput

agent = TriageAgent()  # Auto-detects config from environment
result = await agent.analyze(TriageInput(
    client_id="acme_childrens",
    referral_text=["5-year-old with new onset seizures"]
))

print(f"Specialty: {result.specialty}")  # NEUROLOGY
print(f"Urgent: {result.urgency}")      # 1 (urgent)
```

## Deployment

We deployed this app to Render for easy demo purposes. Note: on Render's free tier, services may sleep after ~15 minutes of inactivity; the first request after idle can incur a cold start of up to ~1 minute. For full deployment strategy and an AWS reference architecture (private EC2 behind API Gateway via VPC Link, provisioned with Terraform), see [DEPLOYMENT.md](DEPLOYMENT.md).

Note: For a take-home, asking for deep DevOps/MLOps (e.g., AWS Lambda + API Gateway builds) is too much. Candidates should be evaluated on a “deploy everywhere” approach—clean, portable interfaces over cloud-specific wiring.

We prioritize an interface-first, cloud-agnostic design (e.g., OpenTelemetry for observability) so this system can be deployed on any public cloud or customer-managed/on‑prem infrastructure.

## Usage

[TODO: How to use the system]

## API Documentation

### 📚 **Full Documentation**
Visit `/docs` when running the system for complete interactive Swagger documentation.

### 🗺️ **Core Triage Endpoint**

**POST `/triage`** - Analyze medical referral

```json
{
  "client_id": "acme_childrens",
  "referral_text": [
    "Patient: 5-year-old male",
    "Chief Complaint: New onset generalized seizures", 
    "History: Previously healthy child, first seizure this morning"
  ]
}
```

**Response:**
```json
{
  "specialty": "NEUROLOGY",
  "urgency": 1,
  "evidence": "New onset seizures in pediatric patient requires urgent neurology evaluation",
  "confidence": 0.92
}
```

### 🏥 **Client Management**

- **GET `/api/admin/clients`** - List all clients
- **POST `/api/admin/clients`** - Create new client with rules/prompts/tools
- **PUT `/api/admin/clients/{client_id}`** - Update client configuration
- **DELETE `/api/admin/clients/{client_id}`** - Remove client

### 🗺️ **System Info**

- **GET `/clients`** - List available client IDs for triage
- **GET `/`** - System health and status

### 📄 Further Reading
- Agent and prompt design: [AGENT_PROMPTS.md](AGENT_PROMPTS.md)
- Deployment strategy and AWS reference: [DEPLOYMENT.md](DEPLOYMENT.md)

### 📄 **Example Client Configuration**

```json
{
  "id": "hospital_xyz",
  "name": "XYZ Medical Center",
  "version": "v2",
  "active": true,
  "rules": [{
    "id": "cardiology_urgent_v1",
    "type": "specialty_urgent_mapping",
    "data": {
      "CARDIOLOGY": "Chest pain, MI, arrhythmia",
      "NEUROLOGY": "Stroke symptoms, seizures"
    }
  }],
  "tools": [{
    "name": "check_patient_history",
    "enabled": true,
    "config": {"max_history_years": 5}
  }]
}
```

## Technical Details

### 📊 **Web Interface**
Access the web interface at `http://localhost:8000` for:
- **Triage Testing**: Interactive form with pre-loaded medical cases
- **Client Management**: Full CRUD interface for client configurations
- **Admin Dashboard**: System monitoring and database access

### 📜 **API Reference** 
Complete API documentation available at `http://localhost:8000/docs` (Swagger UI)

### 📁 **Project Structure**
```
intake_t/
├── triage/              # Independent AI agent core
│   ├── agent.py         # Main TriageAgent class
│   ├── types.py         # Pydantic models
│   └── tools.py         # Dynamic tool system
├── main.py              # FastAPI web application
├── client_config.json   # Client rules and configurations
└── templates/           # Web UI templates
```

---

**Built for production healthcare environments with enterprise-grade security and scalability.**
