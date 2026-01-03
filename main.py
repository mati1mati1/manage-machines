import asyncio
from models.enums.machineStatus import MachineStatus
import redis.asyncio as aioredis
import json
import os
import sys
from typing import List

from models import machine
from models.appState import AppState
from models.task import Task
from models.enums.taskType import TaskType
from workers import run_workers_only, start_workers, stop_workers

async def write_line(writer: asyncio.StreamWriter, line: str) -> None:
    writer.write((line + "\n").encode("utf-8"))
    await writer.drain()

def parse_machines_ip(line: str) -> List[machine.Machine]:
    line = line.strip()
    if not line:
        raise ValueError("Empty command")
    machines = []
    ips = line.split(",")
    for ip in ips:
        ip = ip.strip()
        if not ip:
            continue
        machines.append(machine.Machine(id=0, name="", ip_address=ip))
    return machines


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: AppState) -> None:

    try:
        await write_line(writer, "OK AsyncLab ready. Type HELP.")

        while not state.shutdown_event.is_set():
            data = await reader.readline()
            if not data:
                break 

            line = data.decode("utf-8", errors="replace")
            try:
                machines = parse_machines_ip(line)

            except ValueError:
                await write_line(writer, "ERR INVALID_COMMAND")
                continue


            
            for m in machines:
                m.id = int(await state.redis.incr("next_machine_id"))
                try:
                    await state.redis.hset(
                        f"machine:{m.id}", 
                        mapping={
                            "id": str(m.id),
                            "ip_address": m.ip_address,
                            "name": m.name or "",
                            "status": MachineStatus.DOWN.value
                        }
                    )
                    print(f"✓ Stored machine:{m.id} in Redis", flush=True)
                except Exception as e:
                    print(f"✗ Failed to store machine:{m.id}: {e}", flush=True)
                    
                tid = int(await state.redis.incr("task_id_counter"))
                task_json = json.dumps({
                    "id": tid,
                    "machine_id": m.id,
                    "command": "START"  # Use string directly
                })
                await state.redis.lpush("tasks_queue", task_json)
                await write_line(writer, f"OK MACHINE_ADDED {m.id} {m.ip_address}")

    except asyncio.CancelledError:
        raise
    except Exception as ex:
        # לא נקריס שרת בגלל קליינט
        import traceback
        try:
            await write_line(writer, f"ERR INTERNAL {ex}")
            await write_line(writer, f"ERR INTERNAL {type(ex).__name__}")
            await write_line(writer, f"ERR INTERNAL {traceback.format_exc()}")
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle_shutdown(state: AppState) -> None:
    """Publish shutdown signal to Redis"""
    await state.redis.publish("shutdown", "1")
    state.shutdown_event.set()

async def run_server(host: str = "0.0.0.0", port: int = 8888) -> None:
    state = AppState()
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    try:
        state.redis = await aioredis.from_url(redis_url)
        print(f"✓ Connected to Redis: {redis_url}")
    except Exception as e:
        print(f"✗ Failed to connect to Redis: {e}")
        return
    
    print(f"Starting server on {host}:{port}")
    server = await asyncio.start_server(lambda r, w: handle_client(r, w, state), host, port)

    async with server:
        print(f"✓ Server listening on {host}:{port}")
        await state.shutdown_event.wait()
        print("Broadcasting shutdown signal to workers...")
        
        await state.redis.publish("shutdown", "1")
        await asyncio.sleep(2.0)



async def main() -> None:
    role = os.getenv("ROLE", "server")
    port = sys.argv[1] if len(sys.argv) > 1 else "8888"
    ip = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
    print(f"Starting in role: {role}")
    
    try:
        if role == "server":
            await run_server(host=ip, port=int(port))
        elif role == "worker":
            from models.appState import AppState
            state = AppState()
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            try:
                state.redis = await aioredis.from_url(redis_url)
                print(f"✓ Worker connected to Redis: {redis_url}")
            except Exception as e:
                print(f"✗ Worker failed to connect to Redis: {e}")
                return
            num_workers = int(os.getenv("NUM_WORKERS", "4"))
            print(f"Starting {num_workers} workers...")
            await run_workers_only(state, num_workers)
        else:
            print(f"Unknown role: {role}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
        pass
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()