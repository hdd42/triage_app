"""
Logging service for storing request logs in SQLite database.
"""

from __future__ import annotations

import time
import json
from datetime import datetime
from typing import Optional, Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from models import RequestLog
from db import get_session

logger = logging.getLogger(__name__)


class RequestLogger:
    """Service for logging API requests to database."""
    
    def __init__(self):
        self._log_cache = []  # For batching logs if needed
    
    async def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        response_time_ms: float,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_size: Optional[int] = None,
        response_size: Optional[int] = None,
        success: bool = True,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log a request to the database.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (/triage, /clients, etc.)
            status_code: HTTP response status code
            response_time_ms: Total request processing time in milliseconds
            client_ip: Client IP address
            user_agent: User agent string
            request_size: Size of request body in bytes
            response_size: Size of response body in bytes
            success: Whether the request was successful
            error_type: Type of error if request failed
            error_message: Error message if request failed
            metadata: Additional metadata as JSON
        """
        try:
            async for session in get_session():
                request_log = RequestLog(
                    method=method,
                    path=path,
                    client_ip=client_ip,
                    user_agent=user_agent[:500] if user_agent else None,  # Truncate long user agents
                    request_size=request_size,
                    status_code=status_code,
                    response_size=response_size,
                    response_time_ms=response_time_ms,
                    error_type=error_type,
                    error_message=error_message[:1000] if error_message else None,  # Truncate long errors
                    request_metadata=metadata,
                    success=success,
                )
                
                session.add(request_log)
                await session.commit()
                break  # Exit the async generator loop
                
        except Exception as e:
            logger.error(f"Failed to log request to database: {e}")
            # Don't raise the exception - logging failures shouldn't break the API
    
    async def get_request_stats(
        self,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get request statistics for the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Dictionary with request statistics
        """
        try:
            from sqlalchemy import select, func
            from datetime import datetime, timedelta
            
            async for session in get_session():
                # Calculate time threshold
                since = datetime.utcnow() - timedelta(hours=hours)
                
                # Basic request counts
                total_requests = await session.execute(
                    select(func.count(RequestLog.id)).where(RequestLog.request_time >= since)
                )
                total_count = total_requests.scalar()
                
                # Success rate
                successful_requests = await session.execute(
                    select(func.count(RequestLog.id)).where(
                        RequestLog.request_time >= since,
                        RequestLog.success == True
                    )
                )
                success_count = successful_requests.scalar()
                
                # Average response time
                avg_response_time = await session.execute(
                    select(func.avg(RequestLog.response_time_ms)).where(
                        RequestLog.request_time >= since,
                        RequestLog.response_time_ms.isnot(None)
                    )
                )
                avg_time = avg_response_time.scalar()
                
                # Triage-specific stats
                triage_requests = await session.execute(
                    select(func.count(RequestLog.id)).where(
                        RequestLog.request_time >= since,
                        RequestLog.path == '/triage'
                    )
                )
                triage_count = triage_requests.scalar()
                
                # Error breakdown
                error_stats = await session.execute(
                    select(RequestLog.error_type, func.count(RequestLog.id))
                    .where(
                        RequestLog.request_time >= since,
                        RequestLog.success == False
                    )
                    .group_by(RequestLog.error_type)
                )
                error_breakdown = dict(error_stats.fetchall())
                
                return {
                    'time_period_hours': hours,
                    'total_requests': total_count or 0,
                    'successful_requests': success_count or 0,
                    'success_rate': (success_count / total_count * 100) if total_count > 0 else 0,
                    'average_response_time_ms': round(avg_time, 2) if avg_time else 0,
                    'triage_requests': triage_count or 0,
                    'error_breakdown': error_breakdown,
                }
                
        except Exception as e:
            logger.error(f"Failed to get request stats: {e}")
            return {
                'error': 'Failed to retrieve stats',
                'time_period_hours': hours,
            }


# Global instance
request_logger = RequestLogger()


class TriageTimer:
    """Context manager for timing triage operations."""
    
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None
        self.end_time = None
        
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        
    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


def format_timing_log(
    operation: str, 
    elapsed_ms: float, 
    extra_data: Optional[Dict[str, Any]] = None
) -> str:
    """Format a timing log message."""
    base_msg = f"⏱️  {operation}: {elapsed_ms:.2f}ms"
    if extra_data:
        extra_str = ", ".join(f"{k}={v}" for k, v in extra_data.items())
        return f"{base_msg} ({extra_str})"
    return base_msg