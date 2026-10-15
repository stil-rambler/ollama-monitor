"""
GPU API endpoints for Ollama Monitor
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import GpuMetric, get_db
from app.schemas import GpuMetric as GpuMetricSchema

router = APIRouter(prefix="/gpu", tags=["gpu"])

@router.get("/", response_model=List[GpuMetricSchema])
async def get_gpu_metrics(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    gpu_index: Optional[int] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at", alias="sort"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of GPU metrics with optional filtering
    """
    try:
        # Build the query
        query = select(GpuMetric).options(
            joinedload(GpuMetric.request)
        )
        
        # Apply filters
        if gpu_index is not None:
            query = query.where(GpuMetric.gpu_index == gpu_index)
        if start_time:
            query = query.where(GpuMetric.created_at >= start_time)
        if end_time:
            query = query.where(GpuMetric.created_at <= end_time)
        
        # Apply sorting
        sort_field = getattr(GpuMetric, sort_by, GpuMetric.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute the query
        result = await db.execute(query)
        gpu_metrics = result.scalars().all()
        
        return gpu_metrics
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving GPU metrics: {str(e)}")

@router.get("/summary", response_model=dict)
async def get_gpu_summary(db: AsyncSession = Depends(get_db)):
    """
    Get summary of all GPUs
    """
    try:
        # Get all GPU metrics
        query = select(GpuMetric).order_by(GpuMetric.created_at.desc())
        result = await db.execute(query)
        gpu_metrics = result.scalars().all()
        
        if not gpu_metrics:
            return {
                "summary": "No GPU metrics available"
            }
        
        # Get unique GPU indices
        gpu_indices = set(m.gpu_index for m in gpu_metrics)
        summary = {"total_gpus": len(gpu_indices)}
        
        # For each GPU, get the most recent metric
        for gpu_index in gpu_indices:
            # Get the most recent metric for this GPU
            query = select(GpuMetric).where(GpuMetric.gpu_index == gpu_index).order_by(GpuMetric.created_at.desc()).limit(1)
            result = await db.execute(query)
            gpu_metric = result.scalar_one_or_none()
            
            if gpu_metric:
                summary[f"gpu_{gpu_index}"] = {
                    "index": gpu_index,
                    "name": gpu_metric.gpu_name,
                    "uuid": gpu_metric.gpu_uuid,
                    "total_vram": gpu_metric.total_vram,
                    "used_vram": gpu_metric.used_vram,
                    "free_vram": gpu_metric.free_vram,
                    "gpu_load": gpu_metric.gpu_load,
                    "temperature": gpu_metric.temperature,
                    "power_usage": gpu_metric.power_usage,
                    "power_limit": gpu_metric.power_limit,
                    "created_at": gpu_metric.created_at.isoformat()
                }
        
        return summary
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving GPU summary: {str(e)}")

@router.get("/{gpu_index}", response_model=GpuMetricSchema)
async def get_gpu_metric(gpu_index: int, db: AsyncSession = Depends(get_db)):
    """
    Get the most recent GPU metric for a specific GPU
    """
    try:
        # Get the most recent metric for this GPU
        query = select(GpuMetric).where(GpuMetric.gpu_index == gpu_index).order_by(GpuMetric.created_at.desc()).limit(1)
        
        result = await db.execute(query)
        gpu_metric = result.scalar_one_or_none()
        
        if not gpu_metric:
            raise HTTPException(status_code=404, detail=f"No GPU metric found for GPU {gpu_index}")
            
        return gpu_metric
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving GPU metric: {str(e)}")

@router.get("/{gpu_index}/history", response_model=dict)
async def get_gpu_history(
    gpu_index: int,
    period: str = Query("5m", description="Time period: 5m, 1h, 24h, 7d"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get GPU history for a specific GPU with different time periods
    """
    try:
        # Get the current time
        now = datetime.utcnow()
        
        # Calculate start time based on period
        if period == "5m":
            start_time = now - timedelta(minutes=5)
        elif period == "1h":
            start_time = now - timedelta(hours=1)
        elif period == "24h":
            start_time = now - timedelta(days=1)
        elif period == "7d":
            start_time = now - timedelta(days=7)
        else:
            raise HTTPException(status_code=400, detail="Invalid period. Must be one of: 5m, 1h, 24h, 7d")
        
        # Get GPU metrics for this GPU and period
        query = select(GpuMetric).where(
            GpuMetric.gpu_index == gpu_index,
            GpuMetric.created_at >= start_time
        ).order_by(GpuMetric.created_at.asc())
        
        result = await db.execute(query)
        gpu_metrics = result.scalars().all()
        
        if not gpu_metrics:
            return {
                "gpu_index": gpu_index,
                "period": period,
                "history": []
            }
        
        # Group metrics by time interval (every 30 seconds)
        history = []
        interval_start_time = start_time
        
        # For large datasets, we'll need aggregation
        # But for now, we'll just return all metrics
        for metric in gpu_metrics:
            history.append({
                "timestamp": metric.created_at.isoformat(),
                "gpu_load": metric.gpu_load,
                "memory_load": metric.memory_load,
                "temperature": metric.temperature,
                "power_usage": metric.power_usage,
                "power_limit": metric.power_limit,
                "gpu_frequency": metric.gpu_frequency,
                "memory_frequency": metric.memory_frequency
            })
        
        return {
            "gpu_index": gpu_index,
            "period": period,
            "history": history
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving GPU history: {str(e)}")

@router.get("/{gpu_index}/aggregated", response_model=dict)
async def get_gpu_aggregated(
    gpu_index: int,
    hours: int = Query(24, description="Number of hours to aggregate data for"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get aggregated GPU metrics for a specific GPU over a specified period
    """
    try:
        # Get the end time
        end_time = datetime.utcnow()
        
        # Calculate start time
        start_time = end_time - timedelta(hours=hours)
        
        # Get GPU metrics for this GPU and period
        query = select(GpuMetric).where(
            GpuMetric.gpu_index == gpu_index,
            GpuMetric.created_at >= start_time,
            GpuMetric.created_at <= end_time
        ).order_by(GpuMetric.created_at.asc())
        
        result = await db.execute(query)
        gpu_metrics = result.scalars().all()
        
        if not gpu_metrics:
            return {
                "gpu_index": gpu_index,
                "hours": hours,
                "aggregated": []
            }
        
        # Group metrics by hour and calculate averages
        aggregated = []
        current_hour_start = start_time
        current_hour_metrics = []
        
        for metric in gpu_metrics:
            # Check if we need to start a new hour
            if metric.created_at >= (current_hour_start + timedelta(hours=1)):
                # Process the current hour
                if current_hour_metrics:
                    # Calculate averages for the current hour
                    avg_gpu_load = sum(m.gpu_load for m in current_hour_metrics) / len(current_hour_metrics)
                    avg_memory_load = sum(m.memory_load or 0 for m in current_hour_metrics if m.memory_load is not None) / len([m for m in current_hour_metrics if m.memory_load is not None])
                    avg_temperature = sum(m.temperature or 0 for m in current_hour_metrics if m.temperature is not None) / len([m for m in current_hour_metrics if m.temperature is not None])
                    avg_power_usage = sum(m.power_usage or 0 for m in current_hour_metrics if m.power_usage is not None) / len([m for m in current_hour_metrics if m.power_usage is not None])
                    avg_power_limit = sum(m.power_limit or 0 for m in current_hour_metrics if m.power_limit is not None) / len([m for m in current_hour_metrics if m.power_limit is not None])
                    avg_gpu_frequency = sum(m.gpu_frequency or 0 for m in current_hour_metrics if m.gpu_frequency is not None) / len([m for m in current_hour_metrics if m.gpu_frequency is not None])
                    avg_memory_frequency = sum(m.memory_frequency or 0 for m in current_hour_metrics if m.memory_frequency is not None) / len([m for m in current_hour_metrics if m.memory_frequency is not None])
                    
                    aggregated.append({
                        "timestamp": current_hour_start.isoformat(),
                        "avg_gpu_load": round(avg_gpu_load, 1),
                        "avg_memory_load": round(avg_memory_load, 1),
                        "avg_temperature": round(avg_temperature, 1),
                        "avg_power_usage": round(avg_power_usage, 1),
                        "avg_power_limit": round(avg_power_limit, 1),
                        "avg_gpu_frequency": round(avg_gpu_frequency, 1),
                        "avg_memory_frequency": round(avg_memory_frequency, 1)
                    })
                
                # Start a new hour
                current_hour_start = metric.created_at
                current_hour_metrics = []
            
            # Add metric to current hour
            current_hour_metrics.append(metric)
        
        # Add the last hour
        if current_hour_metrics:
            avg_gpu_load = sum(m.gpu_load for m in current_hour_metrics) / len(current_hour_metrics)
            avg_memory_load = sum(m.memory_load or 0 for m in current_hour_metrics if m.memory_load is not None) / len([m for m in current_hour_metrics if m.memory_load is not None])
            avg_temperature = sum(m.temperature or 0 for m in current_hour_metrics if m.temperature is not None) / len([m for m in current_hour_metrics if m.temperature is not None])
            avg_power_usage = sum(m.power_usage or 0 for m in current_hour_metrics if m.power_usage is not None) / len([m for m in current_hour_metrics if m.power_usage is not None])
            avg_power_limit = sum(m.power_limit or 0 for m in current_hour_metrics if m.power_limit is not None) / len([m for m in current_hour_metrics if m.power_limit is not None])
            avg_gpu_frequency = sum(m.gpu_frequency or 0 for m in current_hour_metrics if m.gpu_frequency is not None) / len([m for m in current_hour_metrics if m.gpu_frequency is not None])
            avg_memory_frequency = sum(m.memory_frequency or 0 for m in current_hour_metrics if m.memory_frequency is not None) / len([m for m in current_hour_metrics if m.memory_frequency is not None])
            
            aggregated.append({
                "timestamp": current_hour_start.isoformat(),
                "avg_gpu_load": round(avg_gpu_load, 1),
                "avg_memory_load": round(avg_memory_load, 1),
                "avg_temperature": round(avg_temperature, 1),
                "avg_power_usage": round(avg_power_usage, 1),
                "avg_power_limit": round(avg_power_limit, 1),
                "avg_gpu_frequency": round(avg_gpu_frequency, 1),
                "avg_memory_frequency": round(avg_memory_frequency, 1)
            })
        
        return {
            "gpu_index": gpu_index,
            "hours": hours,
            "aggregated": aggregated
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving GPU aggregated data: {str(e)}")

@router.get("/{gpu_index}/performance", response_model=dict)
async def get_gpu_performance(gpu_index: int, db: AsyncSession = Depends(get_db)):
    """
    Get GPU performance analysis
    """
    try:
        # Get the most recent metric for this GPU
        query = select(GpuMetric).where(GpuMetric.gpu_index == gpu_index).order_by(GpuMetric.created_at.desc()).limit(1)
        
        result = await db.execute(query)
        gpu_metric = result.scalar_one_or_none()
        
        if not gpu_metric:
            raise HTTPException(status_code=404, detail=f"No GPU metric found for GPU {gpu_index}")
        
        # Get historical metrics for performance analysis
        now = datetime.utcnow()
        start_time = now - timedelta(days=7)  # Last 7 days
        
        query = select(GpuMetric).where(
            GpuMetric.gpu_index == gpu_index,
            GpuMetric.created_at >= start_time
        ).order_by(GpuMetric.created_at.asc())
        
        result = await db.execute(query)
        gpu_metrics = result.scalars().all()
        
        if not gpu_metrics:
            return {
                "gpu_index": gpu_index,
                "performance_analysis": [],
                "summary": "No historical data available"
            }
        
        # Calculate performance metrics
        total_metrics = len(gpu_metrics)
        avg_gpu_load = sum(m.gpu_load for m in gpu_metrics) / total_metrics
        avg_temperature = sum(m.temperature or 0 for m in gpu_metrics if m.temperature is not None) / len([m for m in gpu_metrics if m.temperature is not None])
        avg_power_usage = sum(m.power_usage or 0 for m in gpu_metrics if m.power_usage is not None) / len([m for m in gpu_metrics if m.power_usage is not None])
        
        # Find maximum values
        max_gpu_load = max(m.gpu_load for m in gpu_metrics)
        max_temperature = max(m.temperature or 0 for m in gpu_metrics if m.temperature is not None)
        max_power_usage = max(m.power_usage or 0 for m in gpu_metrics if m.power_usage is not None)
        
        # Find minimum values
        min_gpu_load = min(m.gpu_load for m in gpu_metrics)
        min_temperature = min(m.temperature or 0 for m in gpu_metrics if m.temperature is not None)
        min_power_usage = min(m.power_usage or 0 for m in gpu_metrics if m.power_usage is not None)
        
        # Calculate utilization history
        total_utilization_time = 0
        total_monitoring_time = 0
        for i in range(len(gpu_metrics) - 1):
            time_diff = (gpu_metrics[i+1].created_at - gpu_metrics[i].created_at).total_seconds()
            total_monitoring_time += time_diff
            if gpu_metrics[i].gpu_load > 0:
                total_utilization_time += time_diff
        
        avg_utilization = (total_utilization_time / total_monitoring_time) * 100 if total_monitoring_time > 0 else 0.0
        
        # Return performance analysis
        return {
            "gpu_index": gpu_index,
            "current_status": gpu_metric.to_dict(),
            "performance_summary": {
                "total_metrics": total_metrics,
                "avg_gpu_load": round(avg_gpu_load, 1),
                "avg_temperature": round(avg_temperature, 1) if avg_temperature else None,
                "avg_power_usage": round(avg_power_usage, 1) if avg_power_usage else None,
                "min_gpu_load": round(min_gpu_load, 1) if min_gpu_load else None,
                "min_temperature": round(min_temperature, 1) if min_temperature else None,
                "min_power_usage": round(min_power_usage, 1) if min_power_usage else None,
                "max_gpu_load": round(max_gpu_load, 1) if max_gpu_load else None,
                "max_temperature": round(max_temperature, 1) if max_temperature else None,
                "max_power_usage": round(max_power_usage, 1) if max_power_usage else None,
                "avg_utilization": round(avg_utilization, 1) if avg_utilization else None
            },
            "summary": f"Analyzed {total_metrics} GPU metrics for GPU {gpu_index} over the last 7 days"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving GPU performance: {str(e)}")