"""
Request parser and validator for Ollama Monitor proxy
"""

import json
import re
from typing import Dict, Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, validator

from app.config import Config
from app.database import Request, Model, Client, GpuMetric
from app.services.request_tracker import RequestTracker

class RequestValidator(BaseModel):
    """
    Validation model for incoming requests to the proxy
    """
    # Basic request information
    method: str = Field(..., description="HTTP method")
    path: str = Field(..., description="Request path")
    headers: Dict[str, str] = Field(..., description="Request headers")
    body: Optional[Dict[str, Any]] = Field(None, description="Request body")
    query_params: Dict[str, str] = Field({}, description="Query parameters")
    
    # Request content information
    content_type: Optional[str] = Field(None, description="Content-Type header")
    content_length: Optional[int] = Field(None, description="Content-Length header")
    
    # Validation constraints
    @validator('method')
    def validate_method(cls, v: str) -> str:
        """Validate that the HTTP method is one of the allowed methods"""
        allowed_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']
        if v.upper() not in allowed_methods:
            raise ValueError(f"Method must be one of {allowed_methods}")
        return v.upper()
    
    @validator('path')
    def validate_path(cls, v: str) -> str:
        """Validate that the path is a valid Ollama API path"""
        # Check for valid Ollama API paths
        valid_paths = [
            '/api/generate', '/api/chat', '/api/embed', '/api/embeddings',
            '/api/tags', '/api/ps', '/api/show', '/api/pull',
            '/api/push', '/api/create', '/api/delete', '/api/copy',
            '/api/version'
        ]
        if v not in valid_paths:
            raise ValueError(f"Path must be one of {valid_paths}")
        return v
    
    @validator('content_type')
    def validate_content_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate that the Content-Type is acceptable"""
        if v is None:
            return v
        if not v.startswith('application/json') and not v.startswith('text/event-stream'):
            raise ValueError("Content-Type must be application/json or text/event-stream")
        return v
    
    @validator('content_length')
    def validate_content_length(cls, v: Optional[int]) -> Optional[int]:
        """Validate that the Content-Length is reasonable"""
        # Ollama doesn't use extremely large request bodies, so we'll limit to 100KB
        if v is not None and v > 102400:
            raise ValueError("Content-Length too large (max 100KB)")
        return v

def validate_request(request: RequestValidator) -> bool:
    """
    Validate an incoming request
    """
    try:
        # Validate the request as a Pydantic model
        request_validator = RequestValidator(**request.model_dump())
        
        # Additional validation based on path
        if request_validator.path == '/api/generate' or request_validator.path == '/api/chat':
            # These endpoints require a 'model' field in the body
            if request_validator.body is None or 'model' not in request_validator.body:
                raise HTTPException(status_code=400, detail="Missing 'model' field in request body")
                
            # Check if the model exists in the database
            # This is a placeholder - in a real implementation, we would check
            # the actual Ollama server or database
            pass
            
        # Check for potentially dangerous headers
        for header in request_validator.headers:
            if header.lower() in ['x-forwarded-for', 'x-real-ip', 'x-remote-addr', 'x-remote-ip']:
                # These headers could be used for spoofing
                # Only allow them if they're trusted
                pass
                
        return True
        
    except Exception as e:
        # Log the validation error
        logger.error(f"Request validation failed: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

def parse_request_body(body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse and sanitize the request body for safety
    """
    if body is None:
        return {}
        
    # Remove any potentially dangerous fields
    sanitized_body = {}
    for key, value in body.items():
        # Skip any fields that might be used for SSRF or other attacks
        if key.lower() in ['url', 'uri', 'location', 'path', 'host', 'target', 'destination']:
            continue
            
        # Keep the field if it's not dangerous
        sanitized_body[key] = value
        
    return sanitized_body