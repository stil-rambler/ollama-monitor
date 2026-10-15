"""
Dashboard API endpoints for Ollama Monitor
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import Request, Model, Client, GpuMetric, SystemEvent, get_db
from app.schemas import (
    Request as RequestSchema,
    Model as ModelSchema,
    Client as ClientSchema,
    GpuMetric as GpuMetricSchema,
    SystemEvent as SystemEventSchema,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/", response_model=dict)
async def get_dashboard_data(db: AsyncSession = Depends(get_db)):
    """
    Get all dashboard data including:
    - Active requests
    - Total requests today
    - Average generation speed
    - Average prompt processing speed
    - Average response time
    """
    try:
        # Get today's date
        today = datetime.now().date()
        
        # Calculate start of day
        start_of_day = datetime.combine(today, datetime.min.time())
        
        # Query for today's requests
        today_requests_query = select(Request).where(Request.created_at >= start_of_day)
        today_requests_result = await db.execute(today_requests_query)
        today_requests = today_requests_result.scalars().all()
        
        # Count total requests today
        total_requests_today = len(today_requests)
        
        # Get active requests (started but not finished)
        active_requests_query = select(Request).where(
            Request.finished_at.is_(None),
            Request.started_at.isnot(None)
        )
        active_requests_result = await db.execute(active_requests_query)
        active_requests = active_requests_result.scalars().all()
        
        # Calculate average generation speed
        # We'll filter for completed requests with generation metrics
        completed_requests_with_generation = []
        for request in today_requests:
            if request.eval_count and request.eval_duration and request.eval_duration > 0:
                generation_speed = request.eval_count / (request.eval_duration / 1_000_000_000)
                completed_requests_with_generation.append(generation_speed)
        
        average_generation_speed = (
            sum(completed_requests_with_generation) / len(completed_requests_with_generation)
            if completed_requests_with_generation
            else 0.0
        )
        
        # Calculate average prompt processing speed
        completed_requests_with_prompt = []
        for request in today_requests:
            if request.prompt_eval_count and request.prompt_eval_duration and request.prompt_eval_duration > 0:
                prompt_processing_speed = request.prompt_eval_count / (request.prompt_eval_duration / 1_000_000_000)
                completed_requests_with_prompt.append(prompt_processing_speed)
        
        average_prompt_processing_speed = (
            sum(completed_requests_with_prompt) / len(completed_requests_with_prompt)
            if completed_requests_with_prompt
            else 0.0
        )
        
        # Calculate average response time
        total_response_time = 0
        completed_requests = len(today_requests)
        for request in today_requests:
            if request.total_duration:
                total_response_time += request.total_duration
        
        average_response_time = (
            total_response_time / completed_requests
            if completed_requests > 0
            else 0.0
        )
        
        # Get system info
        system_info = await get_system_info(db)
        
        return {
            "active_requests": len(active_requests),
            "total_requests_today": total_requests_today,
            "average_generation_speed": round(average_generation_speed, 1),
            "average_prompt_processing_speed": round(average_prompt_processing_speed, 1),
            "average_response_time": round(average_response_time / 1000, 1),  # Convert to seconds
            "system_info": system_info
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving dashboard data: {str(e)}")

@router.get("/recent_requests", response_model=List[RequestSchema])
async def get_recent_requests(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """
    Get recent requests for the dashboard
    """
    try:
        query = select(Request).order_by(Request.created_at.desc()).limit(limit)
        result = await db.execute(query)
        requests = result.scalars().all()
        
        return requests
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving recent requests: {str(e)}")

@router.get("/top_models", response_model=List[ModelSchema])
async def get_top_models(limit: int = 5, db: AsyncSession = Depends(get_db)):
    """
    Get top models by total requests
    """
    try:
        query = select(Model).order_by(Model.total_requests.desc()).limit(limit)
        result = await db.execute(query)
        models = result.scalars().all()
        
        return models
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving top models: {str(e)}")

@router.get("/system_status", response_model=dict)
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """
    Get system status including GPU and CPU usage
    """
    try:
        # Get GPU status
        gpu_status = await get_gpu_status(db)
        
        # Get system info
        system_info = await get_system_info(db)
        
        return {
            "gpu_status": gpu_status,
            "system_info": system_info
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving system status: {str(e)}")

@router.get("/active_requests", response_model=List[RequestSchema])
async def get_active_requests(db: AsyncSession = Depends(get_db)):
    """
    Get list of active requests
    """
    try:
        query = select(Request).where(
            Request.finished_at.is_(None),
            Request.started_at.isnot(None)
        ).order_by(Request.started_at)
        result = await db.execute(query)
        requests = result.scalars().all()
        
        return requests
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving active requests: {str(e)}")

async def get_gpu_status(db: AsyncSession) -> dict:
    """
    Get current GPU status
    """
    try:
        # Get the most recent GPU metric for each GPU
        query = select(GpuMetric).order_by(GpuMetric.created_at.desc())
        result = await db.execute(query)
        gpu_metrics = result.scalars().all()
        
        # Group by GPU index
        gpu_status = {}
        for metric in gpu_metrics:
            if metric.gpu_index not in gpu_status:
                gpu_status[metric.gpu_index] = metric.to_dict()
            elif metric.created_at > gpu_status[metric.gpu_index]['created_at']:
                gpu_status[metric.gpu_index] = metric.to_dict()
        
        return gpu_status
        
    except Exception as e:
        # Return empty status if we can't get GPU data
        return {}

async def get_system_info(db: AsyncSession) -> dict:
    """
    Get system information
    """
    try:
        # Get the most recent system event
        query = select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(1)
        result = await db.execute(query)
        event = result.scalars().first()
        
        if event:
            # Extract system info from the event
            # This is a placeholder - in a real implementation, we would have
            # more detailed system metrics
            status = {
                "status": "online",
                "last_event": event.message,
                "source": event.source
            }
        else:
            status = {
                "status": "online",
                "last_event": "System started",
                "source": "OllamaMonitor"
            }
            
        return status
        
    except Exception as e:
        # Return default info if we can't get system data
        return {
            "status": "online",
            "last_event": "System started",
            "source": "OllamaMonitor"
        }