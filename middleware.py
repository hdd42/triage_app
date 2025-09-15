"""
Middleware for automatic request logging and timing.
"""

import time
import json
import logging
from typing import Callable, Optional, Dict, Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from logging_service import request_logger

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically log all requests with timing and metadata."""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Start timing
        start_time = time.perf_counter()
        
        # Extract request metadata
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent")
        method = request.method
        path = str(request.url.path)
        
        # Get request size
        request_size = None
        if hasattr(request, 'body'):
            try:
                body = await request.body()
                request_size = len(body) if body else 0
            except:
                request_size = 0
        
        # Store request data for use in logging
        request.state.start_time = start_time
        request.state.client_ip = client_ip
        request.state.user_agent = user_agent
        request.state.request_size = request_size
        
        # Process the request
        response = await call_next(request)
        
        # Calculate response time
        end_time = time.perf_counter()
        response_time_ms = (end_time - start_time) * 1000
        
        # Get response size
        response_size = None
        if hasattr(response, 'body'):
            response_size = len(response.body) if response.body else 0
        
        # Determine success
        success = 200 <= response.status_code < 400
        
        # Log the request asynchronously (don't block response)
        try:
            await request_logger.log_request(
                method=method,
                path=path,
                status_code=response.status_code,
                response_time_ms=response_time_ms,
                client_ip=client_ip,
                user_agent=user_agent,
                request_size=request_size,
                response_size=response_size,
                success=success
            )
        except Exception as e:
            logger.error(f"Failed to log request: {e}")
        
        # Add performance headers
        response.headers["X-Response-Time"] = f"{response_time_ms:.2f}ms"
        response.headers["X-Request-ID"] = getattr(request.state, 'request_id', 'unknown')
        
        return response
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP from request headers."""
        # Check common headers for client IP
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        
        # Fallback to client from request
        if request.client:
            return request.client.host
        
        return None
    


def setup_logging_config():
    """Setup logging configuration for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )
    
    # Set specific log levels
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # Reduce uvicorn noise
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("triage").setLevel(logging.INFO)
    logging.getLogger("main").setLevel(logging.INFO)