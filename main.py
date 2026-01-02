import asyncio
import sys
from typing import List

from models import machine
from models.appState import AppState
from models.task import Task
from models.enums.taskType import TaskType
from workers import start_workers, stop_workers

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
                async with state.id_lock:
                    m.id = state.next_machine_id
                    state.next_machine_id += 1
                async with state.machines_lock:
                    state.machines[m.id] = m
                async with state.task_id_lock:
                    tid = state.task_id_counter
                    state.task_id_counter += 1
                await state.tasks_to_run.put(Task(
                    id=tid,
                    machine_id=m.id,
                    command=TaskType.START
                ))    
                await write_line(writer, f"OK MACHINE_ADDED {m.id} {m.ip_address}")

    except asyncio.CancelledError:
        raise
    except Exception as ex:
        # לא נקריס שרת בגלל קליינט
        try:
            await write_line(writer, f"ERR INTERNAL {ex}")
            await write_line(writer, f"ERR INTERNAL {type(ex).__name__}")
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def run_server(host: str = "127.0.0.1", port: int = 8888) -> None:
    state = AppState()

    worker_tasks = await start_workers(state, num_workers=4)
    state.system_ready.set()


    server = await asyncio.start_server(lambda r, w: handle_client(r, w, state), host, port)

    async with server:
        # ריצה עד שמישהו שולח SHUTDOWN או Ctrl+C
        await state.shutdown_event.wait()
        # ביטול כל jobs שרצים עכשיו (כדי לא להשאיר משימות תלויות)
        async with state.running_lock:
            running = list(state.running_tasks.values())
        for t in running:
            t.cancel()

        # Grace קצר
        try:
            await asyncio.wait_for(asyncio.gather(*running, return_exceptions=True), timeout=2.0)
        except asyncio.TimeoutError:
            pass

        await stop_workers(worker_tasks)



async def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "8888"
    ip = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    await run_server(host=ip, port=int(port))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
