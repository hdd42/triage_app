from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, JSON, func

from db import Base


class RequestLog(Base):
    """Model for logging API requests and responses."""
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Request metadata
    method = Column(String(10), nullable=False)  # GET, POST, etc.
    path = Column(String(255), nullable=False, index=True)  # /triage, /clients, etc.
    client_ip = Column(String(45), nullable=True)  # IPv4/IPv6 support
    user_agent = Column(Text, nullable=True)
    
    # Request data
    request_size = Column(Integer, nullable=True)  # Size of request body in bytes
    
    # Response data
    status_code = Column(Integer, nullable=False, index=True)
    response_size = Column(Integer, nullable=True)  # Size of response body in bytes
    
    # Timing data
    request_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    response_time_ms = Column(Float, nullable=True)  # Total request processing time
    
    # Error tracking
    error_type = Column(String(50), nullable=True, index=True)  # quota_exceeded, internal_error, etc.
    error_message = Column(Text, nullable=True)
    
    # Additional metadata as JSON
    request_metadata = Column(JSON, nullable=True)
    
    # Success flag for easy filtering
    success = Column(Boolean, nullable=False, default=True, index=True)
