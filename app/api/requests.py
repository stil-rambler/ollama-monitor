"""
Requests API endpoints for Ollama Monitor
"""

from datetime import datetime, timedelta
import json
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import asc, desc, select, func
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

router = APIRouter(prefix="/requests", tags=["requests"])

@router.get("/", response_model=List[RequestSchema])
async def get_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    model_name: Optional[str] = Query(None),
    client_ip: Optional[str] = Query(None),
    client_name: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    http_status: Optional[int] = Query(None),
    execution_status: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of requests with optional filtering and sorting
    """
    try:
        # Build the query
        query = select(Request)
        
        # Apply filters
        if start_time:
            query = query.where(Request.created_at >= start_time)
        if end_time:
            query = query.where(Request.created_at <= end_time)
        if model_name:
            query = query.where(Request.model_name.ilike(f"%{model_name}%"))
        if client_ip:
            query = query.where(Request.client_ip.ilike(f"%{client_ip}%"))
        if client_name:
            query = query.where(Request.client_name.ilike(f"%{client_name}%"))
        if operation_type:
            query = query.where(Request.operation_type == operation_type)
        if http_status:
            query = query.where(Request.http_status == http_status)
        if execution_status:
            query = query.where(Request.execution_status == execution_status)
        
        # Apply sorting
        sort_field = getattr(Request, sort_by, Request.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute the query
        result = await db.execute(query)
        requests = result.scalars().all()
        
        return requests
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving requests: {str(e)}")

@router.get("/{request_id}", response_model=RequestSchema)
async def get_request(request_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific request by ID
    """
    try:
        query = select(Request).where(Request.id == request_id)
        
        result = await db.execute(query)
        request = result.scalar_one_or_none()
        
        if not request:
            raise HTTPException(status_code=404, detail="Request not found")
            
        return request
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving request: {str(e)}")

@router.get("/count", response_model=dict)
async def get_request_count(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    model_name: Optional[str] = Query(None),
    client_ip: Optional[str] = Query(None),
    client_name: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    http_status: Optional[int] = Query(None),
    execution_status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Get count of requests with optional filtering
    """
    try:
        # Build the query
        query = select(func.count(Request.id))
        
        # Apply filters
        if start_time:
            query = query.where(Request.created_at >= start_time)
        if end_time:
            query = query.where(Request.created_at <= end_time)
        if model_name:
            query = query.where(Request.model_name.ilike(f"%{model_name}%"))
        if client_ip:
            query = query.where(Request.client_ip.ilike(f"%{client_ip}%"))
        if client_name:
            query = query.where(Request.client_name.ilike(f"%{client_name}%"))
        if operation_type:
            query = query.where(Request.operation_type == operation_type)
        if http_status:
            query = query.where(Request.http_status == http_status)
        if execution_status:
            query = query.where(Request.execution_status == execution_status)
        
        # Execute the query
        result = await db.execute(query)
        count = result.scalar_one()
        
        return {"count": count}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error counting requests: {str(e)}")

@router.get("/export/CSV", response_class=Response)
async def export_requests_csv(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    model_name: Optional[str] = Query(None),
    client_ip: Optional[str] = Query(None),
    client_name: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    http_status: Optional[int] = Query(None),
    execution_status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export requests as CSV
    """
    try:
        # Build the query
        query = select(Request)
        
        # Apply filters
        if start_time:
            query = query.where(Request.created_at >= start_time)
        if end_time:
            query = query.where(Request.created_at <= end_time)
        if model_name:
            query = query.where(Request.model_name.ilike(f"%{model_name}%"))
        if client_ip:
            query = query.where(Request.client_ip.ilike(f"%{client_ip}%"))
        if client_name:
            query = query.where(Request.client_name.ilike(f"%{client_name}%"))
        if operation_type:
            query = query.where(Request.operation_type == operation_type)
        if http_status:
            query = query.where(Request.http_status == http_status)
        if execution_status:
            query = query.where(Request.execution_status == execution_status)
        
        # Execute the query
        result = await db.execute(query)
        requests = result.scalars().all()
        
        # Convert to CSV
        csv_lines = []
        
        # CSV header
        csv_lines.append("id,created_at,started_at,finished_at,client_ip,client_port,method,endpoint,model_name,operation_type,http_status,execution_status,request_size,response_size,user_agent,client_name,monitoring_mode,data_source,total_duration,model_load_duration,prompt_eval_duration,eval_duration,first_byte_time,first_token_time,response_transfer_time,prompt_eval_count,eval_count,total_tokens,output_tokens")
        
        # CSV data
        for request in requests:
            row = [
                request.id,
                request.created_at.isoformat(),
                request.started_at.isoformat() if request.started_at else "",
                request.finished_at.isoformat() if request.finished_at else "",
                request.client_ip or "",
                request.client_port or "",
                request.method,
                request.endpoint,
                request.model_name or "",
                request.operation_type,
                request.http_status,
                request.execution_status,
                request.request_size or "",
                request.response_size or "",
                request.user_agent or "",
                request.client_name or "",
                request.monitoring_mode,
                request.data_source,
                request.total_duration or "",
                request.model_load_duration or "",
                request.prompt_eval_duration or "",
                request.eval_duration or "",
                request.first_byte_time or "",
                request.first_token_time or "",
                request.response_transfer_time or "",
                request.prompt_eval_count or "",
                request.eval_count or "",
                request.total_tokens or "",
                request.output_tokens or ""
            ]
            csv_lines.append(",".join(map(str, row)))
        
        # Return CSV data
        csv_content = "\n".join(csv_lines)
        return Response(content=csv_content, media_type="text/csv")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting requests: {str(e)}")

@router.get("/export/JSON", response_class=Response)
async def export_requests_json(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    model_name: Optional[str] = Query(None),
    client_ip: Optional[str] = Query(None),
    client_name: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    http_status: Optional[int] = Query(None),
    execution_status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export requests as JSON
    """
    try:
        # Build the query
        query = select(Request)
        
        # Apply filters
        if start_time:
            query = query.where(Request.created_at >= start_time)
        if end_time:
            query = query.where(Request.created_at <= end_time)
        if model_name:
            query = query.where(Request.model_name.ilike(f"%{model_name}%"))
        if client_ip:
            query = query.where(Request.client_ip.ilike(f"%{client_ip}%"))
        if client_name:
            query = query.where(Request.client_name.ilike(f"%{client_name}%"))
        if operation_type:
            query = query.where(Request.operation_type == operation_type)
        if http_status:
            query = query.where(Request.http_status == http_status)
        if execution_status:
            query = query.where(Request.execution_status == execution_status)
        
        # Execute the query
        result = await db.execute(query)
        requests = result.scalars().all()
        
        # Convert to JSON
        json_data = []
        for request in requests:
            json_data.append(request.to_dict())
        
        # Return JSON data
        return Response(content=json.dumps(json_data, indent=2), media_type="application/json")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting requests: {str(e)}")

@router.get("/statistics", response_model=dict)
async def get_request_statistics(db: AsyncSession = Depends(get_db)):
    """
    Get statistics for all requests
    """
    try:
        # Get total requests
        total_requests_query = select(func.count(Request.id))
        total_requests_result = await db.execute(total_requests_query)
        total_requests = total_requests_result.scalar_one()
        
        # Get completed requests
        completed_requests_query = select(func.count(Request.id)).where(Request.execution_status == "COMPLETED")
        completed_requests_result = await db.execute(completed_requests_query)
        completed_requests = completed_requests_result.scalar_one()
        
        # Get average generation speed
        if completed_requests > 0:
            query = select(func.avg(Request.eval_count / (Request.eval_duration / 1_000_000_000))).where(
                Request.eval_count.isnot(None),
                Request.eval_duration.isnot(None),
                Request.eval_duration > 0,
                Request.execution_status == "COMPLETED"
            )
            result = await db.execute(query)
            average_generation_speed = result.scalar_one()
        else:
            average_generation_speed = 0.0
        
        # Get average prompt processing speed
        if completed_requests > 0:
            query = select(func.avg(Request.prompt_eval_count / (Request.prompt_eval_duration / 1_000_000_000))).where(
                Request.prompt_eval_count.isnot(None),
                Request.prompt_eval_duration.isnot(None),
                Request.prompt_eval_duration > 0,
                Request.execution_status == "COMPLETED"
            )
            result = await db.execute(query)
            average_prompt_processing_speed = result.scalar_one()
        else:
            average_prompt_processing_speed = 0.0
        
        # Get average response time
        if completed_requests > 0:
            query = select(func.avg(Request.total_duration)).where(Request.execution_status == "COMPLETED")
            result = await db.execute(query)
            average_response_time = result.scalar_one()
        else:
            average_response_time = 0.0
        
        # Get statistics by model
        model_stats_query = select(
            Request.model_name,
            func.count(Request.id).label("request_count"),
            func.avg(Request.eval_count / (Request.eval_duration / 1_000_000_000)).label("avg_generation_speed"),
            func.avg(Request.prompt_eval_count / (Request.prompt_eval_duration / 1_000_000_000)).label("avg_prompt_processing_speed"),
            func.avg(Request.total_duration).label("avg_response_time"),
            func.sum(Request.total_tokens).label("total_input_tokens"),
            func.sum(Request.output_tokens).label("total_output_tokens")
        ).where(Request.execution_status == "COMPLETED").group_by(Request.model_name)
        
        result = await db.execute(model_stats_query)
        model_stats = []
        for row in result.fetchall():
            model_stats.append({
                "model_name": row[0],
                "request_count": row[1],
                "avg_generation_speed": round(row[2], 2) if row[2] else 0.0,
                "avg_prompt_processing_speed": round(row[3], 2) if row[3] else 0.0,
                "avg_response_time": round(row[4], 2) if row[4] else 0.0,
                "total_input_tokens": row[5],
                "total_output_tokens": row[6]
            })
        
        # Get statistics by client
        client_stats_query = select(
            Request.client_name,
            func.count(Request.id).label("request_count"),
            func.avg(Request.total_duration).label("avg_response_time"),
            func.sum(Request.total_tokens).label("total_input_tokens"),
            func.sum(Request.output_tokens).label("total_output_tokens")
        ).where(Request.execution_status == "COMPLETED").group_by(Request.client_name)
        
        result = await db.execute(client_stats_query)
        client_stats = []
        for row in result.fetchall():
            client_stats.append({
                "client_name": row[0],
                "request_count": row[1],
                "avg_response_time": round(row[2], 2) if row[2] else 0.0,
                "total_input_tokens": row[3],
                "total_output_tokens": row[4]
            })
        
        return {
            "total_requests": total_requests,
            "completed_requests": completed_requests,
            "average_generation_speed": round(average_generation_speed, 1) if average_generation_speed else 0.0,
            "average_prompt_processing_speed": round(average_prompt_processing_speed, 1) if average_prompt_processing_speed else 0.0,
            "average_response_time": round(average_response_time / 1000, 1) if average_response_time else 0.0,  # Convert to seconds
            "model_statistics": model_stats,
            "client_statistics": client_stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving request statistics: {str(e)}")