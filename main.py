from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import logging
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import uvicorn
import asyncio
import logging
import json
from sqladmin import Admin, ModelView
from db import get_engine
from models import RequestLog
from triage_models import TriageLog
from client_config import load_client_config, ClientConfig
from middleware import RequestLoggingMiddleware, setup_logging_config
from logging_service import TriageTimer
from triage_logging_service import triage_logger
# Load environment variables from .env if present
load_dotenv()

# Setup logger
logger = logging.getLogger(__name__)

APP_NAME = os.getenv("APP_NAME", "intake_t")
APP_ENV = os.getenv("APP_ENV", "development")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
RELOAD = os.getenv("RELOAD", "true").strip().lower() in {"1", "true", "yes", "on"}
CLIENT_CONFIG_PATH = os.getenv("CLIENT_CONFIG_PATH", "client_config.json")

app = FastAPI(
    title="LLM-Powered Urgent Diagnosis Triage System",
    description="""
    A proof-of-concept FastAPI application that provides LLM-powered medical referral triage.
    
    ## Features
    
    * **Specialty Detection**: Uses LLM to infer the correct medical specialty from unstructured referral text
    * **Urgency Assessment**: Applies configurable client-specific rules to determine urgency (0 = not urgent, 1 = urgent)
    * **Evidence Extraction**: Provides supporting evidence and rationale from the referral text
    * **Confidence Scoring**: Returns confidence score (0.0-1.0) for the assessment
    
    ## Usage
    
    1. Send referral text and client ID to `/triage` endpoint
    2. Receive structured JSON with specialty, urgency, evidence, and confidence
    3. Use the results to prioritize patient care and scheduling
    
    ## Client Configuration
    
    Each client has configurable specialty urgency mappings and available tools.
    Available clients: `acme_childrens`, `northstar_health`, `carewell_clinics`
    """,
    version="1.0.0",
    contact={
        "name": "Triage System",
        "email": "support@example.com"
    },
    license_info={
        "name": "MIT License"
    }
)

# Add logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Initialize templates
templates = Jinja2Templates(directory="templates")

# Request/Response schemas for /triage endpoint
class TriageRequest(BaseModel):
    """Request payload for medical referral triage analysis."""
    
    client_id: str = Field(
        ..., 
        description="Client identifier that determines which clinic's rules and tools to use",
        example="acme_childrens"
    )
    referral_text: List[str] = Field(
        ..., 
        description="List of page strings from the referral document. Each string represents one page of the referral.",
        example=[
            "Patient John Doe, 5 years old, presents with new onset seizures.",
            "Episodes started 2 days ago, lasting 1-2 minutes each.", 
            "Parents report 3 episodes in past 24 hours. No fever, no trauma history."
        ]
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "client_id": "acme_childrens",
                "referral_text": [
                    "Patient John Doe, 5 years old, presents with new onset seizures.",
                    "Episodes started 2 days ago, lasting 1-2 minutes each.",
                    "Parents report 3 episodes in past 24 hours. No fever, no trauma history."
                ]
            }
        }
    }


class TriageResponse(BaseModel):
    """Response from medical referral triage analysis."""
    
    specialty: str = Field(
        ..., 
        description="Detected medical specialty based on referral content",
        example="NEUROLOGY"
    )
    urgency: int = Field(
        ..., 
        ge=0, 
        le=1, 
        description="Urgency status determined by client-specific rules: 1 = urgent, 0 = not urgent",
        example=1
    )
    evidence: str = Field(
        ..., 
        description="Supporting evidence and rationale for the specialty and urgency determination",
        example="Patient presents with new onset seizures in a 5-year-old child. Based on NEUROLOGY urgency criteria: 'New onset seizure or seizure like events' - this qualifies as urgent."
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence score for the overall assessment (0.0 = no confidence, 1.0 = highest confidence)",
        example=0.85
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "specialty": "NEUROLOGY",
                "urgency": 1,
                "evidence": "Patient presents with new onset seizures in a 5-year-old child. Based on NEUROLOGY urgency criteria: 'New onset seizure or seizure like events' - this qualifies as urgent.",
                "confidence": 0.85
            }
        }
    }

# Admin UI (SQLAdmin) - mount at /sqladmin to avoid conflicts
engine = get_engine()
admin = Admin(app, engine, base_url='/sqladmin')

class RequestLogAdmin(ModelView, model=RequestLog):
    column_list = [RequestLog.id, RequestLog.method, RequestLog.path, RequestLog.status_code, 
                   RequestLog.response_time_ms, RequestLog.success, RequestLog.request_time]
    column_searchable_list = [RequestLog.path, RequestLog.method]
    column_sortable_list = [RequestLog.id, RequestLog.request_time, RequestLog.response_time_ms, RequestLog.status_code]
    column_default_sort = [(RequestLog.request_time, True)]  # Sort by request_time descending
    page_size = 50

class TriageLogAdmin(ModelView, model=TriageLog):
    column_list = [TriageLog.id, TriageLog.client_id, TriageLog.detected_specialty, 
                   TriageLog.urgency_result, TriageLog.confidence_score, TriageLog.success,
                   TriageLog.total_analysis_time_ms, TriageLog.created_at]
    column_searchable_list = [TriageLog.client_id, TriageLog.detected_specialty, TriageLog.request_id]
    column_sortable_list = [TriageLog.id, TriageLog.created_at, TriageLog.total_analysis_time_ms, TriageLog.confidence_score]
    column_default_sort = [(TriageLog.created_at, True)]  # Sort by created_at descending
    page_size = 25
    # Note: Sensitive data (referral_text, llm_response, evidence) is encrypted in database
    column_details_list = [TriageLog.referral_text_encrypted, TriageLog.llm_response_encrypted, TriageLog.evidence_encrypted]

admin.add_view(RequestLogAdmin)
admin.add_view(TriageLogAdmin)

# Database init and client config load on startup
@app.on_event("startup")
async def on_startup():
    # Setup logging configuration
    setup_logging_config()
    
    from db import init_db
    await init_db()
    
    # Load client configuration
    try:
        app.state.client_config = load_client_config(CLIENT_CONFIG_PATH)
        logging.info(f"Loaded {len(app.state.client_config.clients)} clients from {CLIENT_CONFIG_PATH}")
    except Exception as e:
        logging.error(f"Failed to load client config: {e}")
        raise

# Web UI Routes
@app.get("/ui", response_class=HTMLResponse, tags=["Web UI"])
async def triage_ui(request: Request):
    """Triage testing web interface."""
    return templates.TemplateResponse("triage.html", {"request": request})

@app.get("/ui/admin", response_class=HTMLResponse, tags=["Web UI"])
async def admin_ui(request: Request):
    """Admin dashboard web interface."""
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/ui/admin/clients", response_class=HTMLResponse, tags=["Web UI"])
async def client_management_ui(request: Request):
    """Client management web interface."""
    return templates.TemplateResponse("client_management.html", {"request": request})

@app.get("/ui/admin/stats", tags=["Web UI"])
async def admin_stats():
    """Get statistics for admin dashboard."""
    try:
        stats = await triage_logger.get_triage_stats(hours=24)
        
        # Format stats for HTML display
        return HTMLResponse(f"""
        <div class="bg-white overflow-hidden shadow rounded-lg">
            <div class="p-5">
                <div class="flex items-center">
                    <div class="flex-shrink-0">
                        <div class="text-2xl">📊</div>
                    </div>
                    <div class="ml-5 w-0 flex-1">
                        <dl>
                            <dt class="text-sm font-medium text-gray-500 truncate">Total Analyses</dt>
                            <dd class="text-lg font-medium text-gray-900">{stats.get('total_analyses', 0)}</dd>
                        </dl>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="bg-white overflow-hidden shadow rounded-lg">
            <div class="p-5">
                <div class="flex items-center">
                    <div class="flex-shrink-0">
                        <div class="text-2xl">✅</div>
                    </div>
                    <div class="ml-5 w-0 flex-1">
                        <dl>
                            <dt class="text-sm font-medium text-gray-500 truncate">Success Rate</dt>
                            <dd class="text-lg font-medium text-gray-900">{stats.get('success_rate', 0):.1f}%</dd>
                        </dl>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="bg-white overflow-hidden shadow rounded-lg">
            <div class="p-5">
                <div class="flex items-center">
                    <div class="flex-shrink-0">
                        <div class="text-2xl">⚡</div>
                    </div>
                    <div class="ml-5 w-0 flex-1">
                        <dl>
                            <dt class="text-sm font-medium text-gray-500 truncate">Avg Response Time</dt>
                            <dd class="text-lg font-medium text-gray-900">{stats.get('average_analysis_time_ms', 0):.0f}ms</dd>
                        </dl>
                    </div>
                </div>
            </div>
        </div>
        """)
    except Exception as e:
        return HTMLResponse(f"<div class='text-red-500'>Error loading stats: {e}</div>")

@app.get("/ui/admin/logs", tags=["Web UI"])
async def admin_logs():
    """Get recent triage logs for admin interface."""
    try:
        from sqlalchemy import select
        from db import get_session
        
        async for session in get_session():
            result = await session.execute(
                select(TriageLog)
                .order_by(TriageLog.created_at.desc())
                .limit(10)
            )
            logs = result.scalars().all()
            
            if not logs:
                return HTMLResponse("""
                <div class="text-center py-8 text-gray-500">
                    <div class="text-4xl mb-2">📋</div>
                    <p>No triage logs found</p>
                </div>
                """)
            
            # Build HTML for logs
            html_parts = []
            for log in logs:
                urgency_badge = "🚨 Urgent" if log.urgency_result == 1 else "⏳ Not Urgent"
                urgency_class = "bg-red-100 text-red-800" if log.urgency_result == 1 else "bg-green-100 text-green-800"
                
                html_parts.append(f"""
                <div class="border border-gray-200 rounded-lg p-4 mb-4">
                    <div class="flex justify-between items-start mb-2">
                        <div>
                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                {log.detected_specialty}
                            </span>
                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {urgency_class} ml-2">
                                {urgency_badge}
                            </span>
                        </div>
                        <div class="text-sm text-gray-500">
                            {log.created_at.strftime('%Y-%m-%d %H:%M:%S')}
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-3 gap-4 text-sm">
                        <div>
                            <span class="font-medium">Client:</span> {log.client_id}
                        </div>
                        <div>
                            <span class="font-medium">Confidence:</span> {log.confidence_score:.2f}
                        </div>
                        <div>
                            <span class="font-medium">Time:</span> {log.total_analysis_time_ms:.0f}ms
                        </div>
                    </div>
                    
                    <div class="mt-2 flex space-x-2">
                        <button onclick="viewDecryptedLog({log.id})" 
                                class="text-xs px-2 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200">
                            🔓 View Decrypted
                        </button>
                    </div>
                    
                    <div class="log-details mt-3 p-3 bg-gray-50 rounded text-sm" style="display: none;">
                        <div><strong>Request ID:</strong> {log.request_id}</div>
                        <div><strong>Pages:</strong> {log.referral_pages}</div>
                        <div><strong>Model:</strong> {log.llm_model or 'N/A'}</div>
                        <div class="mt-2 text-xs text-gray-600">
                            <em>Referral text and responses are encrypted in database</em>
                        </div>
                    </div>
                </div>
                """)
            
            return HTMLResponse(''.join(html_parts))
            
    except Exception as e:
        return HTMLResponse(f"<div class='text-red-500'>Error loading logs: {e}</div>")

@app.post("/api/triage/ui", tags=["Web UI API"])
async def api_triage_for_ui(request: Request):
    """Triage endpoint for web UI (returns HTML response)."""
    try:
        # Get JSON data from request
        try:
            data = await request.json()
        except Exception as json_error:
            logger.error(f"JSON parsing error: {json_error}")
            # Try to get form data instead
            form_data = await request.form()
            referral_text = form_data.get('referral_text', '')
            client_id = form_data.get('client_id', '')
            
            if not referral_text or not client_id:
                return HTMLResponse(f"""
                <div class="bg-red-50 border border-red-200 rounded-lg p-4">
                    <div class="text-red-800">
                        <h3 class="font-medium">❌ Missing Data</h3>
                        <p>Please provide both client ID and referral text.</p>
                    </div>
                </div>
                """)
            
            referral_lines = [line.strip() for line in referral_text.split('\n') if line.strip()]
            data = {
                'client_id': client_id,
                'referral_text': referral_lines
            }
            
        # Validate the data
        if not data.get('client_id') or not data.get('referral_text'):
            return HTMLResponse(f"""
            <div class="bg-red-50 border border-red-200 rounded-lg p-4">
                <div class="text-red-800">
                    <h3 class="font-medium">❌ Invalid Data</h3>
                    <p>Please provide both client ID and referral text.</p>
                </div>
            </div>
            """)
        
        # Create triage request using the existing model
        triage_request = TriageRequest(
            client_id=data['client_id'],
            referral_text=data['referral_text']
        )
        
        # Process with existing triage logic
        # Store request data for logging middleware
        request.state.triage_client_id = triage_request.client_id
        request.state.referral_pages = len(triage_request.referral_text)
        
        # Initialize and run triage agent (same logic as main triage endpoint)
        from triage import TriageAgent, TriageInput
        from logging_service import TriageTimer
        
        client_config = app.state.client_config
        client = client_config.get_client(triage_request.client_id)
        if not client:
            available_clients = [c.id for c in client_config.clients]
            return HTMLResponse(f"""
            <div class="bg-red-50 border border-red-200 rounded-lg p-4">
                <div class="text-red-800">
                    <h3 class="font-medium">❌ Client Not Found</h3>
                    <p>Client '{triage_request.client_id}' not found.</p>
                    <p>Available: {', '.join(available_clients)}</p>
                </div>
            </div>
            """)
        
        # Check if we're in test mode (no OpenAI API key configured)
        test_mode = not bool(os.getenv("OPENAI_API_KEY"))
        
        if test_mode:
            # Return mock response for testing UI
            return HTMLResponse(f"""
            <div class="space-y-4">
                <div class="bg-green-50 border border-green-200 rounded-lg p-4">
                    <h3 class="text-lg font-medium text-green-800 mb-3">✅ Analysis Complete (Test Mode)</h3>
                    
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700">Detected Specialty</label>
                            <div class="mt-1">
                                <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
                                    NEUROLOGY
                                </span>
                            </div>
                        </div>
                        
                        <div>
                            <label class="block text-sm font-medium text-gray-700">Urgency</label>
                            <div class="mt-1">
                                <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800">
                                    🚨 URGENT
                                </span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700">Confidence Score</label>
                        <div class="mt-1">
                            <span class="text-lg font-medium text-green-600">0.85</span>
                            <div class="w-full bg-gray-200 rounded-full h-2 mt-1">
                                <div class="bg-blue-600 h-2 rounded-full" style="width: 85%"></div>
                            </div>
                        </div>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Clinical Evidence & Reasoning</label>
                        <div class="bg-gray-50 rounded-lg p-3 text-sm">
                            <strong>TEST MODE:</strong> Mock analysis for UI demonstration. Patient presents with seizures which would typically be classified as NEUROLOGY specialty. Based on client rules for '{triage_request.client_id}', new onset seizures are classified as urgent.
                        </div>
                    </div>
                    
                    <div class="mt-4 p-3 bg-gray-50 rounded-lg">
                        <div class="text-sm font-medium text-gray-700 mb-2">Analysis Details</div>
                        <div class="grid grid-cols-2 gap-4 text-xs text-gray-600">
                            <div>
                                <span class="font-medium">Total Time:</span> 150ms
                            </div>
                            <div>
                                <span class="font-medium">Agent Init:</span> 50ms
                            </div>
                            <div>
                                <span class="font-medium">LLM Model:</span> Mock Mode
                            </div>
                            <div>
                                <span class="font-medium">Pages:</span> {len(triage_request.referral_text)}
                            </div>
                        </div>
                        <div class="mt-2 text-xs text-gray-500">
                            <span class="font-medium">Tools:</span> Client rules processing, specialty detection, urgency mapping (test mode - no actual tools called)
                        </div>
                        <div class="mt-3 bg-yellow-50 border border-yellow-200 rounded p-2 text-xs">
                            ⚠️ <strong>TEST MODE:</strong> No LLM service configured. Configure OPENAI_API_KEY or LLM_BASE_URL for real analysis.
                        </div>
                    </div>
                </div>
            </div>
            """)
        
        # Initialize the agent with timing
        with TriageTimer("agent_initialization") as agent_timer:
            agent = TriageAgent()
        
        # Get client rules
        client_rules = {
            'rules': [rule.model_dump() for rule in client.rules],
            'tools': [tool.model_dump() for tool in client.tools]
        }
        
        # Create agent input
        agent_input = TriageInput(
            client_id=triage_request.client_id,
            referral_text=triage_request.referral_text,
            client_rules=client_rules
        )
        
        # Run the agent analysis with timing
        with TriageTimer("triage_analysis") as analysis_timer:
            result = await agent.analyze(agent_input)
        
        # Log to triage database
        try:
            await triage_logger.log_triage_analysis(
                client_id=triage_request.client_id,
                referral_text=triage_request.referral_text,
                agent_init_time_ms=agent_timer.elapsed_ms,
                total_analysis_time_ms=analysis_timer.elapsed_ms,
                llm_response=getattr(agent, '_last_llm_response', result.evidence),
                llm_model=agent.llm_model,
                detected_specialty=result.specialty,
                urgency_result=result.urgency,
                confidence_score=result.confidence,
                evidence=result.evidence,
                success=True
            )
        except Exception as log_error:
            logger.warning(f"Failed to log triage analysis: {log_error}")
        
        # Return HTML response
        urgency_badge = "🚨 URGENT" if result.urgency == 1 else "⏳ Not Urgent"
        urgency_class = "bg-red-100 text-red-800" if result.urgency == 1 else "bg-green-100 text-green-800"
        confidence_class = "text-green-600" if result.confidence >= 0.7 else "text-yellow-600" if result.confidence >= 0.5 else "text-red-600"
        
        return HTMLResponse(f"""
        <div class="space-y-4">
            <div class="bg-green-50 border border-green-200 rounded-lg p-4">
                <h3 class="text-lg font-medium text-green-800 mb-3">✅ Analysis Complete</h3>
                
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Detected Specialty</label>
                        <div class="mt-1">
                            <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
                                {result.specialty}
                            </span>
                        </div>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Urgency</label>
                        <div class="mt-1">
                            <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium {urgency_class}">
                                {urgency_badge}
                            </span>
                        </div>
                    </div>
                </div>
                
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700">Confidence Score</label>
                    <div class="mt-1">
                        <span class="text-lg font-medium {confidence_class}">{result.confidence:.2f}</span>
                        <div class="w-full bg-gray-200 rounded-full h-2 mt-1">
                            <div class="bg-blue-600 h-2 rounded-full" style="width: {result.confidence * 100}%"></div>
                        </div>
                    </div>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Clinical Evidence & Reasoning</label>
                    <div class="bg-gray-50 rounded-lg p-3 text-sm">
                        {result.evidence}
                    </div>
                </div>
                
                <div class="mt-4 p-3 bg-gray-50 rounded-lg">
                    <div class="text-sm font-medium text-gray-700 mb-2">Analysis Details</div>
                    <div class="grid grid-cols-2 gap-4 text-xs text-gray-600">
                        <div>
                            <span class="font-medium">Total Time:</span> {analysis_timer.elapsed_ms:.0f}ms
                        </div>
                        <div>
                            <span class="font-medium">Agent Init:</span> {agent_timer.elapsed_ms:.0f}ms
                        </div>
                        <div>
                            <span class="font-medium">LLM Model:</span> {getattr(agent, 'llm_model', 'Unknown')}
                        </div>
                        <div>
                            <span class="font-medium">Pages:</span> {len(triage_request.referral_text)}
                        </div>
                    </div>
                    <div class="mt-2 text-xs text-gray-500">
                        <span class="font-medium">Tools:</span> Client rules processing, specialty detection, urgency mapping{', ' + ', '.join(getattr(agent, 'tools_called', [])) if getattr(agent, 'tools_called', []) else ''}
                    </div>
                </div>
            </div>
        </div>
        """)
        
    except Exception as e:
        logger.error(f"UI triage analysis failed: {e}")
        return HTMLResponse(f"""
        <div class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="text-red-800">
                <h3 class="font-medium">❌ Analysis Failed</h3>
                <p class="text-sm mt-1">{str(e)}</p>
            </div>
        </div>
        """)

# API Routes
@app.get(
    "/", 
    tags=["System"],
    summary="System Status",
    description="Get system status and basic information about the triage API.",
    response_description="System status information"
)
async def read_root():
    """Get system status and basic information."""
    return {
        "status": "ok", 
        "app": APP_NAME, 
        "env": APP_ENV,
        "version": "1.0.0",
        "description": "LLM-Powered Urgent Diagnosis Triage System",
        "available_endpoints": [
            "GET / - System status",
            "POST /triage - Medical referral triage analysis",
            "GET /docs - API documentation (Swagger UI)",
            "GET /redoc - API documentation (ReDoc)"
        ]
    }


@app.get(
    "/clients",
    tags=["System"],
    summary="List Available Clients",
    description="Get a list of available client IDs and their configurations for triage analysis.",
    response_description="List of available clients with their details"
)
async def list_clients():
    """Get list of available clients and their configurations."""
    client_config: ClientConfig = app.state.client_config
    
    clients_info = []
    for client in client_config.clients:
        # Count rules by type
        rule_types = {}
        for rule in client.rules:
            rule_types[rule.type] = rule_types.get(rule.type, 0) + 1
        
        # Count enabled tools
        enabled_tools = [tool.name for tool in client.tools if tool.enabled]
        
        clients_info.append({
            "client_id": client.id,
            "name": client.name,
            "rules": {
                "total": len(client.rules),
                "by_type": rule_types
            },
            "tools": {
                "total": len(client.tools),
                "enabled": enabled_tools,
                "count_enabled": len(enabled_tools)
            }
        })
    
    return {
        "total_clients": len(clients_info),
        "clients": clients_info
    }

@app.post(
    "/triage", 
    response_model=TriageResponse, 
    tags=["Triage"],
    summary="Medical Referral Triage Analysis",
    description="""
    Analyze medical referral documents to determine specialty and urgency.
    
    This endpoint uses an LLM-powered agent to:
    1. **Detect Medical Specialty**: Analyze unstructured referral text to infer the most appropriate medical specialty
    2. **Assess Urgency**: Apply client-specific configurable rules to determine if the referral is urgent (1) or not (0)
    3. **Extract Evidence**: Provide supporting rationale and evidence from the referral text
    4. **Generate Confidence Score**: Return a confidence score (0.0-1.0) for the overall assessment
    
    ## Process Flow
    
    1. **Client Validation**: Verify the client_id exists and load client-specific rules
    2. **LLM Analysis**: Send referral text to LLM for specialty detection and clinical detail extraction
    3. **Rule Application**: Match detected specialty against client's urgency criteria
    4. **Response Generation**: Return structured JSON with specialty, urgency (0/1), evidence, and confidence
    
    ## Available Clients
    
    - `acme_childrens` - Acme Children's Hospital with pediatric-focused rules
    - `northstar_health` - NorthStar Health Network with general healthcare rules
    - `carewell_clinics` - CareWell Clinics with specialized urgent care criteria
    
    ## Specialty Detection
    
    The system can detect these medical specialties:
    NEUROLOGY, CARDIOLOGY, ORTHOPEDICS, ENDOCRINOLOGY, GASTROENTEROLOGY, GENERAL_SURGERY, 
    GYNECOLOGY, OPHTHALMOLOGY, EAR_NOSE_AND_THROAT_OTOLARYNGOLOGY, INFECTIOUS_DISEASE, 
    NUTRITION, OCCUPATIONAL_THERAPY, PHYSICAL_THERAPY, PULMONOLOGY_RESPIRATORY_AND_SLEEP_MEDICINE, 
    SPEECH_THERAPY, WOUND_CARE, and others.
    
    ## Important Notes
    
    - This system provides triage assistance and is not a substitute for clinical judgment
    - Results should be reviewed by qualified healthcare professionals
    - The urgency determination is based on configurable client rules, not clinical diagnosis
    """,
    response_description="Structured triage analysis with specialty, urgency, evidence, and confidence",
    responses={
        200: {
            "description": "Successful triage analysis",
            "content": {
                "application/json": {
                    "example": {
                        "specialty": "NEUROLOGY",
                        "urgency": 1,
                        "evidence": "Patient presents with new onset seizures in a 5-year-old child. Based on NEUROLOGY urgency criteria: 'New onset seizure or seizure like events' - this qualifies as urgent.",
                        "confidence": 0.85
                    }
                }
            }
        },
        404: {
            "description": "Client not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Client 'invalid_client' not found. Available: ['acme_childrens', 'northstar_health', 'carewell_clinics']"
                    }
                }
            }
        },
        400: {
            "description": "Invalid request data",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Validation error in request payload"
                    }
                }
            }
        },
        429: {
            "description": "Rate limit exceeded",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Rate limit exceeded",
                            "message": "OpenAI API quota exceeded. Please check your billing and usage.",
                            "type": "quota_exceeded",
                            "retry_after": "Please try again later or upgrade your OpenAI plan."
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Internal server error",
                            "message": "An unexpected error occurred during analysis. Please try again or contact support.",
                            "type": "internal_error"
                        }
                    }
                }
            }
        },
        502: {
            "description": "Bad gateway - Upstream service error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Upstream service error",
                            "message": "LLM service is temporarily unavailable. Please try again later.",
                            "type": "upstream_error"
                        }
                    }
                }
            }
        },
        503: {
            "description": "Service unavailable",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "LLM service unavailable",
                            "message": "The AI analysis service is currently unavailable. Please try again later.",
                            "type": "service_unavailable"
                        }
                    }
                }
            }
        }
    }
)
async def triage_referral(triage_request: TriageRequest, request: Request) -> TriageResponse:
    """
    Analyze medical referral for specialty detection and urgency assessment.
    
    Args:
        triage_request: TriageRequest containing client_id and referral_text pages
        request: FastAPI Request object for logging metadata
        
    Returns:
        TriageResponse with specialty, urgency (0/1), evidence, and confidence
        
    Raises:
        HTTPException: 404 if client_id not found, 400 for validation errors
    """
    logger = logging.getLogger(__name__)
    # Store request data for logging middleware
    request.state.triage_client_id = triage_request.client_id
    request.state.referral_pages = len(triage_request.referral_text)
    
    # Validate client exists
    client_config: ClientConfig = app.state.client_config
    client = client_config.get_client(triage_request.client_id)
    if not client:
        available_clients = [c.id for c in client_config.clients]
        raise HTTPException(
            status_code=404,
            detail=f"Client '{triage_request.client_id}' not found. Available: {available_clients}"
        )
    
    # Use the actual TriageAgent for LLM-powered analysis
    try:
        from triage import TriageAgent, TriageInput
        
        # Initialize the agent with timing
        with TriageTimer("agent_initialization") as agent_timer:
            agent = TriageAgent()
        
        request.state.agent_init_time_ms = agent_timer.elapsed_ms
        logger.info(f"Agent initialized in {agent_timer.elapsed_ms:.2f}ms")
        
        # Get client rules for the agent (convert Pydantic models to dict)
        client_rules = {
            'rules': [rule.model_dump() for rule in client.rules],
            'tools': [tool.model_dump() for tool in client.tools]
        }
        
        # Create agent input
        agent_input = TriageInput(
            client_id=triage_request.client_id,
            referral_text=triage_request.referral_text,
            client_rules=client_rules
        )
        
        # Run the agent analysis with timing
        with TriageTimer("triage_analysis") as analysis_timer:
            result = await agent.analyze(agent_input)
        
        # Store timing and result data for logging
        request.state.llm_call_time_ms = getattr(agent, '_last_llm_time_ms', None)
        request.state.rule_processing_time_ms = getattr(agent, '_last_rule_time_ms', None)
        request.state.detected_specialty = result.specialty
        request.state.urgency_result = result.urgency
        request.state.confidence_score = result.confidence
        
        logger.info(f"Triage analysis completed in {analysis_timer.elapsed_ms:.2f}ms")
        logger.info(f"Result: specialty={result.specialty}, urgency={result.urgency}, confidence={result.confidence}")
        
        # Log to dedicated triage log (don't block response if logging fails)
        try:
            await triage_logger.log_triage_analysis(
                request_id=getattr(request.state, 'request_id', None),
                client_id=triage_request.client_id,
                client_ip=getattr(request.state, 'client_ip', None),
                user_agent=getattr(request.state, 'user_agent', None),
                referral_text=triage_request.referral_text,
                agent_init_time_ms=agent_timer.elapsed_ms,
                llm_call_time_ms=request.state.llm_call_time_ms,
                rule_processing_time_ms=request.state.rule_processing_time_ms,
                total_analysis_time_ms=analysis_timer.elapsed_ms,
                llm_response=getattr(agent, '_last_llm_response', result.evidence),
                llm_model=agent.llm_model,
                detected_specialty=result.specialty,
                urgency_result=result.urgency,
                confidence_score=result.confidence,
                evidence=result.evidence,
                success=True
            )
        except Exception as log_error:
            logger.warning(f"Failed to log triage analysis: {log_error}")
        
        # Check if the result indicates an API failure (not actual analysis)
        if (result.specialty == "UNKNOWN" and 
            result.confidence == 0.0 and 
            "status_code:" in result.evidence):
            
            # This is an API error, not a valid analysis result
            error_msg = result.evidence
            
            # Determine appropriate HTTP status code based on error type
            if "429" in error_msg or "quota" in error_msg.lower():
                # Rate limit or quota exceeded
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "message": "OpenAI API quota exceeded. Please check your billing and usage.",
                        "type": "quota_exceeded",
                        "retry_after": "Please try again later or upgrade your OpenAI plan."
                    }
                )
            elif "401" in error_msg or "unauthorized" in error_msg.lower():
                # Authentication error
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "Service configuration error",
                        "message": "LLM service authentication failed. Please contact support.",
                        "type": "authentication_error"
                    }
                )
            elif "500" in error_msg or "502" in error_msg or "503" in error_msg:
                # Upstream service error
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "Upstream service error",
                        "message": "LLM service is temporarily unavailable. Please try again later.",
                        "type": "upstream_error"
                    }
                )
            else:
                # Generic LLM service error
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "LLM service unavailable",
                        "message": "The AI analysis service is currently unavailable. Please try again later.",
                        "type": "service_unavailable"
                    }
                )
        
        # Valid analysis result
        return TriageResponse(
            specialty=result.specialty,
            urgency=result.urgency,
            evidence=result.evidence,
            confidence=result.confidence
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions (from above error handling)
        raise
        
    except Exception as e:
        # Store error data for logging
        request.state.error_type = type(e).__name__
        request.state.error_message = str(e)
        
        logger.error(f"Agent analysis failed with unexpected error: {e}")
        
        # Log error to triage log
        try:
            await triage_logger.log_triage_analysis(
                request_id=getattr(request.state, 'request_id', None),
                client_id=triage_request.client_id,
                client_ip=getattr(request.state, 'client_ip', None),
                user_agent=getattr(request.state, 'user_agent', None),
                referral_text=triage_request.referral_text,
                agent_init_time_ms=getattr(request.state, 'agent_init_time_ms', None),
                llm_response="",
                llm_model=getattr(agent, 'llm_model', None) if 'agent' in locals() else None,
                detected_specialty="UNKNOWN",
                urgency_result=0,
                confidence_score=0.0,
                evidence=f"Error: {str(e)}",
                success=False,
                error_type=type(e).__name__,
                error_message=str(e)
            )
        except Exception as log_error:
            logger.warning(f"Failed to log triage error: {log_error}")
        
        # For unexpected errors, return 500 Internal Server Error
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "message": "An unexpected error occurred during analysis. Please try again or contact support.",
                "type": "internal_error"
            }
        )

@app.get(
    "/triage-log/{log_id}/decrypted",
    tags=["Admin"],
    summary="Get Decrypted Triage Log",
    description="Get a triage log with decrypted sensitive data. Use with caution - contains PHI!"
)
async def get_decrypted_triage_log(log_id: int):
    """Get a triage log with decrypted sensitive health data."""
    try:
        decrypted_log = await triage_logger.get_decrypted_triage_log(log_id)
        if not decrypted_log:
            raise HTTPException(status_code=404, detail=f"Triage log {log_id} not found")
        
        return {
            "warning": "This response contains decrypted PHI - handle securely!",
            "log": decrypted_log
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt log: {str(e)}")

@app.get(
    "/ui/admin/triage-log/{log_id}/decrypted",
    tags=["Web UI"],
    summary="Get Decrypted Triage Log (HTML)",
    description="Get a triage log with decrypted sensitive data formatted for admin UI"
)
async def get_decrypted_triage_log_html(log_id: int):
    """Get a triage log with decrypted sensitive health data formatted as HTML."""
    try:
        decrypted_log = await triage_logger.get_decrypted_triage_log(log_id)
        if not decrypted_log:
            return HTMLResponse("""
            <div class="bg-red-50 border border-red-200 rounded-lg p-4">
                <div class="text-red-800">
                    <h3 class="font-medium">❌ Log Not Found</h3>
                    <p>Triage log {log_id} not found in database.</p>
                </div>
            </div>
            """)
        
        # Format referral text
        referral_text_html = ""
        if decrypted_log.get('referral_text'):
            referral_pages = decrypted_log['referral_text']
            if isinstance(referral_pages, list):
                referral_text_html = "<br>".join(f"<strong>Page {i+1}:</strong> {page}" for i, page in enumerate(referral_pages))
            else:
                referral_text_html = str(referral_pages)
        else:
            referral_text_html = "<em>No referral text available</em>"
        
        # Format timestamps
        created_at = decrypted_log.get('created_at', 'Unknown')
        if 'T' in str(created_at):
            created_at = created_at.replace('T', ' ').split('.')[0]  # Remove microseconds
        
        # Determine urgency styling
        urgency = decrypted_log.get('urgency_result', 0)
        urgency_badge = "🚨 URGENT" if urgency == 1 else "⏳ Not Urgent"
        urgency_class = "bg-red-100 text-red-800" if urgency == 1 else "bg-green-100 text-green-800"
        
        # Format confidence score
        confidence = decrypted_log.get('confidence_score', 0.0)
        confidence_class = "text-green-600" if confidence >= 0.7 else "text-yellow-600" if confidence >= 0.5 else "text-red-600"
        
        return HTMLResponse(f"""
        <div class="bg-yellow-50 border-l-4 border-yellow-400 p-4 mb-4">
            <div class="flex">
                <div class="flex-shrink-0">
                    <div class="text-yellow-400 text-xl">⚠️</div>
                </div>
                <div class="ml-3">
                    <h3 class="text-sm font-medium text-yellow-800">DECRYPTED HEALTH DATA</h3>
                    <div class="mt-2 text-sm text-yellow-700">
                        <p>This data contains decrypted PHI. Handle securely and in compliance with HIPAA regulations.</p>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="space-y-6">
            <!-- Log Metadata -->
            <div class="bg-white shadow rounded-lg p-6">
                <h3 class="text-lg font-medium text-gray-900 mb-4">📋 Log Information</h3>
                <div class="grid grid-cols-2 gap-4 text-sm">
                    <div><strong>Log ID:</strong> {decrypted_log.get('id', 'N/A')}</div>
                    <div><strong>Request ID:</strong> {decrypted_log.get('request_id', 'N/A')}</div>
                    <div><strong>Client ID:</strong> {decrypted_log.get('client_id', 'N/A')}</div>
                    <div><strong>Created:</strong> {created_at}</div>
                    <div><strong>Client IP:</strong> {decrypted_log.get('client_ip', 'N/A')}</div>
                    <div><strong>Analysis Time:</strong> {decrypted_log.get('total_analysis_time_ms', 0):.0f}ms</div>
                    <div><strong>LLM Model:</strong> {decrypted_log.get('llm_model', 'N/A')}</div>
                    <div><strong>Success:</strong> {"✅ Yes" if decrypted_log.get('success') else "❌ No"}</div>
                </div>
            </div>
            
            <!-- Analysis Results -->
            <div class="bg-white shadow rounded-lg p-6">
                <h3 class="text-lg font-medium text-gray-900 mb-4">🔍 Analysis Results</h3>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Detected Specialty</label>
                        <div class="mt-1">
                            <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
                                {decrypted_log.get('detected_specialty', 'UNKNOWN')}
                            </span>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Urgency</label>
                        <div class="mt-1">
                            <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium {urgency_class}">
                                {urgency_badge}
                            </span>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Confidence Score</label>
                        <div class="mt-1">
                            <span class="text-lg font-medium {confidence_class}">{confidence:.2f}</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Decrypted Referral Text -->
            <div class="bg-white shadow rounded-lg p-6">
                <h3 class="text-lg font-medium text-gray-900 mb-4">📄 Decrypted Referral Text</h3>
                <div class="bg-gray-50 rounded-lg p-4 text-sm">
                    {referral_text_html}
                </div>
            </div>
            
            <!-- LLM Response -->
            <div class="bg-white shadow rounded-lg p-6">
                <h3 class="text-lg font-medium text-gray-900 mb-4">🤖 LLM Response</h3>
                <div class="bg-gray-50 rounded-lg p-4 text-sm">
                    {decrypted_log.get('llm_response', '<em>No LLM response available</em>')}
                </div>
            </div>
            
            <!-- Clinical Evidence -->
            <div class="bg-white shadow rounded-lg p-6">
                <h3 class="text-lg font-medium text-gray-900 mb-4">🔬 Clinical Evidence</h3>
                <div class="bg-gray-50 rounded-lg p-4 text-sm">
                    {decrypted_log.get('evidence', '<em>No evidence available</em>')}
                </div>
            </div>
        </div>
        """)
        
    except Exception as e:
        logger.error(f"Failed to get decrypted triage log HTML: {e}")
        return HTMLResponse(f"""
        <div class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="text-red-800">
                <h3 class="font-medium">❌ Error</h3>
                <p>Failed to decrypt log: {str(e)}</p>
            </div>
        </div>
        """)


@app.post(
    "/admin/database/recreate",
    tags=["Admin"],
    summary="Recreate Database Tables",
    description="⚠️ DANGER: Drops and recreates all database tables. All data will be lost!"
)
async def recreate_database_tables():
    """Drop and recreate all database tables. WARNING: This deletes all data!"""
    try:
        logger.warning("Admin initiated database table recreation - ALL DATA WILL BE LOST")
        from db import Base, get_engine
        
        engine = get_engine()
        
        # Import all models to ensure they're registered
        from models import RequestLog
        from triage_models import TriageLog
        
        async with engine.begin() as conn:
            # Drop all tables
            await conn.run_sync(Base.metadata.drop_all)
            
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
        
        return {
            "status": "success",
            "message": "Database tables recreated successfully",
            "warning": "All previous data has been permanently deleted",
            "tables_created": [
                "request_logs",
                "triage_logs"
            ]
        }
        
    except Exception as e:
        logger.error(f"Database recreation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database recreation failed: {str(e)}")


@app.get(
    "/admin/encryption/test",
    tags=["Admin"], 
    summary="Test Encryption System",
    description="Test that health data encryption is working correctly"
)
async def test_encryption_system():
    """Test the health data encryption system."""
    try:
        from encryption import test_encryption, get_encryption
        
        # Test basic encryption
        encryption = get_encryption()
        test_data = "Patient has chest pain and needs urgent care"
        
        encrypted = encryption.encrypt(test_data)
        decrypted = encryption.decrypt(encrypted)
        
        success = test_data == decrypted
        
        return {
            "status": "success" if success else "failed",
            "test_passed": success,
            "original_length": len(test_data),
            "encrypted_length": len(encrypted),
            "encryption_key_configured": bool(os.getenv("HEALTH_DATA_ENCRYPTION_KEY")),
            "sample_encrypted_data": encrypted[:50] + "..." if len(encrypted) > 50 else encrypted
        }
        
    except Exception as e:
        logger.error(f"Encryption test failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "test_passed": False
        }


# Client Management API Endpoints
@app.get(
    "/api/admin/clients",
    tags=["Admin - Client Management"],
    summary="List All Clients",
    description="Get a list of all configured clients with their configurations"
)
async def list_clients_admin():
    """Get list of all clients for admin management."""
    try:
        client_config: ClientConfig = app.state.client_config
        
        clients_data = []
        for client in client_config.clients:
            clients_data.append({
                "id": client.id,
                "name": client.name,
                "description": client.description,
                "active": client.active,
                "created_at": client.created_at,
                "updated_at": client.updated_at,
                "rules_count": len(client.rules),
                "prompts_count": len(client.prompts),
                "tools_count": len([t for t in client.tools if t.enabled]),
                "total_tools": len(client.tools)
            })
        
        return {
            "clients": clients_data,
            "total": len(clients_data),
            "config_version": client_config.version,
            "config_updated_at": client_config.updated_at
        }
        
    except Exception as e:
        logger.error(f"Failed to list clients: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list clients: {str(e)}")


@app.get(
    "/api/admin/clients/{client_id}",
    tags=["Admin - Client Management"],
    summary="Get Client Details",
    description="Get detailed configuration for a specific client"
)
async def get_client_admin(client_id: str):
    """Get detailed client configuration."""
    try:
        client_config: ClientConfig = app.state.client_config
        client = client_config.get_client(client_id)
        
        if not client:
            raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
        
        return client.model_dump()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get client {client_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get client: {str(e)}")


@app.post(
    "/api/admin/clients",
    tags=["Admin - Client Management"],
    summary="Create New Client",
    description="Create a new client configuration"
)
async def create_client_admin(client_data: dict):
    """Create a new client configuration."""
    try:
        from client_config import Client, save_client_config
        
        # Validate required fields
        if "id" not in client_data or "name" not in client_data:
            raise HTTPException(status_code=400, detail="Client ID and name are required")
        
        client_config: ClientConfig = app.state.client_config
        
        # Check if client already exists
        if client_config.get_client(client_data["id"]):
            raise HTTPException(status_code=409, detail=f"Client '{client_data['id']}' already exists")
        
        # Create new client
        new_client = Client(**client_data)
        client_config.add_client(new_client)
        
        # Save configuration
        save_client_config(client_config, CLIENT_CONFIG_PATH)
        
        logger.info(f"Created new client: {client_data['id']}")
        return {
            "message": "Client created successfully",
            "client": new_client.model_dump()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create client: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create client: {str(e)}")


@app.put(
    "/api/admin/clients/{client_id}",
    tags=["Admin - Client Management"],
    summary="Update Client",
    description="Update an existing client configuration"
)
async def update_client_admin(client_id: str, client_data: dict):
    """Update an existing client configuration."""
    try:
        from client_config import Client, save_client_config
        
        client_config: ClientConfig = app.state.client_config
        
        # Check if client exists
        if not client_config.get_client(client_id):
            raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
        
        # Ensure ID matches
        client_data["id"] = client_id
        
        # Create updated client
        updated_client = Client(**client_data)
        client_config.update_client(client_id, updated_client)
        
        # Save configuration
        save_client_config(client_config, CLIENT_CONFIG_PATH)
        
        logger.info(f"Updated client: {client_id}")
        return {
            "message": "Client updated successfully",
            "client": updated_client.model_dump()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update client {client_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update client: {str(e)}")


@app.delete(
    "/api/admin/clients/{client_id}",
    tags=["Admin - Client Management"],
    summary="Delete Client",
    description="Delete a client configuration"
)
async def delete_client_admin(client_id: str):
    """Delete a client configuration."""
    try:
        from client_config import save_client_config
        
        client_config: ClientConfig = app.state.client_config
        
        # Check if client exists
        if not client_config.get_client(client_id):
            raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
        
        # Delete client
        client_config.delete_client(client_id)
        
        # Save configuration
        save_client_config(client_config, CLIENT_CONFIG_PATH)
        
        logger.info(f"Deleted client: {client_id}")
        return {"message": "Client deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete client {client_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete client: {str(e)}")


# Client Management UI Endpoints
@app.get("/ui/admin/clients/list", tags=["Web UI"])
async def clients_ui_endpoint():
    """Get clients data for admin UI."""
    try:
        client_config: ClientConfig = app.state.client_config
        
        clients_html = []
        for client in client_config.clients:
            status_badge = "✅ Active" if client.active else "❌ Inactive"
            status_class = "bg-green-100 text-green-800" if client.active else "bg-red-100 text-red-800"
            
            clients_html.append(f"""
            <div class="border border-gray-200 rounded-lg p-4 mb-4">
                <div class="flex justify-between items-start mb-2">
                    <div>
                        <h4 class="text-lg font-medium text-gray-900">{client.name}</h4>
                        <p class="text-sm text-gray-500">ID: {client.id}</p>
                        {f'<p class="text-sm text-gray-600 mt-1">{client.description}</p>' if client.description else ''}
                    </div>
                    <div class="flex items-center space-x-2">
                        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {status_class}">
                            {status_badge}
                        </span>
                    </div>
                </div>
                
                <div class="grid grid-cols-4 gap-4 text-sm mb-3">
                    <div>
                        <span class="font-medium">Rules:</span> {len(client.rules)}
                    </div>
                    <div>
                        <span class="font-medium">Prompts:</span> {len(client.prompts)}
                    </div>
                    <div>
                        <span class="font-medium">Tools:</span> {len([t for t in client.tools if t.enabled])}/{len(client.tools)}
                    </div>
                    <div>
                        <span class="font-medium">Updated:</span> {client.updated_at[:10] if client.updated_at else 'N/A'}
                    </div>
                </div>
                
                <div class="flex space-x-2">
                    <button onclick="viewClientDetails('{client.id}')" 
                            class="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded hover:bg-blue-200">
                        📋 View Details
                    </button>
                    <button onclick="editClient('{client.id}')" 
                            class="text-xs px-2 py-1 bg-yellow-100 text-yellow-700 rounded hover:bg-yellow-200">
                        ✏️ Edit
                    </button>
                    <button onclick="confirmDeleteClient('{client.id}', '{client.name}')" 
                            class="text-xs px-2 py-1 bg-red-100 text-red-700 rounded hover:bg-red-200">
                        🗑️ Delete
                    </button>
                </div>
            </div>
            """)
        
        if not clients_html:
            return HTMLResponse("""
            <div class="text-center py-8 text-gray-500">
                <div class="text-4xl mb-2">🏥</div>
                <p>No clients configured</p>
                <button onclick="showCreateClientForm()" 
                        class="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                    Create First Client
                </button>
            </div>
            """)
        
        return HTMLResponse(''.join(clients_html))
        
    except Exception as e:
        return HTMLResponse(f"<div class='text-red-500'>Error loading clients: {e}</div>")


@app.get("/ui/admin/clients/{client_id}/details", tags=["Web UI"])
async def client_details_ui_endpoint(client_id: str):
    """Get detailed client information for admin UI."""
    try:
        client_config: ClientConfig = app.state.client_config
        client = next((c for c in client_config.clients if c.id == client_id), None)
        
        if not client:
            return HTMLResponse("<div class='text-red-500'>Client not found</div>")
        
        # Format rules
        rules_html = []
        for rule in client.rules:
            rules_html.append(f"""
            <div class="border-l-4 border-blue-500 pl-3 mb-2">
                <div class="text-sm font-medium">{rule.id} ({rule.type})</div>
                <div class="text-xs text-gray-600">{rule.description or 'No description'}</div>
                <div class="text-xs text-gray-500 mt-1">Source: {rule.source or 'N/A'}</div>
            </div>
            """)
        
        # Format prompts
        prompts_html = []
        for prompt in client.prompts:
            prompts_html.append(f"""
            <div class="border-l-4 border-green-500 pl-3 mb-2">
                <div class="text-sm font-medium">{prompt.id} ({prompt.role})</div>
                <div class="text-xs text-gray-600">Locale: {prompt.locale or 'Default'}</div>
                <div class="text-xs text-gray-500 mt-1">{prompt.content[:100]}{'...' if len(prompt.content) > 100 else ''}</div>
            </div>
            """)
        
        # Format tools
        tools_html = []
        for tool in client.tools:
            status = "✅" if tool.enabled else "❌"
            tools_html.append(f"""
            <div class="border-l-4 border-purple-500 pl-3 mb-2">
                <div class="text-sm font-medium">{status} {tool.name}</div>
                <div class="text-xs text-gray-600">{tool.description}</div>
            </div>
            """)
        
        return HTMLResponse(f"""
        <div class="space-y-6">
            <div class="flex justify-between items-center">
                <h3 class="text-lg font-medium">Client Details: {client.name}</h3>
                <button onclick="closeModal()" class="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="text-sm font-medium text-gray-700">ID:</label>
                    <p class="text-sm text-gray-900">{client.id}</p>
                </div>
                <div>
                    <label class="text-sm font-medium text-gray-700">Status:</label>
                    <p class="text-sm text-gray-900">{'Active' if client.active else 'Inactive'}</p>
                </div>
                <div class="col-span-2">
                    <label class="text-sm font-medium text-gray-700">Description:</label>
                    <p class="text-sm text-gray-900">{client.description or 'No description'}</p>
                </div>
            </div>
            
            <div class="space-y-4">
                <div>
                    <h4 class="text-md font-medium mb-2">Rules ({len(client.rules)})</h4>
                    <div class="max-h-32 overflow-y-auto space-y-2">
                        {''.join(rules_html) if rules_html else '<p class="text-sm text-gray-500">No rules configured</p>'}
                    </div>
                </div>
                
                <div>
                    <h4 class="text-md font-medium mb-2">Prompts ({len(client.prompts)})</h4>
                    <div class="max-h-32 overflow-y-auto space-y-2">
                        {''.join(prompts_html) if prompts_html else '<p class="text-sm text-gray-500">No prompts configured</p>'}
                    </div>
                </div>
                
                <div>
                    <h4 class="text-md font-medium mb-2">Tools ({len(client.tools)})</h4>
                    <div class="max-h-32 overflow-y-auto space-y-2">
                        {''.join(tools_html) if tools_html else '<p class="text-sm text-gray-500">No tools configured</p>'}
                    </div>
                </div>
            </div>
            
            <div class="text-xs text-gray-500">
                Version: {client.version} | Created: {client.created_at[:19] if client.created_at else 'Unknown'} | 
                Updated: {client.updated_at[:19] if client.updated_at else 'Unknown'}
            </div>
        </div>
        """)
        
    except Exception as e:
        return HTMLResponse(f"<div class='text-red-500'>Error loading client details: {e}</div>")


@app.get("/ui/admin/clients/create-form", tags=["Web UI"])
async def create_client_form_endpoint():
    """Get create client form for admin UI."""
    return HTMLResponse("""
    <form id="createClientForm" class="space-y-6">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-medium">Create New Client</h3>
            <button type="button" onclick="closeModal()" class="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        
        <!-- Basic Info -->
        <div class="space-y-4">
            <h4 class="text-md font-medium text-gray-900 border-b border-gray-200 pb-2">Basic Information</h4>
            
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Client ID*</label>
                    <input type="text" name="id" required 
                           class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                           placeholder="e.g., clinic_001">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Client Name*</label>
                    <input type="text" name="name" required 
                           class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                           placeholder="e.g., Downtown Clinic">
                </div>
            </div>
            
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Version</label>
                    <input type="text" name="version" value="v1" 
                           class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                           placeholder="e.g., v1">
                </div>
                <div class="flex items-center pt-6">
                    <input type="checkbox" name="active" checked 
                           class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                    <label class="ml-2 block text-sm text-gray-900">Active</label>
                </div>
            </div>
            
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea name="description" rows="2" 
                          class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="Optional description of the client..."></textarea>
            </div>
        </div>
        
        <!-- Rules Section -->
        <div class="space-y-4">
            <div class="flex justify-between items-center border-b border-gray-200 pb-2">
                <h4 class="text-md font-medium text-gray-900">Rules</h4>
                <button type="button" onclick="addRule()" class="text-sm px-2 py-1 bg-blue-100 text-blue-700 rounded hover:bg-blue-200">
                    + Add Rule
                </button>
            </div>
            <div id="rules-container" class="space-y-3">
                <!-- Rules will be added dynamically -->
                <p class="text-sm text-gray-500">No rules added yet. Click "Add Rule" to create rules.</p>
            </div>
        </div>
        
        <!-- Prompts Section -->
        <div class="space-y-4">
            <div class="flex justify-between items-center border-b border-gray-200 pb-2">
                <h4 class="text-md font-medium text-gray-900">Prompts</h4>
                <button type="button" onclick="addPrompt()" class="text-sm px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200">
                    + Add Prompt
                </button>
            </div>
            <div id="prompts-container" class="space-y-3">
                <!-- Prompts will be added dynamically -->
                <p class="text-sm text-gray-500">No prompts added yet. Click "Add Prompt" to create prompts.</p>
            </div>
        </div>
        
        <!-- Tools Section -->
        <div class="space-y-4">
            <div class="flex justify-between items-center border-b border-gray-200 pb-2">
                <h4 class="text-md font-medium text-gray-900">Tools</h4>
                <button type="button" onclick="addTool()" class="text-sm px-2 py-1 bg-purple-100 text-purple-700 rounded hover:bg-purple-200">
                    + Add Tool
                </button>
            </div>
            <div id="tools-container" class="space-y-3">
                <!-- Tools will be added dynamically -->
                <p class="text-sm text-gray-500">No tools added yet. Click "Add Tool" to create tools.</p>
            </div>
        </div>
        
        <div class="pt-4 border-t">
            <div class="flex justify-end space-x-3">
                <button type="button" onclick="closeModal()" 
                        class="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200">
                    Cancel
                </button>
                <button type="submit" 
                        class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                    Create Client
                </button>
            </div>
        </div>
    </form>
    
    <script>
    let ruleCounter = 0;
    let promptCounter = 0;
    let toolCounter = 0;
    
    // Attach form submission handler directly to this form
    document.getElementById('createClientForm').addEventListener('submit', function(event) {
        event.preventDefault();
        console.log('Form submission triggered');
        
        const form = event.target;
        const formData = new FormData(form);
        const clientData = {
            id: formData.get('id'),
            name: formData.get('name'),
            description: formData.get('description') || null,
            version: formData.get('version') || 'v1',
            active: formData.get('active') === 'on',
            rules: [],
            prompts: [],
            tools: []
        };
        
        // Process rules
        const ruleInputs = {};
        for (const [key, value] of formData.entries()) {
            if (key.startsWith('rules[')) {
                const match = key.match(/rules\\[(\\d+)\\]\\[([^\\]]+)\\]/);
                if (match) {
                    const [, index, field] = match;
                    if (!ruleInputs[index]) ruleInputs[index] = {};
                    if (field === 'data' || field === 'variables') {
                        try {
                            ruleInputs[index][field] = value ? JSON.parse(value) : (field === 'data' ? {} : null);
                        } catch (e) {
                            ruleInputs[index][field] = field === 'data' ? {} : null;
                        }
                    } else {
                        ruleInputs[index][field] = value;
                    }
                }
            }
        }
        
        for (const rule of Object.values(ruleInputs)) {
            if (rule.id) {
                clientData.rules.push({
                    id: rule.id,
                    type: rule.type || 'specialty_urgent_mapping',
                    version: rule.version || 'v1',
                    description: rule.description || null,
                    source: rule.source || null,
                    active: true,
                    data: rule.data || {}
                });
            }
        }
        
        // Process prompts
        const promptInputs = {};
        for (const [key, value] of formData.entries()) {
            if (key.startsWith('prompts[')) {
                const match = key.match(/prompts\\[(\\d+)\\]\\[([^\\]]+)\\]/);
                if (match) {
                    const [, index, field] = match;
                    if (!promptInputs[index]) promptInputs[index] = {};
                    if (field === 'variables') {
                        promptInputs[index][field] = value ? value.split(',').map(v => v.trim()).filter(v => v) : null;
                    } else {
                        promptInputs[index][field] = value;
                    }
                }
            }
        }
        
        for (const prompt of Object.values(promptInputs)) {
            if (prompt.id && prompt.content) {
                clientData.prompts.push({
                    id: prompt.id,
                    version: prompt.version || 'v1',
                    role: prompt.role || 'system',
                    content: prompt.content,
                    variables: prompt.variables,
                    locale: prompt.locale || 'en-US',
                    active: true
                });
            }
        }
        
        // Process tools
        const toolInputs = {};
        for (const [key, value] of formData.entries()) {
            if (key.startsWith('tools[')) {
                const match = key.match(/tools\\[(\\d+)\\]\\[([^\\]]+)\\]/);
                if (match) {
                    const [, index, field] = match;
                    if (!toolInputs[index]) toolInputs[index] = {};
                    if (field === 'enabled') {
                        toolInputs[index][field] = value === 'on';
                    } else if (field === 'config') {
                        try {
                            toolInputs[index][field] = value ? JSON.parse(value) : {};
                        } catch (e) {
                            toolInputs[index][field] = {};
                        }
                    } else {
                        toolInputs[index][field] = value;
                    }
                }
            }
        }
        
        for (const tool of Object.values(toolInputs)) {
            if (tool.name) {
                clientData.tools.push({
                    name: tool.name,
                    description: tool.description || null,
                    enabled: tool.enabled !== false,
                    config: tool.config || {}
                });
            }
        }
        
        console.log('Submitting client data:', clientData);
        
        fetch('/api/admin/clients', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(clientData)
        }).then(response => {
            if (response.ok) {
                alert('Client created successfully!');
                if (window.closeModal) window.closeModal();
                if (window.htmx) {
                    window.htmx.trigger('#clients-container', 'load');
                }
                if (window.updateClientCount) window.updateClientCount();
            } else {
                return response.json().then(err => {
                    throw new Error(err.detail || 'Unknown error');
                });
            }
        }).catch((error) => {
            console.error('Error:', error);
            alert('Error creating client: ' + error.message);
        });
    });
    
    function addRule() {
        const container = document.getElementById('rules-container');
        if (container.children.length === 1 && container.children[0].tagName === 'P') {
            container.innerHTML = '';
        }
        
        const ruleDiv = document.createElement('div');
        ruleDiv.className = 'border border-gray-200 rounded p-3 bg-blue-50';
        ruleDiv.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <h5 class="text-sm font-medium">Rule ${ruleCounter + 1}</h5>
                <button type="button" onclick="this.parentElement.parentElement.remove()" 
                        class="text-red-600 hover:text-red-800 text-sm">✕</button>
            </div>
            <div class="grid grid-cols-2 gap-3 mb-2">
                <input type="text" name="rules[${ruleCounter}][id]" placeholder="Rule ID (e.g., urgent_mapping_v1)" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <select name="rules[${ruleCounter}][type]" class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                        <option value="specialty_urgent_mapping">Specialty Urgent Mapping (Active)</option>
                        <option value="triage_rules" disabled>Triage Rules (Future)</option>
                        <option value="custom" disabled>Custom (Future)</option>
                    </select>
            </div>
            <div class="grid grid-cols-2 gap-3 mb-2">
                <input type="text" name="rules[${ruleCounter}][version]" value="v1" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded" placeholder="Version">
                <input type="text" name="rules[${ruleCounter}][source]" placeholder="Source (e.g., mapping_rules.json)" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
            </div>
            <textarea name="rules[${ruleCounter}][description]" rows="2" placeholder="Rule description..." 
                      class="w-full px-2 py-1 text-sm border border-gray-300 rounded mb-2"></textarea>
            <textarea name="rules[${ruleCounter}][data]" rows="4" placeholder="Rule data (JSON format)..." 
                      class="w-full px-2 py-1 text-sm border border-gray-300 rounded font-mono"></textarea>
        `;
        container.appendChild(ruleDiv);
        ruleCounter++;
    }
    
    function addPrompt() {
        const container = document.getElementById('prompts-container');
        if (container.children.length === 1 && container.children[0].tagName === 'P') {
            container.innerHTML = '';
        }
        
        const promptDiv = document.createElement('div');
        promptDiv.className = 'border border-gray-200 rounded p-3 bg-green-50';
        promptDiv.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <h5 class="text-sm font-medium">Prompt ${promptCounter + 1}</h5>
                <button type="button" onclick="this.parentElement.parentElement.remove()" 
                        class="text-red-600 hover:text-red-800 text-sm">✕</button>
            </div>
            <div class="grid grid-cols-3 gap-3 mb-2">
                <input type="text" name="prompts[${promptCounter}][id]" placeholder="Prompt ID (e.g., system_v1)" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                <select name="prompts[${promptCounter}][role]" class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <option value="system">System</option>
                    <option value="user_template">User Template</option>
                    <option value="assistant">Assistant</option>
                </select>
                <input type="text" name="prompts[${promptCounter}][version]" value="v1" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded" placeholder="Version">
            </div>
            <div class="grid grid-cols-2 gap-3 mb-2">
                <input type="text" name="prompts[${promptCounter}][locale]" value="en-US" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded" placeholder="Locale">
                <input type="text" name="prompts[${promptCounter}][variables]" 
                       placeholder="Variables (comma-separated)" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
            </div>
            <textarea name="prompts[${promptCounter}][content]" rows="4" placeholder="Prompt content..." 
                      class="w-full px-2 py-1 text-sm border border-gray-300 rounded"></textarea>
        `;
        container.appendChild(promptDiv);
        promptCounter++;
    }
    
    function addTool() {
        const container = document.getElementById('tools-container');
        if (container.children.length === 1 && container.children[0].tagName === 'P') {
            container.innerHTML = '';
        }
        
        const toolDiv = document.createElement('div');
        toolDiv.className = 'border border-gray-200 rounded p-3 bg-purple-50';
        toolDiv.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <h5 class="text-sm font-medium">Tool ${toolCounter + 1}</h5>
                <button type="button" onclick="this.parentElement.parentElement.remove()" 
                        class="text-red-600 hover:text-red-800 text-sm">✕</button>
            </div>
            <div class="grid grid-cols-2 gap-3 mb-2">
                <input type="text" name="tools[${toolCounter}][name]" placeholder="Tool name (e.g., validate_insurance)" 
                       class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                <div class="flex items-center">
                    <input type="checkbox" name="tools[${toolCounter}][enabled]" checked 
                           class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                    <label class="ml-2 block text-sm text-gray-900">Enabled</label>
                </div>
            </div>
            <textarea name="tools[${toolCounter}][description]" rows="2" placeholder="Tool description..." 
                      class="w-full px-2 py-1 text-sm border border-gray-300 rounded mb-2"></textarea>
            <textarea name="tools[${toolCounter}][config]" rows="3" placeholder="Tool configuration (JSON format)..." 
                      class="w-full px-2 py-1 text-sm border border-gray-300 rounded font-mono"></textarea>
        `;
        container.appendChild(toolDiv);
        toolCounter++;
    }
    </script>
    """)


@app.get("/ui/admin/clients/{client_id}/edit-form", tags=["Web UI"])
async def edit_client_form_endpoint(client_id: str):
    """Get edit client form for admin UI."""
    try:
        client_config: ClientConfig = app.state.client_config
        client = next((c for c in client_config.clients if c.id == client_id), None)
        
        if not client:
            return HTMLResponse("<div class='text-red-500'>Client not found</div>")
        
        # Format existing rules
        rules_html = ""
        for i, rule in enumerate(client.rules):
            data_str = json.dumps(rule.data, indent=2) if rule.data else ""
            rules_html += f"""
            <div class="border border-gray-200 rounded p-3 bg-blue-50">
                <div class="flex justify-between items-start mb-2">
                    <h5 class="text-sm font-medium">Rule {i + 1}</h5>
                    <button type="button" onclick="this.parentElement.parentElement.remove()" 
                            class="text-red-600 hover:text-red-800 text-sm">✕</button>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="rules[{i}][id]" value="{rule.id}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <select name="rules[{i}][type]" class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                        <option value="specialty_urgent_mapping" {'selected' if rule.type == 'specialty_urgent_mapping' else ''}>Specialty Urgent Mapping (Active)</option>
                        <option value="triage_rules" {'selected' if rule.type == 'triage_rules' else ''} disabled>Triage Rules (Future)</option>
                        <option value="custom" {'selected' if rule.type == 'custom' else ''} disabled>Custom (Future)</option>
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="rules[{i}][version]" value="{rule.version}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <input type="text" name="rules[{i}][source]" value="{rule.source or ''}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                </div>
                <textarea name="rules[{i}][description]" rows="2" 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded mb-2">{rule.description or ''}</textarea>
                <textarea name="rules[{i}][data]" rows="4" 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded font-mono">{data_str}</textarea>
            </div>
            """
        
        # Format existing prompts
        prompts_html = ""
        for i, prompt in enumerate(client.prompts):
            variables_str = ','.join(prompt.variables) if prompt.variables else ""
            prompts_html += f"""
            <div class="border border-gray-200 rounded p-3 bg-green-50">
                <div class="flex justify-between items-start mb-2">
                    <h5 class="text-sm font-medium">Prompt {i + 1}</h5>
                    <button type="button" onclick="this.parentElement.parentElement.remove()" 
                            class="text-red-600 hover:text-red-800 text-sm">✕</button>
                </div>
                <div class="grid grid-cols-3 gap-3 mb-2">
                    <input type="text" name="prompts[{i}][id]" value="{prompt.id}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <select name="prompts[{i}][role]" class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                        <option value="system" {'selected' if prompt.role == 'system' else ''}>System</option>
                        <option value="user_template" {'selected' if prompt.role == 'user_template' else ''}>User Template</option>
                        <option value="assistant" {'selected' if prompt.role == 'assistant' else ''}>Assistant</option>
                    </select>
                    <input type="text" name="prompts[{i}][version]" value="{prompt.version}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="prompts[{i}][locale]" value="{prompt.locale or 'en-US'}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <input type="text" name="prompts[{i}][variables]" value="{variables_str}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                </div>
                <textarea name="prompts[{i}][content]" rows="4" 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded">{prompt.content}</textarea>
            </div>
            """
        
        # Format existing tools
        tools_html = ""
        for i, tool in enumerate(client.tools):
            config_str = json.dumps(tool.config, indent=2) if tool.config else ""
            tools_html += f"""
            <div class="border border-gray-200 rounded p-3 bg-purple-50">
                <div class="flex justify-between items-start mb-2">
                    <h5 class="text-sm font-medium">Tool {i + 1}</h5>
                    <button type="button" onclick="this.parentElement.parentElement.remove()" 
                            class="text-red-600 hover:text-red-800 text-sm">✕</button>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="tools[{i}][name]" value="{tool.name}" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <div class="flex items-center">
                        <input type="checkbox" name="tools[{i}][enabled]" {'checked' if tool.enabled else ''} 
                               class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                        <label class="ml-2 block text-sm text-gray-900">Enabled</label>
                    </div>
                </div>
                <textarea name="tools[{i}][description]" rows="2" 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded mb-2">{tool.description or ''}</textarea>
                <textarea name="tools[{i}][config]" rows="3" 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded font-mono">{config_str}</textarea>
            </div>
            """
        
        return HTMLResponse(f"""
        <form id="editClientForm" class="space-y-6">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-medium">Edit Client: {client.name}</h3>
                <button type="button" onclick="closeModal()" class="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            
            <input type="hidden" name="id" value="{client.id}">
            
            <!-- Basic Info -->
            <div class="space-y-4">
                <h4 class="text-md font-medium text-gray-900 border-b border-gray-200 pb-2">Basic Information</h4>
                
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
                        <input type="text" value="{client.id}" disabled 
                               class="w-full px-3 py-2 bg-gray-100 border border-gray-300 rounded-md text-gray-500">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Client Name*</label>
                        <input type="text" name="name" value="{client.name}" required 
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                    </div>
                </div>
                
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Version</label>
                        <input type="text" name="version" value="{client.version}" 
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                    </div>
                    <div class="flex items-center pt-6">
                        <input type="checkbox" name="active" {'checked' if client.active else ''} 
                               class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                        <label class="ml-2 block text-sm text-gray-900">Active</label>
                    </div>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Description</label>
                    <textarea name="description" rows="2" 
                              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">{client.description or ''}</textarea>
                </div>
            </div>
            
            <!-- Rules Section -->
            <div class="space-y-4">
                <div class="flex justify-between items-center border-b border-gray-200 pb-2">
                    <h4 class="text-md font-medium text-gray-900">Rules</h4>
                    <button type="button" onclick="addRuleEdit()" class="text-sm px-2 py-1 bg-blue-100 text-blue-700 rounded hover:bg-blue-200">
                        + Add Rule
                    </button>
                </div>
                <div id="rules-container" class="space-y-3">
                    {rules_html if rules_html else '<p class="text-sm text-gray-500">No rules configured. Click "Add Rule" to create rules.</p>'}
                </div>
            </div>
            
            <!-- Prompts Section -->
            <div class="space-y-4">
                <div class="flex justify-between items-center border-b border-gray-200 pb-2">
                    <h4 class="text-md font-medium text-gray-900">Prompts</h4>
                    <button type="button" onclick="addPromptEdit()" class="text-sm px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200">
                        + Add Prompt
                    </button>
                </div>
                <div id="prompts-container" class="space-y-3">
                    {prompts_html if prompts_html else '<p class="text-sm text-gray-500">No prompts configured. Click "Add Prompt" to create prompts.</p>'}
                </div>
            </div>
            
            <!-- Tools Section -->
            <div class="space-y-4">
                <div class="flex justify-between items-center border-b border-gray-200 pb-2">
                    <h4 class="text-md font-medium text-gray-900">Tools</h4>
                    <button type="button" onclick="addToolEdit()" class="text-sm px-2 py-1 bg-purple-100 text-purple-700 rounded hover:bg-purple-200">
                        + Add Tool
                    </button>
                </div>
                <div id="tools-container" class="space-y-3">
                    {tools_html if tools_html else '<p class="text-sm text-gray-500">No tools configured. Click "Add Tool" to create tools.</p>'}
                </div>
            </div>
            
            <div class="text-xs text-gray-500">
                Current Version: {client.version} | Last updated: {client.updated_at[:19] if client.updated_at else 'Unknown'}
            </div>
            
            <div class="pt-4 border-t">
                <div class="flex justify-end space-x-3">
                    <button type="button" onclick="closeModal()" 
                            class="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200">
                        Cancel
                    </button>
                    <button type="submit" 
                            class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                        Update Client
                    </button>
                </div>
            </div>
        </form>
        
        <script>
        let editRuleCounter = {len(client.rules)};
        let editPromptCounter = {len(client.prompts)};
        let editToolCounter = {len(client.tools)};
        
        // Attach form submission handler directly to this edit form
        document.getElementById('editClientForm').addEventListener('submit', function(event) {{
            event.preventDefault();
            console.log('Edit form submission triggered');
            
            const form = event.target;
            const formData = new FormData(form);
            const clientId = formData.get('id');
            const clientData = {{
                id: clientId,
                name: formData.get('name'),
                description: formData.get('description') || null,
                version: formData.get('version') || 'v1',
                active: formData.get('active') === 'on',
                rules: [],
                prompts: [],
                tools: []
            }};
            
            // Process rules (same logic as create)
            const ruleInputs = {{}};
            for (const [key, value] of formData.entries()) {{
                if (key.startsWith('rules[')) {{
                    const match = key.match(/rules\\[(\\d+)\\]\\[([^\\]]+)\\]/);
                    if (match) {{
                        const [, index, field] = match;
                        if (!ruleInputs[index]) ruleInputs[index] = {{}};
                        if (field === 'data') {{
                            try {{
                                ruleInputs[index][field] = value ? JSON.parse(value) : {{}};
                            }} catch (e) {{
                                ruleInputs[index][field] = {{}};
                            }}
                        }} else {{
                            ruleInputs[index][field] = value;
                        }}
                    }}
                }}
            }}
            
            for (const rule of Object.values(ruleInputs)) {{
                if (rule.id) {{
                    clientData.rules.push({{
                        id: rule.id,
                        type: rule.type || 'specialty_urgent_mapping',
                        version: rule.version || 'v1',
                        description: rule.description || null,
                        source: rule.source || null,
                        active: true,
                        data: rule.data || {{}}
                    }});
                }}
            }}
            
            // Process prompts
            const promptInputs = {{}};
            for (const [key, value] of formData.entries()) {{
                if (key.startsWith('prompts[')) {{
                    const match = key.match(/prompts\\[(\\d+)\\]\\[([^\\]]+)\\]/);
                    if (match) {{
                        const [, index, field] = match;
                        if (!promptInputs[index]) promptInputs[index] = {{}};
                        if (field === 'variables') {{
                            promptInputs[index][field] = value ? value.split(',').map(v => v.trim()).filter(v => v) : null;
                        }} else {{
                            promptInputs[index][field] = value;
                        }}
                    }}
                }}
            }}
            
            for (const prompt of Object.values(promptInputs)) {{
                if (prompt.id && prompt.content) {{
                    clientData.prompts.push({{
                        id: prompt.id,
                        version: prompt.version || 'v1',
                        role: prompt.role || 'system',
                        content: prompt.content,
                        variables: prompt.variables,
                        locale: prompt.locale || 'en-US',
                        active: true
                    }});
                }}
            }}
            
            // Process tools
            const toolInputs = {{}};
            for (const [key, value] of formData.entries()) {{
                if (key.startsWith('tools[')) {{
                    const match = key.match(/tools\\[(\\d+)\\]\\[([^\\]]+)\\]/);
                    if (match) {{
                        const [, index, field] = match;
                        if (!toolInputs[index]) toolInputs[index] = {{}};
                        if (field === 'enabled') {{
                            toolInputs[index][field] = value === 'on';
                        }} else if (field === 'config') {{
                            try {{
                                toolInputs[index][field] = value ? JSON.parse(value) : {{}};
                            }} catch (e) {{
                                toolInputs[index][field] = {{}};
                            }}
                        }} else {{
                            toolInputs[index][field] = value;
                        }}
                    }}
                }}
            }}
            
            for (const tool of Object.values(toolInputs)) {{
                if (tool.name) {{
                    clientData.tools.push({{
                        name: tool.name,
                        description: tool.description || null,
                        enabled: tool.enabled !== false,
                        config: tool.config || {{}}
                    }});
                }}
            }}
            
            console.log('Updating client data:', clientData);
            
            fetch(`/api/admin/clients/${{clientId}}`, {{
                method: 'PUT',
                headers: {{
                    'Content-Type': 'application/json',
                }},
                body: JSON.stringify(clientData)
            }}).then(response => {{
                if (response.ok) {{
                    alert('Client updated successfully!');
                    if (window.closeModal) window.closeModal();
                    if (window.htmx) {{
                        window.htmx.trigger('#clients-container', 'load');
                    }}
                }} else {{
                    return response.json().then(err => {{
                        throw new Error(err.detail || 'Unknown error');
                    }});
                }}
            }}).catch((error) => {{
                console.error('Error:', error);
                alert('Error updating client: ' + error.message);
            }});
        }});
        
        function addRuleEdit() {{
            // Same as addRule but with edit counter
            const container = document.getElementById('rules-container');
            if (container.children.length === 1 && container.children[0].tagName === 'P') {{
                container.innerHTML = '';
            }}
            
            const ruleDiv = document.createElement('div');
            ruleDiv.className = 'border border-gray-200 rounded p-3 bg-blue-50';
            ruleDiv.innerHTML = `
                <div class="flex justify-between items-start mb-2">
                    <h5 class="text-sm font-medium">Rule ${{editRuleCounter + 1}}</h5>
                    <button type="button" onclick="this.parentElement.parentElement.remove()" 
                            class="text-red-600 hover:text-red-800 text-sm">✕</button>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="rules[${{editRuleCounter}}][id]" placeholder="Rule ID" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <select name="rules[${{editRuleCounter}}][type]" class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                        <option value="specialty_urgent_mapping">Specialty Urgent Mapping (Active)</option>
                        <option value="triage_rules" disabled>Triage Rules (Future)</option>
                        <option value="custom" disabled>Custom (Future)</option>
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="rules[${{editRuleCounter}}][version]" value="v1" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <input type="text" name="rules[${{editRuleCounter}}][source]" placeholder="Source" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                </div>
                <textarea name="rules[${{editRuleCounter}}][description]" rows="2" placeholder="Rule description..." 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded mb-2"></textarea>
                <textarea name="rules[${{editRuleCounter}}][data]" rows="4" placeholder="Rule data (JSON format)..." 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded font-mono"></textarea>
            `;
            container.appendChild(ruleDiv);
            editRuleCounter++;
        }}
        
        function addPromptEdit() {{
            const container = document.getElementById('prompts-container');
            if (container.children.length === 1 && container.children[0].tagName === 'P') {{
                container.innerHTML = '';
            }}
            
            const promptDiv = document.createElement('div');
            promptDiv.className = 'border border-gray-200 rounded p-3 bg-green-50';
            promptDiv.innerHTML = `
                <div class="flex justify-between items-start mb-2">
                    <h5 class="text-sm font-medium">Prompt ${{editPromptCounter + 1}}</h5>
                    <button type="button" onclick="this.parentElement.parentElement.remove()" 
                            class="text-red-600 hover:text-red-800 text-sm">✕</button>
                </div>
                <div class="grid grid-cols-3 gap-3 mb-2">
                    <input type="text" name="prompts[${{editPromptCounter}}][id]" placeholder="Prompt ID" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <select name="prompts[${{editPromptCounter}}][role]" class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                        <option value="system">System</option>
                        <option value="user_template">User Template</option>
                        <option value="assistant">Assistant</option>
                    </select>
                    <input type="text" name="prompts[${{editPromptCounter}}][version]" value="v1" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="prompts[${{editPromptCounter}}][locale]" value="en-US" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <input type="text" name="prompts[${{editPromptCounter}}][variables]" 
                           placeholder="Variables (comma-separated)" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                </div>
                <textarea name="prompts[${{editPromptCounter}}][content]" rows="4" placeholder="Prompt content..." 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded"></textarea>
            `;
            container.appendChild(promptDiv);
            editPromptCounter++;
        }}
        
        function addToolEdit() {{
            const container = document.getElementById('tools-container');
            if (container.children.length === 1 && container.children[0].tagName === 'P') {{
                container.innerHTML = '';
            }}
            
            const toolDiv = document.createElement('div');
            toolDiv.className = 'border border-gray-200 rounded p-3 bg-purple-50';
            toolDiv.innerHTML = `
                <div class="flex justify-between items-start mb-2">
                    <h5 class="text-sm font-medium">Tool ${{editToolCounter + 1}}</h5>
                    <button type="button" onclick="this.parentElement.parentElement.remove()" 
                            class="text-red-600 hover:text-red-800 text-sm">✕</button>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-2">
                    <input type="text" name="tools[${{editToolCounter}}][name]" placeholder="Tool name" 
                           class="w-full px-2 py-1 text-sm border border-gray-300 rounded">
                    <div class="flex items-center">
                        <input type="checkbox" name="tools[${{editToolCounter}}][enabled]" checked 
                               class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                        <label class="ml-2 block text-sm text-gray-900">Enabled</label>
                    </div>
                </div>
                <textarea name="tools[${{editToolCounter}}][description]" rows="2" placeholder="Tool description..." 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded mb-2"></textarea>
                <textarea name="tools[${{editToolCounter}}][config]" rows="3" placeholder="Tool configuration (JSON format)..." 
                          class="w-full px-2 py-1 text-sm border border-gray-300 rounded font-mono"></textarea>
            `;
            container.appendChild(toolDiv);
            editToolCounter++;
        }}
        </script>
        """)
        
    except Exception as e:
        return HTMLResponse(f"<div class='text-red-500'>Error loading edit form: {e}</div>")


if __name__ == "__main__":
    # Using the string import path enables auto-reload to work correctly.
    uvicorn.run("main:app", host=HOST, port=PORT, reload=RELOAD)
