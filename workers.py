import asyncio
import hashlib
import random
from datetime import datetime, timezone
from typing import List, Optional

from models.appState import AppState
from models.enums.machineStatus import MachineStatus
from models.enums.taskType import TaskType
from models.task import Task




async def do_sleep(payload: str) -> str:
    ms = int(payload.strip())
    await asyncio.sleep(ms / 1000.0)
    return f"slept:{ms}ms"

async def turn_on_machine(machine_id: int, state: AppState) -> str:
    async with state.machines_lock:
        machine = state.machines.get(machine_id)
        if machine is None:
            return f"error: machine {machine_id} not found"
        if machine.status == MachineStatus.UP:
            return f"machine {machine_id} already ON"
        
    await do_sleep("1000") 

    async with state.machines_lock:
        machine = state.machines.get(machine_id)  # Re-fetch
        if machine:
            machine.status = MachineStatus.UP
    return f"machine {machine_id} turned ON"

async def turn_off_machine(machine_id: int, state: AppState) -> str:
    async with state.machines_lock:
        machine = state.machines.get(machine_id)
        if machine is None:
            return f"error: machine {machine_id} not found"
        if machine.status == MachineStatus.DOWN:
            return f"machine {machine_id} already OFF"
        
    await do_sleep("1000")  
    async with state.machines_lock:
        machine = state.machines.get(machine_id)  
        if machine:
            machine.status = MachineStatus.DOWN
    return f"machine {machine_id} turned OFF"
      


async def process_tasks(state: AppState, task: Task) -> None:
    try:
        print(f"Processing task {task.id}: {task.command} on machine {task.machine_id}")
        if task.command == TaskType.START:
            result = await turn_on_machine(task.machine_id, state)
            async with state.task_id_lock:
                tid = state.task_id_counter
                state.task_id_counter += 1
            await state.tasks_to_run.put(Task(
                id=tid,
                machine_id=task.machine_id,
                command=TaskType.STOP
            ))
        elif task.command == TaskType.STOP:
            result = await turn_off_machine(task.machine_id, state)
        else:
            result = f"error: unknown command {task.command}"
        print(f"Task {task.id} completed: {result}")   
    except Exception as e:
        print(f"Error processing task {task.id}: {e}")
        return

async def worker_loop(state: AppState) -> None:
    while not state.shutdown_event.is_set():
        try:
            task_obj = await asyncio.wait_for(state.tasks_to_run.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        try:
            task = asyncio.create_task(process_tasks(state, task_obj))
            async with state.running_lock:
                state.running_tasks[task_obj.id] = task

            try:
                await task
            finally:
                async with state.running_lock:
                    state.running_tasks.pop(task_obj.id, None)
        finally:
            state.tasks_to_run.task_done()

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
