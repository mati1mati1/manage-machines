import asyncio
import hashlib
import json
import random
from datetime import datetime, timezone
from typing import List, Optional

from models import task
from models.appState import AppState
from models.enums.machineStatus import MachineStatus
from models.enums.taskType import TaskType
from models.machine import Machine
from models.task import Task


async def do_sleep(payload: str) -> str:
    ms = int(payload.strip())
    await asyncio.sleep(ms / 1000.0)
    return f"slept:{ms}ms"

async def turn_on_machine(machine_id: int, state: AppState) -> str:
    machine_data = await state.get_machine(machine_id)
    print(f"DEBUG: get_machine({machine_id}) returned: {machine_data} (type: {type(machine_data)})", flush=True)
    if not machine_data:
        return f"error: machine {machine_id} not found"
    
    current_status = machine_data.get(b"status", b"").decode("utf-8")
    if current_status == MachineStatus.UP.value:
        return f"machine {machine_id} already ON"
    
    await do_sleep("10000")
    
    await state.set_machine_status(machine_id, MachineStatus.UP.value)
    return f"machine {machine_id} turned ON"
    

async def turn_off_machine(machine_id: int, state: AppState) -> str:
    machine_data = await state.get_machine(machine_id)
    if not machine_data:
        return f"error: machine {machine_id} not found"
    
    current_status = machine_data.get(b"status", b"").decode("utf-8")
    if current_status == MachineStatus.DOWN.value:
        return f"machine {machine_id} already OFF"
    
    await do_sleep("1000")
    
    await state.set_machine_status(machine_id, MachineStatus.DOWN.value)
    return f"machine {machine_id} turned OFF"

      


async def process_tasks(state: AppState, task: Task) -> None:
    try:
        print(f"Processing task {task.id}: {task.command} on machine {task.machine_id}")
        if task.command == TaskType.START:
            result = await turn_on_machine(task.machine_id, state)
            tid = int(await state.redis.incr("task_id_counter"))
            await state.redis.lpush("tasks_queue", json.dumps({
                "id": tid,
                "machine_id": task.machine_id,
                "command": "STOP"  # Use string
            }))
        elif task.command == TaskType.STOP:
            result = await turn_off_machine(task.machine_id, state)
        else:
            result = f"error: unknown command {task.command}"
        print(f"Task {task.id} completed: {result}")   
    except Exception as e:
        print(f"Error processing task {task.id}: {e}")
        return

async def worker_loop(state: AppState) -> None:
    pubsub = state.redis.pubsub()
    await pubsub.subscribe("shutdown")
    
    while True:
        message = await pubsub.get_message()
        if message and message["data"] == b"1":
            print("Shutdown signal received")
            break
        
        try:
            task_data = await asyncio.wait_for(
                state.redis.brpop("tasks_queue", timeout=1),
                timeout=1.1
            )
            if task_data:
                task_dict = json.loads(task_data[1])
                # Convert string command to enum
                if isinstance(task_dict["command"], str):
                    task_dict["command"] = TaskType(task_dict["command"])
                task = Task(**task_dict)
                await process_tasks(state, task)

        except asyncio.TimeoutError:
            continue

async def start_workers(state: AppState, num_workers: int) -> List[asyncio.Task]:
    tasks: List[asyncio.Task] = []
    for i in range(num_workers):
        tasks.append(asyncio.create_task(worker_loop(state)))
    return tasks


async def stop_workers(worker_tasks: List[asyncio.Task]) -> None:
    for t in worker_tasks:
        t.cancel()

    for t in worker_tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass


async def run_workers_only(state: AppState, num_workers: int) -> None:
    """Run worker-only mode (no server)"""
    worker_tasks = await start_workers(state, num_workers)
    state.system_ready.set()
    
    try:
        await state.shutdown_event.wait()
    finally:
        await stop_workers(worker_tasks)
