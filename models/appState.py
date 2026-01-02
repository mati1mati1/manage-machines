from dataclasses import dataclass, field
import asyncio
from typing import Dict

from models.machine import Machine
from models.task import Task


@dataclass
class AppState:
    system_ready: asyncio.Event = field(default_factory=asyncio.Event)
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    machines: Dict[int, Machine] = field(default_factory=dict)
    machines_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    next_machine_id: int = 1
    id_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    tasks_to_run: asyncio.Queue[Task] = field(default_factory=asyncio.Queue)
    task_id_counter: int = 1
    task_id_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    running_tasks: Dict[int, asyncio.Task] = field(default_factory=dict)
    running_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # external concurrency limiter (נשתמש בשלב הבא)
    external_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(5))
