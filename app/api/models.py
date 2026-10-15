"""
Models API endpoints for Ollama Monitor
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import Model, Request, get_db
from app.schemas import Model as ModelSchema

router = APIRouter(prefix="/models", tags=["models"])

@router.get("/", response_model=List[ModelSchema])
async def get_models(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("total_requests", alias="sort"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of models with optional sorting
    """
    try:
        # Build the query
        query = select(Model).order_by(asc(sort_by) if sort_order == "asc" else desc(sort_by))
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute the query
        result = await db.execute(query)
        models = result.scalars().all()
        
        return models
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving models: {str(e)}")

@router.get("/{model_name}", response_model=ModelSchema)
async def get_model(model_name: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific model by name
    """
    try:
        query = select(Model).where(Model.name == model_name)
        
        result = await db.execute(query)
        model = result.scalar_one_or_none()
        
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
            
        return model
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving model: {str(e)}")

@router.get("/{model_name}/statistics", response_model=dict)
async def get_model_statistics(model_name: str, db: AsyncSession = Depends(get_db)):
    """
    Get detailed statistics for a specific model
    """
    try:
        # Get the model
        query = select(Model).where(Model.name == model_name)
        result = await db.execute(query)
        model = result.scalar_one_or_none()
        
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Get statistics for the model
        # Filter requests by model name
        query = select(Request).where(Request.model_name == model_name)
        
        result = await db.execute(query)
        requests = result.scalars().all()
        
        if not requests:
            return {
                "model_name": model_name,
                "total_requests": 0,
                "average_generation_speed": 0.0,
                "average_prompt_processing_speed": 0.0,
                "average_response_time": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "error_count": 0,
                "context_length": model.context_length,
                "quantization_type": model.quantization_type
            }
        
        # Calculate statistics
        total_requests = len(requests)
        total_input_tokens = sum(r.prompt_eval_count or 0 for r in requests if r.prompt_eval_count is not None)
        total_output_tokens = sum(r.eval_count or 0 for r in requests if r.eval_count is not None)
        
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
        
        # Calculate average response time (in seconds)
        total_response_time = sum(r.total_duration or 0 for r in requests if r.total_duration is not None)
        average_response_time = (total_response_time / total_requests / 1000) if total_requests > 0 else 0.0
        
        # Calculate error count
        error_count = sum(1 for r in requests if r.execution_status == "ERROR")
        
        # Calculate average context length
        average_context_length = sum(
            r.total_tokens or 0 
            for r in requests 
            if r.total_tokens is not None
        ) / total_requests if total_requests > 0 else 0.0
        
        return {
            "model_name": model_name,
            "total_requests": total_requests,
            "average_generation_speed": round(average_generation_speed, 1),
            "average_prompt_processing_speed": round(average_prompt_processing_speed, 1),
            "average_response_time": round(average_response_time, 1),  # already in seconds
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "error_count": error_count,
            "context_length": model.context_length,
            "quantization_type": model.quantization_type,
            "average_context_length": round(average_context_length, 1)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving model statistics: {str(e)}")

@router.get("/{model_name}/comparisons", response_model=dict)
async def get_model_comparisons(
    model_name: str,
    comparison_model: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Compare two models
    """
    try:
        # Get the first model
        query = select(Model).where(Model.name == model_name)
        result = await db.execute(query)
        model1 = result.scalar_one_or_none()
        
        if not model1:
            raise HTTPException(status_code=404, detail=f"Model {model_name} not found")
        
        # Get the second model
        query = select(Model).where(Model.name == comparison_model)
        result = await db.execute(query)
        model2 = result.scalar_one_or_none()
        
        if not model2:
            raise HTTPException(status_code=404, detail=f"Model {comparison_model} not found")
        
        # Get statistics for both models
        query = select(Request).where(Request.model_name.in_([model_name, comparison_model]))
        result = await db.execute(query)
        requests = result.scalars().all()
        
        # Filter requests for each model
        model1_requests = [r for r in requests if r.model_name == model_name]
        model2_requests = [r for r in requests if r.model_name == comparison_model]
        
        # Calculate statistics for model 1
        model1_stats = calculate_model_stats(model1_requests)
        
        # Calculate statistics for model 2
        model2_stats = calculate_model_stats(model2_requests)
        
        return {
            "model1": {
                "name": model_name,
                "statistics": model1_stats
            },
            "model2": {
                "name": comparison_model,
                "statistics": model2_stats
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving model comparison: {str(e)}")

def calculate_model_stats(requests):
    """Helper function to calculate model statistics"""
    if not requests:
        return {
            "total_requests": 0,
            "average_generation_speed": 0.0,
            "average_prompt_processing_speed": 0.0,
            "average_response_time": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "error_count": 0
        }
    
    total_requests = len(requests)
    total_input_tokens = sum(r.total_tokens or 0 for r in requests if r.total_tokens is not None)
    total_output_tokens = sum(r.output_tokens or 0 for r in requests if r.output_tokens is not None)
    
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
    
    # Calculate average response time (in seconds)
    total_response_time = sum(r.total_duration or 0 for r in requests if r.total_duration is not None)
    average_response_time = total_response_time / total_requests if total_requests > 0 else 0.0
    
    # Calculate error count
    error_count = sum(1 for r in requests if r.execution_status == "ERROR")
    
    return {
        "total_requests": total_requests,
        "average_generation_speed": round(average_generation_speed, 1),
        "average_prompt_processing_speed": round(average_prompt_processing_speed, 1),
        "average_response_time": round(average_response_time / 1000, 1),  # Convert to seconds
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "error_count": error_count
    }

@router.get("/{model_name}/context_analysis", response_model=dict)
async def get_context_analysis(model_name: str, db: AsyncSession = Depends(get_db)):
    """
    Analyze model performance based on context length
    """
    try:
        # Get the model
        query = select(Model).where(Model.name == model_name)
        result = await db.execute(query)
        model = result.scalar_one_or_none()
        
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Get requests for this model with complete context data
        query = select(Request).where(
            Request.model_name == model_name,
            Request.total_tokens.isnot(None)
        )
        
        result = await db.execute(query)
        requests = result.scalars().all()
        
        if not requests:
            return {
                "model_name": model_name,
                "context_analysis": [],
                "summary": "No requests with complete context data found"
            }
        
        # Group requests by context length
        context_groups = {}
        for request in requests:
            if request.total_tokens:
                # Create groups of 1000 tokens
                context_group = (request.total_tokens // 1000) * 1000
                if context_group not in context_groups:
                    context_groups[context_group] = []
                context_groups[context_group].append(request)
        
        # Calculate statistics for each context group
        context_analysis = []
        for context_length, group_requests in context_groups.items():
            if len(group_requests) >= 3:  # Only include groups with at least 3 requests
                # Calculate average generation speed for this context length
                total_generation_time = sum(
                    r.eval_duration / 1_000_000_000 
                    for r in group_requests 
                    if r.eval_count and r.eval_duration and r.eval_duration > 0
                )
                total_generation_tokens = sum(
                    r.eval_count 
                    for r in group_requests 
                    if r.eval_count is not None
                )
                avg_generation_speed = total_generation_tokens / total_generation_time if total_generation_time > 0 else 0.0
                
                # Calculate average response time (in seconds)
                total_response_time = sum(r.total_duration or 0 for r in group_requests if r.total_duration is not None)
                avg_response_time = total_response_time / len(group_requests) if len(group_requests) > 0 else 0.0
                
                # Calculate percentage of completed requests
                completed_count = sum(1 for r in group_requests if r.execution_status == "COMPLETED")
                completion_rate = (completed_count / len(group_requests)) * 100
                
                # Add to analysis
                context_analysis.append({
                    "context_length": context_length,
                    "request_count": len(group_requests),
                    "avg_generation_speed": round(avg_generation_speed, 1),
                    "avg_response_time": round(avg_response_time / 1000, 1),  # Convert to seconds
                    "completion_rate": round(completion_rate, 1)
                })
        
        # Sort by context length
        context_analysis.sort(key=lambda x: x["context_length"])
        
        # Return analysis
        return {
            "model_name": model_name,
            "context_analysis": context_analysis,
            "summary": f"Analyzed {len(context_groups)} context length groups with {len(requests)} total requests"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving context analysis: {str(e)}")

@router.get("/{model_name}/long_requests", response_model=dict)
async def get_long_requests(model_name: str, threshold: int = 60, db: AsyncSession = Depends(get_db)):
    """
    Find long-running requests for a model
    """
    try:
        # Get the model
        query = select(Model).where(Model.name == model_name)
        result = await db.execute(query)
        model = result.scalar_one_or_none()
        
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Get requests for this model that exceed the threshold
        # We use a threshold of 60 seconds (1 minute) for long requests
        # and only completed requests are considered
        query = select(Request).where(
            Request.model_name == model_name,
            Request.execution_status == "COMPLETED",
            Request.total_duration > threshold * 1000  # Convert to milliseconds
        )
        
        result = await db.execute(query)
        long_requests = result.scalars().all()
        
        if not long_requests:
            return {
                "model_name": model_name,
                "threshold": threshold,
                "long_requests": [],
                "summary": f"No requests exceeding {threshold} seconds found"
            }
        
        # Calculate average duration of long requests
        total_duration = sum(r.total_duration for r in long_requests)
        avg_duration = total_duration / len(long_requests) / 1000  # Convert to seconds
        
        return {
            "model_name": model_name,
            "threshold": threshold,
            "long_requests": [r.to_dict() for r in long_requests],
            "total_long_requests": len(long_requests),
            "average_duration": round(avg_duration, 1),  # Convert to seconds
            "summary": f"Found {len(long_requests)} long-running requests with average duration of {avg_duration:.1f} seconds"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving long requests: {str(e)}")