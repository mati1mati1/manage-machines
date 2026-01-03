from dataclasses import dataclass, field
import asyncio
from typing import Dict, Optional
import redis.asyncio as aioredis

from models.machine import Machine
from models.task import Task


@dataclass
class AppState:
    system_ready: asyncio.Event = field(default_factory=asyncio.Event)
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    redis: aioredis.Redis = None
    machines: Dict[int, Machine] = field(default_factory=dict)
    machines_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_machine(self, machine_id: int) -> Optional[dict]:
        machine_data = await self.redis.hgetall(f"machine:{machine_id}")
        if not machine_data:
            return None
        return machine_data
        
    async def set_machine_status(self, machine_id: int, status: str) -> None:
        await self.redis.hset(f"machine:{machine_id}", "status", status)

