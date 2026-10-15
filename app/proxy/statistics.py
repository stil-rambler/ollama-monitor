"""
Statistics collection and calculation for Ollama Monitor proxy
"""

import json
import time
from typing import Dict, Any, Optional, List
from uuid import UUID

import numpy as np

from app.database import Request, Model, Client, GpuMetric
from app.services.request_tracker import RequestTracker
from app.schemas import Request as RequestSchema

class StatisticsCollector:
    """
    Class for collecting and calculating statistics from Ollama responses
    """
    
    def __init__(self):
        self.request_tracker = RequestTracker()
        
    def collect_request_stats(self, request_id: str, response_data: dict) -> Dict[str, Any]:
        """
        Collect statistics from a request response
        """
        # Initialize stats dictionary
        stats = {
            "request_id": request_id,
            "collection_time": time.time(),
            "parsed_objects": [],
            "total_duration": 0,
            "model_load_duration": 0,
            "prompt_eval_duration": 0,
            "eval_duration": 0,
            "first_byte_time": 0,
            "first_token_time": 0,
            "response_transfer_time": 0,
            "prompt_eval_count": 0,
            "eval_count": 0,
            "total_tokens": 0,
            "output_tokens": 0
        }
        
        # Extract statistics from the response data
        # This will be specific to the type of response (NDJSON, SSE, etc.)
        # For now, we'll handle the standard Ollama response format
        self._extract_standard_stats(stats, response_data)
        
        # Calculate derived statistics
        stats = self._calculate_derived_stats(stats)
        
        # Update the request with the collected statistics
        request_tracker = RequestTracker()
        request_tracker.update_request(request_id, stats)
        
        return stats
        
    def _extract_standard_stats(self, stats: Dict[str, Any], response_data: dict):
        """
        Extract statistics from standard Ollama response format
        """
        # Handle the case where the response data is a list of JSON objects
        # This is the case for NDJSON streaming responses
        if isinstance(response_data, list):
            for obj in response_data:
                self._extract_single_object_stats(stats, obj)
        elif isinstance(response_data, dict):
            # Handle single JSON object
            self._extract_single_object_stats(stats, response_data)
            
    def _extract_single_object_stats(self, stats: Dict[str, Any], obj: dict):
        """
        Extract statistics from a single JSON object
        """
        # Check if this is a completion event
        if "done" in obj and obj["done"]:
            # This is the final object, so we can extract final statistics
            if "eval_count" in obj:
                stats["eval_count"] = obj["eval_count"]
            if "prompt_eval_count" in obj:
                stats["prompt_eval_count"] = obj["prompt_eval_count"]
            if "eval_duration" in obj:
                stats["eval_duration"] = obj["eval_duration"]
            if "prompt_eval_duration" in obj:
                stats["prompt_eval_duration"] = obj["prompt_eval_duration"]
            if "load_duration" in obj:
                stats["model_load_duration"] = obj["load_duration"]
                
        # Check if this is a response event
        if "response" in obj:
            # This is a response event, so we can extract token statistics
            # The response is a string, so we'll count the characters
            # but we need to be careful about encoding
            response_text = obj["response"]
            if not isinstance(response_text, str):
                response_text = str(response_text)
                
            # Count the number of characters in the response
            # This is not exactly the number of tokens, but it's a rough estimate
            # For exact token count, we would need to use a tokenizer, but that's 
            # beyond the scope of this implementation
            stats["output_tokens"] = len(response_text)
            
            # Update total tokens processed
            if stats["prompt_eval_count"]:
                stats["total_tokens"] = stats["prompt_eval_count"] + stats["output_tokens"]
        
        # Update the total duration
        # In a real implementation, we would have access to the actual timings from 
        # the request and response events, but for now we'll use the time from the first
        # completion event
        if "done" in obj and obj["done"]:
            # This is the completion event, so we can set the total duration
            # but we need to figure out when the request started
            # In a real implementation, we would have access to the start time
            # from when the request was first received
            stats["total_duration"] = 0  # Placeholder - we would need to track this
            
    def _calculate_derived_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate derived statistics from the collected data
        """
        # Calculate average generation speed (tokens per second)
        if stats["eval_count"] > 0 and stats["eval_duration"] > 0:
            stats["generation_speed"] = stats["eval_count"] / (stats["eval_duration"] / 1_000_000_000)
        else:
            stats["generation_speed"] = 0.0
            
        # Calculate average prompt processing speed (tokens per second)
        if stats["prompt_eval_count"] > 0 and stats["prompt_eval_duration"] > 0:
            stats["prompt_processing_speed"] = stats["prompt_eval_count"] / (stats["prompt_eval_duration"] / 1_000_000_000)
        else:
            stats["prompt_processing_speed"] = 0.0
            
        # Calculate average response time (in seconds)
        if stats["total_duration"] > 0:
            stats["average_response_time"] = stats["total_duration"] / 1000  # Convert to seconds
        else:
            stats["average_response_time"] = 0.0
            
        # Calculate total number of inputs and outputs
        # We need to be careful about the case where we have multiple responses
        # In a real implementation, we would track the total number of inputs and outputs
        # over the entire request
        if stats["prompt_eval_count"] and stats["output_tokens"]:
            stats["total_input_tokens"] = stats["prompt_eval_count"]
            stats["total_output_tokens"] = stats["output_tokens"]
        elif stats["prompt_eval_count"]:
            stats["total_input_tokens"] = stats["prompt_eval_count"]
            stats["total_output_tokens"] = 0
        elif stats["output_tokens"]:
            stats["total_input_tokens"] = 0
            stats["total_output_tokens"] = stats["output_tokens"]
        else:
            stats["total_input_tokens"] = 0
            stats["total_output_tokens"] = 0
            
        return stats
        
    def calculate_model_statistics(self, model_name: str, start_time: float, end_time: float) -> Dict[str, Any]:
        """
        Calculate statistics for a specific model over a time period
        """
        # Get requests for the model within the time period
        # This is a placeholder - in a real implementation, we would query the database
        # for requests with the specified model name and within the time period
        requests = []
        
        # Calculate the statistics based on the requests
        # This is a simplified version - in a real implementation, we would calculate
        # the actual statistics from the collected request data
        stats = {
            "model_name": model_name,
            "total_requests": len(requests),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_duration": 0,
            "average_generation_speed": 0.0,
            "average_prompt_processing_speed": 0.0,
            "average_response_time": 0.0,
            "error_count": 0,
            "min_response_time": float('inf'),
            "max_response_time": 0.0,
            "p95_response_time": 0.0
        }
        
        # Calculate the actual statistics
        response_times = []
        for request in requests:
            # Extract the response time for this request
            # In a real implementation, we would have access to the actual response time
            # from the collected data
            response_time = 0  # Placeholder
            
            # Update the response times list
            response_times.append(response_time)
            
            # Update the total duration
            stats["total_duration"] += response_time
            
            # Update the total token counts
            if hasattr(request, 'total_input_tokens'):
                stats["total_input_tokens"] += request.total_input_tokens
            if hasattr(request, 'total_output_tokens'):
                stats["total_output_tokens"] += request.total_output_tokens
                
            # Update the error count
            if hasattr(request, 'error') and request.error:
                stats["error_count"] += 1
                
            # Update the min and max response times
            if response_time < stats["min_response_time"]:
                stats["min_response_time"] = response_time
            if response_time > stats["max_response_time"]:
                stats["max_response_time"] = response_time
                
        # Calculate the average response time
        if len(response_times) > 0:
            stats["average_response_time"] = stats["total_duration"] / len(response_times)
            stats["average_generation_speed"] = stats["total_output_tokens"] / stats["total_duration"] if stats["total_duration"] > 0 else 0.0
            
            # Calculate P95 response time
            # We need to sort the response times
            sorted_response_times = sorted(response_times)
            p95_index = int(len(sorted_response_times) * 0.95)
            stats["p95_response_time"] = sorted_response_times[p95_index]
            
        # Update the statistics with the calculated values
        stats["average_generation_speed"] = stats["total_output_tokens"] / stats["total_duration"] if stats["total_duration"] > 0 else 0.0
        stats["average_prompt_processing_speed"] = stats["total_input_tokens"] / stats["total_duration"] if stats["total_duration"] > 0 else 0.0
            
        return stats
        
    def calculate_client_statistics(self, client_ip: str, start_time: float, end_time: float) -> Dict[str, Any]:
        """
        Calculate statistics for a specific client over a time period
        """
        # Get requests for the client within the time period
        # This is a placeholder - in a real implementation, we would query the database
        # for requests from the specified client IP and within the time period
        requests = []
        
        # Calculate the statistics based on the requests
        # This is a simplified version - in a real implementation, we would calculate
        # the actual statistics from the collected data
        stats = {
            "client_ip": client_ip,
            "total_requests": len(requests),
            "total_request_duration": 0,
            "average_response_time": 0.0,
            "used_models": [],
            "error_count": 0,
            "min_response_time": float('inf'),
            "max_response_time": 0.0,
            "p95_response_time": 0.0
        }
        
        # Calculate the actual statistics
        response_times = []
        used_models = set()
        for request in requests:
            # Extract the response time for this request
            # In a real implementation, we would have access to the actual response time
            # from the collected data
            response_time = 0  # Placeholder
            
            # Update the response times list
            response_times.append(response_time)
            
            # Update the total request duration
            stats["total_request_duration"] += response_time
            
            # Update the used models
            if hasattr(request, 'model_name'):
                used_models.add(request.model_name)
                
            # Update the error count
            if hasattr(request, 'error') and request.error:
                stats["error_count"] += 1
                
            # Update the min and max response times
            if response_time < stats["min_response_time"]:
                stats["min_response_time"] = response_time
            if response_time > stats["max_response_time"]:
                stats["max_response_time"] = response_time
                
        # Calculate the average response time
        if len(response_times) > 0:
            stats["average_response_time"] = stats["total_request_duration"] / len(response_times)
            
            # Calculate P95 response time
            # We need to sort the response times
            sorted_response_times = sorted(response_times)
            p95_index = int(len(sorted_response_times) * 0.95)
            stats["p95_response_time"] = sorted_response_times[p95_index]
            
        # Update the statistics with the calculated values
        stats["used_models"] = list(used_models)
        
        return stats
        
    def get_summary_statistics(self) -> Dict[str, Any]:
        """
        Get summary statistics for all requests
        """
        # Get all requests from the database
        # This is a placeholder - in a real implementation, we would query the database
        # for all requests
        requests = []
        
        # Calculate the statistics based on the requests
        # This is a simplified version - in a real implementation, we would calculate
        # the actual statistics from the collected data
        summary = {
            "total_requests": len(requests),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_duration": 0,
            "average_generation_speed": 0.0,
            "average_prompt_processing_speed": 0.0,
            "average_response_time": 0.0,
            "error_count": 0,
            "min_response_time": float('inf'),
            "max_response_time": 0.0,
            "p95_response_time": 0.0
        }
        
        # Calculate the actual statistics
        response_times = []
        for request in requests:
            # Extract the response time for this request
            # In a real implementation, we would have access to the actual response time
            # from the collected data
            response_time = 0  # Placeholder
            
            # Update the response times list
            response_times.append(response_time)
            
            # Update the total duration
            summary["total_duration"] += response_time
            
            # Update the total token counts
            if hasattr(request, 'total_input_tokens'):
                summary["total_input_tokens"] += request.total_input_tokens
            if hasattr(request, 'total_output_tokens'):
                summary["total_output_tokens"] += request.total_output_tokens
                
            # Update the error count
            if hasattr(request, 'error') and request.error:
                summary["error_count"] += 1
                
            # Update the min and max response times
            if response_time < summary["min_response_time"]:
                summary["min_response_time"] = response_time
            if response_time > summary["max_response_time"]:
                summary["max_response_time"] = response_time
                
        # Calculate the average response time
        if len(response_times) > 0:
            summary["average_response_time"] = summary["total_duration"] / len(response_times)
            summary["average_generation_speed"] = summary["total_output_tokens"] / summary["total_duration"] if summary["total_duration"] > 0 else 0.0
            summary["average_prompt_processing_speed"] = summary["total_input_tokens"] / summary["total_duration"] if summary["total_duration"] > 0 else 0.0
            
            # Calculate P95 response time
            # We need to sort the response times
            sorted_response_times = sorted(response_times)
            p95_index = int(len(sorted_response_times) * 0.95)
            summary["p95_response_time"] = sorted_response_times[p95_index]
            
        # Update the summary with the calculated values
        summary["average_generation_speed"] = summary["total_output_tokens"] / summary["total_duration"] if summary["total_duration"] > 0 else 0.0
        summary["average_prompt_processing_speed"] = summary["total_input_tokens"] / summary["total_duration"] if summary["total_duration"] > 0 else 0.0
            
        return summary