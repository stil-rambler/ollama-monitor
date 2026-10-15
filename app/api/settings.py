"""
Settings API endpoints for Ollama Monitor
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import Setting, get_db
from app.schemas import Setting as SettingSchema

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/all", response_model=List[SettingSchema])
async def get_all_settings(db: AsyncSession = Depends(get_db)):
    """
    Get all settings
    """
    try:
        query = select(Setting)
        result = await db.execute(query)
        settings = result.scalars().all()
        
        return settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving settings: {str(e)}")

@router.get("/{key}", response_model=SettingSchema)
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific setting by key
    """
    try:
        query = select(Setting).where(Setting.key == key)
        result = await db.execute(query)
        setting = result.scalar_one_or_none()
        
        if not setting:
            raise HTTPException(status_code=404, detail="Setting not found")
            
        return setting
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving setting: {str(e)}")

@router.put("/{key}", response_model=SettingSchema)
async def update_setting(key: str, value: str, db: AsyncSession = Depends(get_db)):
    """
    Update a setting
    """
    try:
        # Check if setting exists
        query = select(Setting).where(Setting.key == key)
        result = await db.execute(query)
        setting = result.scalar_one_or_none()
        
        if not setting:
            # Create new setting
            setting = Setting(key=key, value=value, data_type="string")
            db.add(setting)
        else:
            # Update existing setting
            setting.value = value
        
        # Commit changes
        await db.commit()
        
        # Refresh setting to get updated data
        await db.refresh(setting)
        
        return setting
        
    except Exception as e:
        # Rollback transaction
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating setting: {str(e)}")

@router.get("/ui", response_model=dict)
async def get_ui_settings(db: AsyncSession = Depends(get_db)):
    """
    Get UI settings
    """
    try:
        # Get UI settings
        query = select(Setting).where(Setting.key.in_(['language', 'theme']))
        result = await db.execute(query)
        settings = result.scalars().all()
        
        # Convert to dictionary
        ui_settings = {}
        for setting in settings:
            ui_settings[setting.key] = setting.value
        
        return ui_settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving UI settings: {str(e)}")

@router.put("/ui", response_model=dict)
async def update_ui_settings(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Update UI settings
    """
    try:
        # Validate input
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Data must be a dictionary")
        
        # Get current UI settings
        query = select(Setting).where(Setting.key.in_(['language', 'theme']))
        result = await db.execute(query)
        existing_settings = result.scalars().all()
        
        # Create a dictionary of existing settings
        existing_dict = {s.key: s for s in existing_settings}
        
        # Update or create settings
        for key, value in data.items():
            if key not in ['language', 'theme']:
                continue
                
            if key in existing_dict:
                # Update existing setting
                setting = existing_dict[key]
                setting.value = str(value)
            else:
                # Create new setting
                setting = Setting(key=key, value=str(value), data_type="string")
                db.add(setting)
        
        # Commit changes
        await db.commit()
        
        # Refresh settings
        for setting in existing_settings:
            await db.refresh(setting)
        
        # Return updated settings
        return {k: v.value for k, v in existing_dict.items()}
        
    except Exception as e:
        # Rollback transaction
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating UI settings: {str(e)}")

@router.get("/database", response_model=dict)
async def get_database_settings(db: AsyncSession = Depends(get_db)):
    """
    Get database settings
    """
    try:
        # Get database settings
        query = select(Setting).where(Setting.key.in_(['database_path', 'retention_requests_days', 'retention_gpu_raw_hours', 'retention_gpu_aggregated_days']))
        result = await db.execute(query)
        settings = result.scalars().all()
        
        # Convert to dictionary
        db_settings = {}
        for setting in settings:
            db_settings[setting.key] = setting.value
        
        return db_settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving database settings: {str(e)}")

@router.put("/database", response_model=dict)
async def update_database_settings(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Update database settings
    """
    try:
        # Validate input
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Data must be a dictionary")
        
        # Get current database settings
        query = select(Setting).where(Setting.key.in_(['database_path', 'retention_requests_days', 'retention_gpu_raw_hours', 'retention_gpu_aggregated_days']))
        result = await db.execute(query)
        existing_settings = result.scalars().all()
        
        # Create a dictionary of existing settings
        existing_dict = {s.key: s for s in existing_settings}
        
        # Update settings
        for key, value in data.items():
            if key not in ['database_path', 'retention_requests_days', 'retention_gpu_raw_hours', 'retention_gpu_aggregated_days']:
                continue
                
            if key in existing_dict:
                # Update existing setting
                setting = existing_dict[key]
                setting.value = str(value)
            else:
                # Create new setting
                setting = Setting(key=key, value=str(value), data_type="string")
                db.add(setting)
        
        # Commit changes
        await db.commit()
        
        # Refresh settings
        for setting in existing_settings:
            await db.refresh(setting)
        
        # Return updated settings
        return {k: v.value for k, v in existing_dict.items()}
        
    except Exception as e:
        # Rollback transaction
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating database settings: {str(e)}")

@router.get("/monitoring", response_model=dict)
async def get_monitoring_settings(db: AsyncSession = Depends(get_db)):
    """
    Get monitoring settings
    """
    try:
        # Get monitoring settings
        query = select(Setting).where(Setting.key.in_(['passive_enabled', 'proxy_enabled', 'gpu_interval', 'ollama_interval']))
        result = await db.execute(query)
        settings = result.scalars().all()
        
        # Convert to dictionary
        monitoring_settings = {}
        for setting in settings:
            monitoring_settings[setting.key] = setting.value
        
        return monitoring_settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving monitoring settings: {str(e)}")

@router.put("/monitoring", response_model=dict)
async def update_monitoring_settings(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Update monitoring settings
    """
    try:
        # Validate input
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Data must be a dictionary")
        
        # Get current monitoring settings
        query = select(Setting).where(Setting.key.in_(['passive_enabled', 'proxy_enabled', 'gpu_interval', 'ollama_interval']))
        result = await db.execute(query)
        existing_settings = result.scalars().all()
        
        # Create a dictionary of existing settings
        existing_dict = {s.key: s for s in existing_settings}
        
        # Update settings
        for key, value in data.items():
            if key not in ['passive_enabled', 'proxy_enabled', 'gpu_interval', 'ollama_interval']:
                continue
                
            if key in existing_dict:
                # Update existing setting
                setting = existing_dict[key]
                setting.value = str(value)
            else:
                # Create new setting
                setting = Setting(key=key, value=str(value), data_type="string")
                db.add(setting)
        
        # Commit changes
        await db.commit()
        
        # Refresh settings
        for setting in existing_settings:
            await db.refresh(setting)
        
        # Return updated settings
        return {k: v.value for k, v in existing_dict.items()}
        
    except Exception as e:
        # Rollback transaction
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating monitoring settings: {str(e)}")

@router.get("/ollama", response_model=dict)
async def get_ollama_settings(db: AsyncSession = Depends(get_db)):
    """
    Get Ollama settings
    """
    try:
        # Get Ollama settings
        query = select(Setting).where(Setting.key.in_(['base_url', 'timeout']))
        result = await db.execute(query)
        settings = result.scalars().all()
        
        # Convert to dictionary
        ollama_settings = {}
        for setting in settings:
            ollama_settings[setting.key] = setting.value
        
        return ollama_settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving Ollama settings: {str(e)}")

@router.put("/ollama", response_model=dict)
async def update_ollama_settings(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Update Ollama settings
    """
    try:
        # Validate input
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Data must be a dictionary")
        
        # Get current Ollama settings
        query = select(Setting).where(Setting.key.in_(['base_url', 'timeout']))
        result = await db.execute(query)
        existing_settings = result.scalars().all()
        
        # Create a dictionary of existing settings
        existing_dict = {s.key: s for s in existing_settings}
        
        # Update settings
        for key, value in data.items():
            if key not in ['base_url', 'timeout']:
                continue
                
            if key in existing_dict:
                # Update existing setting
                setting = existing_dict[key]
                setting.value = str(value)
            else:
                # Create new setting
                setting = Setting(key=key, value=str(value), data_type="string")
                db.add(setting)
        
        # Commit changes
        await db.commit()
        
        # Refresh settings
        for setting in existing_settings:
            await db.refresh(setting)
        
        # Return updated settings
        return {k: v.value for k, v in existing_dict.items()}
        
    except Exception as e:
        # Rollback transaction
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating Ollama settings: {str(e)}")

@router.get("/logging", response_model=dict)
async def get_logging_settings(db: AsyncSession = Depends(get_db)):
    """
    Get logging settings
    """
    try:
        # Get logging settings
        query = select(Setting).where(Setting.key.in_(['level', 'save_request_body', 'save_response_body']))
        result = await db.execute(query)
        settings = result.scalars().all()
        
        # Convert to dictionary
        logging_settings = {}
        for setting in settings:
            logging_settings[setting.key] = setting.value
        
        return logging_settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving logging settings: {str(e)}")

@router.put("/logging", response_model=dict)
async def update_logging_settings(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Update logging settings
    """
    try:
        # Validate input
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Data must be a dictionary")
        
        # Get current logging settings
        query = select(Setting).where(Setting.key.in_(['level', 'save_request_body', 'save_response_body']))
        result = await db.execute(query)
        existing_settings = result.scalars().all()
        
        # Create a dictionary of existing settings
        existing_dict = {s.key: s for s in existing_settings}
        
        # Update settings
        for key, value in data.items():
            if key not in ['level', 'save_request_body', 'save_response_body']:
                continue
                
            if key in existing_dict:
                # Update existing setting
                setting = existing_dict[key]
                setting.value = str(value)
            else:
                # Create new setting
                setting = Setting(key=key, value=str(value), data_type="string")
                db.add(setting)
        
        # Commit changes
        await db.commit()
        
        # Refresh settings
        for setting in existing_settings:
            await db.refresh(setting)
        
        # Return updated settings
        return {k: v.value for k, v in existing_dict.items()}
        
    except Exception as e:
        # Rollback transaction
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating logging settings: {str(e)}")