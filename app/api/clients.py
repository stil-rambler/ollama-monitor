"""
Clients API endpoints for Ollama Monitor
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import Client, Request, get_db
from app.schemas import Client as ClientSchema

router = APIRouter(prefix="/clients", tags=["clients"])

@router.get("/", response_model=List[ClientSchema])
async def get_clients(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("total_requests", alias="sort"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of clients with optional sorting
    """
    try:
        # Build the query
        query = select(Client).order_by(asc(sort_by) if sort_order == "asc" else desc(sort_by))
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute the query
        result = await db.execute(query)
        clients = result.scalars().all()
        
        return clients
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving clients: {str(e)}")

@router.get("/{client_ip}", response_model=ClientSchema)
async def get_client(client_ip: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific client by IP address
    """
    try:
        query = select(Client).where(Client.client_ip == client_ip)
        
        result = await db.execute(query)
        client = result.scalar_one_or_none()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
            
        return client
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving client: {str(e)}")

@router.get("/{client_ip}/statistics", response_model=dict)
async def get_client_statistics(client_ip: str, db: AsyncSession = Depends(get_db)):
    """
    Get detailed statistics for a specific client
    """
    try:
        # Get the client
        query = select(Client).where(Client.client_ip == client_ip)
        result = await db.execute(query)
        client = result.scalar_one_or_none()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Get statistics for the client
        # Filter requests by client IP
        query = select(Request).where(Request.client_ip == client_ip)
        
        result = await db.execute(query)
        requests = result.scalars().all()
        
        if not requests:
            return {
                "client_ip": client_ip,
                "total_requests": 0,
                "average_response_time": 0.0,
                "total_request_duration": 0,
                "average_response_time": 0.0,
                "used_models": [],
                "request_count_by_model": {},
                "last_active": None
            }
        
        # Calculate statistics
        total_requests = len(requests)
        total_request_duration = sum(r.total_duration or 0 for r in requests if r.total_duration is not None)
        average_response_time = total_request_duration / total_requests if total_requests > 0 else 0.0
        
        # Get used models and count by model
        used_models = set()
        request_count_by_model = {}
        for request in requests:
            if request.model_name:
                used_models.add(request.model_name)
                if request.model_name not in request_count_by_model:
                    request_count_by_model[request.model_name] = 0
                request_count_by_model[request.model_name] += 1
        
        # Find last active time
        last_active = max(r.created_at for r in requests) if requests else None
        
        return {
            "client_ip": client_ip,
            "total_requests": total_requests,
            "average_response_time": round(average_response_time / 1000, 1),  # Convert to seconds
            "total_request_duration": total_request_duration,
            "used_models": sorted(list(used_models)),
            "request_count_by_model": request_count_by_model,
            "last_active": last_active.isoformat() if last_active else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving client statistics: {str(e)}")

@router.get("/{client_ip}/sessions", response_model=dict)
async def get_client_sessions(
    client_ip: str,
    session_id: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Get client sessions
    """
    try:
        # Get the client
        query = select(Client).where(Client.client_ip == client_ip)
        result = await db.execute(query)
        client = result.scalar_one_or_none()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Get requests for this client with session information
        query = select(Request).where(
            Request.client_ip == client_ip
        )
        
        if session_id:
            query = query.where(Request.id == session_id)
        
        if start_time:
            query = query.where(Request.created_at >= start_time)
        if end_time:
            query = query.where(Request.created_at <= end_time)
        
        result = await db.execute(query)
        requests = result.scalars().all()
        
        if not requests:
            return {
                "client_ip": client_ip,
                "sessions": [],
                "total_sessions": 0
            }
        
        # Group requests into sessions
        # We'll use the X-Ollama-Monitor-Session header to identify sessions
        # If not present, we'll group requests that are close in time
        sessions = {}
        
        for request in requests:
            session_id = request.id
            
            if request.id:
                # Use the request ID as session ID
                session_id = request.id
                
            if session_id not in sessions:
                sessions[session_id] = {
                    "id": session_id,
                    "start_time": request.created_at,
                    "end_time": request.created_at,
                    "requests": [],
                    "used_models": set(),
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_duration": 0,
                    "error_count": 0
                }
            
            sessions[session_id]["end_time"] = request.created_at
            sessions[session_id]["requests"].append(request.to_dict())
            if request.model_name:
                sessions[session_id]["used_models"].add(request.model_name)
            if request.total_tokens:
                sessions[session_id]["total_input_tokens"] += request.total_tokens
            if request.output_tokens:
                sessions[session_id]["total_output_tokens"] += request.output_tokens
            if request.total_duration:
                sessions[session_id]["total_duration"] += request.total_duration
            if request.execution_status == "ERROR":
                sessions[session_id]["error_count"] += 1
        
        # Convert sessions to list and sort by start time
        sessions_list = list(sessions.values())
        sessions_list.sort(key=lambda s: s["start_time"])
        
        # Return sessions
        return {
            "client_ip": client_ip,
            "sessions": sessions_list,
            "total_sessions": len(sessions_list)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving client sessions: {str(e)}")

@router.get("/{client_ip}/performance", response_model=dict)
async def get_client_performance(client_ip: str, db: AsyncSession = Depends(get_db)):
    """
    Get client performance analysis
    """
    try:
        # Get the client
        query = select(Client).where(Client.client_ip == client_ip)
        result = await db.execute(query)
        client = result.scalar_one_or_none()
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Get all requests for this client
        query = select(Request).where(Request.client_ip == client_ip)
        result = await db.execute(query)
        requests = result.scalars().all()
        
        if not requests:
            return {
                "client_ip": client_ip,
                "performance_analysis": [],
                "summary": "No requests found for this client"
            }
        
        # Calculate performance metrics
        total_requests = len(requests)
        total_input_tokens = sum(r.total_tokens or 0 for r in requests if r.total_tokens is not None)
        total_output_tokens = sum(r.output_tokens or 0 for r in requests if r.output_tokens is not None)
        
        # Calculate average response time (in seconds)
        total_response_time = sum(r.total_duration or 0 for r in requests if r.total_duration is not None)
        average_response_time = total_response_time / total_requests if total_requests > 0 else 0.0
        
        # Calculate average generation speed (tokens per second)
        total_generation_time = sum(
            r.eval_duration / 1_000_000_000 
            for r in requests 
            if r.eval_count and r.eval_duration and r.eval_duration > 0
        )
        total_generation_tokens = sum(
            r.eval_count 
            for r in requests 
            if r.eval_count is not None
        )
        average_generation_speed = total_generation_tokens / total_generation_time if total_generation_time > 0 else 0.0
        
        # Calculate average prompt processing speed (tokens per second)
        total_prompt_processing_time = sum(
            r.prompt_eval_duration / 1_000_000_000 
            for r in requests 
            if r.prompt_eval_count and r.prompt_eval_duration and r.prompt_eval_duration > 0
        )
        total_prompt_tokens = sum(
            r.prompt_eval_count 
            for r in requests 
            if r.prompt_eval_count is not None
        )
        average_prompt_processing_speed = total_prompt_tokens / total_prompt_processing_time if total_prompt_processing_time > 0 else 0.0
        
        # Calculate error rate
        error_count = sum(1 for r in requests if r.execution_status == "ERROR")
        error_rate = (error_count / total_requests) * 100 if total_requests > 0 else 0.0
        
        # Calculate performance by model
        performance_by_model = {}
        for request in requests:
            if request.model_name:
                if request.model_name not in performance_by_model:
                    performance_by_model[request.model_name] = {
                        "request_count": 0,
                        "total_input_tokens": 0,
                        "total_output_tokens": 0,
                        "total_duration": 0,
                        "avg_generation_speed": 0.0
                    }
                
                performance_by_model[request.model_name]["request_count"] += 1
                if request.total_tokens:
                    performance_by_model[request.model_name]["total_input_tokens"] += request.total_tokens
                if request.output_tokens:
                    performance_by_model[request.model_name]["total_output_tokens"] += request.output_tokens
                if request.total_duration:
                    performance_by_model[request.model_name]["total_duration"] += request.total_duration
                
                # Calculate average generation speed for this model
                if request.eval_count and request.eval_duration and request.eval_duration > 0:
                    generation_speed = request.eval_count / (request.eval_duration / 1_000_000_000)
                    performance_by_model[request.model_name]["avg_generation_speed"] = (
                        (performance_by_model[request.model_name]["avg_generation_speed"] * 
                         (performance_by_model[request.model_name]["request_count"] - 1) + generation_speed) / 
                        performance_by_model[request.model_name]["request_count"]
                    )
        
        # Sort performance by model by request count
        sorted_performance_by_model = sorted(
            performance_by_model.items(),
            key=lambda x: x[1]["request_count"],
            reverse=True
        )
        
        # Return performance analysis
        return {
            "client_ip": client_ip,
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "average_response_time": round(average_response_time / 1000, 1),  # Convert to seconds
            "average_generation_speed": round(average_generation_speed, 1),
            "average_prompt_processing_speed": round(average_prompt_processing_speed, 1),
            "error_rate": round(error_rate, 1),
            "performance_by_model": sorted_performance_by_model,
            "summary": f"Analyzed {total_requests} requests from client {client_ip}"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving client performance: {str(e)}")