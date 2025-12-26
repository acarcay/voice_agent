"""
Redis-based State Manager for Voice Agent

Replaces in-memory global variables with distributed state storage.

Features:
- Redis for cross-worker state sharing
- Appointment caching with TTL
- Conversation event streaming
- Distributed locking for concurrent operations
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio.lock import Lock

logger = logging.getLogger("state_manager")


class StateManager:
    """
    Production-grade state management with Redis.
    
    Provides:
    - Appointment caching (reduces DB load)
    - Conversation event logging (Redis Streams)
    - Distributed locking (prevents race conditions)
    - Pub/Sub for cross-worker notifications
    
    Usage:
        state = StateManager()
        await state.connect()
        await state.cache_appointment("id", {...})
        await state.log_conversation_event("id", "type", {...})
        await state.disconnect()
    """

    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize state manager.
        
        Args:
            redis_url: Redis connection URL.
                       If not provided, reads from REDIS_URL env var.
                       
        Raises:
            ValueError: If no Redis URL is available.
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        
        if not self.redis_url:
            raise ValueError(
                "REDIS_URL is required. "
                "Set it in environment or pass redis_url. "
                "Example: redis://localhost:6379/0"
            )
        
        self.redis: Optional[redis.Redis] = None
        self.cache_ttl = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour default
        self._connected = False

    async def connect(self) -> None:
        """
        Connect to Redis.
        
        Raises:
            Exception: If connection fails.
        """
        try:
            self.redis = redis.from_url(
                self.redis_url, 
                decode_responses=True,
                socket_connect_timeout=5
            )
            # Verify connection
            await self.redis.ping()
            self._connected = True
            logger.info("✅ Redis connection established")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            raise

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            self._connected = False
            logger.info("Redis connection closed")

    def _ensure_connected(self) -> None:
        """Raise error if not connected."""
        if not self._connected or not self.redis:
            raise RuntimeError("StateManager not connected. Call connect() first.")

    # ==================== Appointment Caching ====================

    async def cache_appointment(
        self, 
        appointment_id: str, 
        data: Dict[str, Any]
    ) -> None:
        """
        Cache appointment data for fast retrieval.
        
        Args:
            appointment_id: Unique appointment identifier.
            data: Appointment data dictionary.
        """
        self._ensure_connected()
        cache_key = f"appointment:{appointment_id}"
        await self.redis.setex(
            cache_key,
            self.cache_ttl,
            json.dumps(data, default=str)
        )
        logger.debug(f"Cached appointment: {appointment_id}")

    async def get_cached_appointment(
        self, 
        appointment_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get appointment from cache.
        
        Args:
            appointment_id: Unique appointment identifier.
            
        Returns:
            Appointment data or None if not cached.
        """
        self._ensure_connected()
        cache_key = f"appointment:{appointment_id}"
        cached = await self.redis.get(cache_key)
        
        if cached:
            logger.debug(f"Cache hit: {appointment_id}")
            return json.loads(cached)
        
        logger.debug(f"Cache miss: {appointment_id}")
        return None

    async def invalidate_appointment(self, appointment_id: str) -> None:
        """
        Remove appointment from cache (e.g., after status update).
        
        Args:
            appointment_id: Unique appointment identifier.
        """
        self._ensure_connected()
        cache_key = f"appointment:{appointment_id}"
        await self.redis.delete(cache_key)
        logger.debug(f"Cache invalidated: {appointment_id}")

    # ==================== Conversation Logging ====================

    async def log_conversation_event(
        self,
        appointment_id: str,
        event_type: str,
        data: Dict[str, Any]
    ) -> str:
        """
        Append conversation event to Redis Stream.
        
        Args:
            appointment_id: Associated appointment.
            event_type: Type of event (e.g., "greeting", "confirmed", "ended").
            data: Event data.
            
        Returns:
            Stream entry ID.
        """
        self._ensure_connected()
        stream_key = f"conversation:{appointment_id}"
        
        entry = {
            "event_type": event_type,
            "data": json.dumps(data, default=str),
            "timestamp": datetime.now().isoformat()
        }
        
        # MAXLEN keeps stream bounded (last 1000 events)
        entry_id = await self.redis.xadd(
            stream_key,
            entry,
            maxlen=1000
        )
        
        logger.debug(f"Logged event: {event_type} for {appointment_id}")
        return entry_id

    async def get_conversation_events(
        self,
        appointment_id: str,
        count: int = 100
    ) -> list:
        """
        Get recent conversation events for an appointment.
        
        Args:
            appointment_id: Associated appointment.
            count: Maximum number of events to return.
            
        Returns:
            List of event dictionaries.
        """
        self._ensure_connected()
        stream_key = f"conversation:{appointment_id}"
        
        # Read last N entries
        entries = await self.redis.xrevrange(stream_key, count=count)
        
        events = []
        for entry_id, entry_data in entries:
            event = {
                "id": entry_id,
                "event_type": entry_data.get("event_type"),
                "timestamp": entry_data.get("timestamp"),
                "data": json.loads(entry_data.get("data", "{}"))
            }
            events.append(event)
        
        return list(reversed(events))  # Chronological order

    # ==================== Distributed Locking ====================

    @asynccontextmanager
    async def lock(
        self, 
        resource: str, 
        timeout: float = 10.0
    ):
        """
        Distributed lock for coordinating across workers.
        
        Usage:
            async with state.lock(f"call:{appointment_id}"):
                # Only one worker can execute this at a time
                await make_call()
        
        Args:
            resource: Lock name/identifier.
            timeout: Lock timeout in seconds.
        """
        self._ensure_connected()
        lock_key = f"lock:{resource}"
        lock = Lock(self.redis, lock_key, timeout=timeout)
        
        try:
            acquired = await lock.acquire(blocking=True, blocking_timeout=timeout)
            if not acquired:
                raise TimeoutError(f"Could not acquire lock: {resource}")
            logger.debug(f"Lock acquired: {resource}")
            yield
        finally:
            try:
                await lock.release()
                logger.debug(f"Lock released: {resource}")
            except Exception:
                pass  # Lock may have expired

    # ==================== Pub/Sub for Notifications ====================

    async def publish_status_update(
        self,
        appointment_id: str,
        new_status: str,
        changed_by: str
    ) -> int:
        """
        Publish appointment status update to other workers.
        
        Args:
            appointment_id: Updated appointment.
            new_status: New status value.
            changed_by: Who made the change.
            
        Returns:
            Number of subscribers that received the message.
        """
        self._ensure_connected()
        message = json.dumps({
            "appointment_id": appointment_id,
            "status": new_status,
            "changed_by": changed_by,
            "timestamp": datetime.now().isoformat()
        })
        
        subscribers = await self.redis.publish("appointment_updates", message)
        logger.debug(f"Published status update: {appointment_id} → {new_status}")
        return subscribers

    # ==================== Call Metrics ====================

    async def increment_call_metric(
        self,
        metric: str,
        value: int = 1
    ) -> int:
        """
        Increment a call metric counter.
        
        Args:
            metric: Metric name (e.g., "confirmed", "cancelled").
            value: Amount to increment by.
            
        Returns:
            New counter value.
        """
        self._ensure_connected()
        key = f"metrics:calls:{metric}"
        return await self.redis.incrby(key, value)

    async def get_call_metrics(self) -> Dict[str, int]:
        """
        Get all call metrics.
        
        Returns:
            Dictionary of metric_name: count.
        """
        self._ensure_connected()
        
        metrics = {}
        metric_names = ["confirmed", "cancelled", "rescheduled", "no_response", "total"]
        
        for metric in metric_names:
            key = f"metrics:calls:{metric}"
            value = await self.redis.get(key)
            metrics[metric] = int(value) if value else 0
        
        return metrics


# Singleton instance management
_state_instance: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """
    Get the singleton StateManager instance.
    
    Returns:
        StateManager: The shared state manager.
        
    Raises:
        ValueError: If REDIS_URL is not set.
    """
    global _state_instance
    if _state_instance is None:
        _state_instance = StateManager()
    return _state_instance


async def init_state_manager() -> StateManager:
    """
    Initialize and connect to Redis.
    
    Convenience function for application startup.
    
    Returns:
        Connected StateManager instance.
    """
    state = get_state_manager()
    await state.connect()
    return state
