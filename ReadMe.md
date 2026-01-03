# Distributed Machine Management System - Project Summary

## 📋 Project Overview

This project implements a **scalable distributed machine management system** capable of handling 10,000+ remote machines. It uses **asyncio** for concurrent operations, **Redis** for persistent state and task queuing, and **Docker** for containerization and multi-instance deployment.

### Core Objective
Provide a centralized server that can:
1. Accept machine IP addresses from clients
2. Store machine state persistently in Redis
3. Distribute control tasks (turn ON/OFF) to distributed workers
4. Scale horizontally by adding more worker containers

---

## 🏗️ Architecture

### System Design Pattern: Producer-Consumer with Redis Queue

```
┌─────────────┐
│   Clients   │ (TCP connections)
│  (IPs list) │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│   Server (main.py)              │
│ • Accepts TCP connections       │
│ • Parses IP addresses           │
│ • Stores machines in Redis      │
│ • Queues START tasks to Redis   │
└──────────┬──────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│       Redis (7.4.7-alpine)           │
│ ┌────────────────────────────────┐  │
│ │ • Persistent Queue             │  │
│ │   - tasks_queue (list)         │  │
│ │ • Atomic Counters              │  │
│ │   - next_machine_id (INCR)     │  │
│ │   - task_id_counter (INCR)     │  │
│ │ • Machine State Storage        │  │
│ │   - machine:{id} (hashes)      │  │
│ │ • Pub/Sub (shutdown signals)   │  │
│ └────────────────────────────────┘  │
└────┬──────────────────────────────┬──┘
     │                              │
     ▼                              ▼
┌─────────────────┐        ┌─────────────────┐
│ Worker Pool 1   │        │ Worker Pool 2   │
│ (50 workers)    │        │ (50 workers)    │
│ • Consume tasks │        │ • Consume tasks │
│ • Update status │        │ • Update status │
│ • Queue STOP    │        │ • Queue STOP    │
└─────────────────┘        └─────────────────┘
```

---

## 🔄 Asyncio - Asynchronous Concurrency Model

### Core Async Patterns Used

#### 1. **AsyncIO Server (TCP Connection Handling)**
```python
# main.py: Start TCP server listening on all interfaces
server = await asyncio.start_server(
    lambda r, w: handle_client(r, w, state), 
    host="0.0.0.0", 
    port=8888
)
async with server:
    await state.shutdown_event.wait()
```

**Key Concept**: `asyncio.start_server()` creates a non-blocking TCP server that handles multiple concurrent clients without threads.

#### 2. **Async Generator for I/O Operations**
```python
# main.py: Read client data asynchronously
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: AppState):
    data = await reader.readline()  # Non-blocking wait for data
    line = data.decode("utf-8")
    await write_line(writer, "OK AsyncLab ready")  # Non-blocking write
```

**Key Concept**: `StreamReader.readline()` and `StreamWriter.drain()` allow reading/writing without blocking the event loop.

#### 3. **Async Context Managers**
```python
# main.py: Async context manager for server lifecycle
async with server:
    print(f"✓ Server listening on {host}:{port}")
    await state.shutdown_event.wait()
```

**Key Concept**: The `async with` statement ensures proper cleanup when the context exits.

#### 4. **Concurrent Task Creation with asyncio.create_task()**
```python
# workers.py: Spawn multiple worker tasks
async def start_workers(state: AppState, num_workers: int) -> List[asyncio.Task]:
    tasks: List[asyncio.Task] = []
    for i in range(num_workers):
        tasks.append(asyncio.create_task(worker_loop(state)))  # Fire-and-forget
    return tasks
```

**Key Concept**: `asyncio.create_task()` schedules a coroutine to run concurrently without waiting for it. This creates 50-100+ concurrent workers per container.

#### 5. **Event-Based Synchronization**
```python
# appState.py: Async events for coordination
@dataclass
class AppState:
    system_ready: asyncio.Event = field(default_factory=asyncio.Event)
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

# main.py: Wait for shutdown signal
await state.shutdown_event.wait()
```

**Key Concept**: `asyncio.Event` allows tasks to wait for signals from other tasks without blocking.

#### 6. **Task Timeout Handling**
```python
# workers.py: Timeout for Redis BRPOP (blocking pop)
try:
    task_data = await asyncio.wait_for(
        state.redis.brpop("tasks_queue", timeout=1),
        timeout=1.1
    )
except asyncio.TimeoutError:
    continue  # Loop back, check for shutdown
```

**Key Concept**: `asyncio.wait_for()` sets a deadline; if the operation exceeds it, raises `TimeoutError`.

#### 7. **Task Cancellation and Cleanup**
```python
# workers.py: Graceful worker shutdown
async def stop_workers(worker_tasks: List[asyncio.Task]) -> None:
    for t in worker_tasks:
        t.cancel()  # Signal cancellation
    
    for t in worker_tasks:
        try:
            await t  # Wait for cancellation to complete
        except asyncio.CancelledError:
            pass  # Expected exception
```

**Key Concept**: `Task.cancel()` and catching `asyncio.CancelledError` provide graceful shutdown.

#### 8. **Running the Event Loop**
```python
# main.py: Entry point
if __name__ == "__main__":
    try:
        asyncio.run(main())  # Create event loop and run main()
    except KeyboardInterrupt:
        print("Shutting down...")
```

**Key Concept**: `asyncio.run()` creates a fresh event loop, runs the coroutine, and closes the loop. This is the modern (Python 3.7+) way to start async code.

### Asyncio Benefits in This Project
| Feature | Benefit |
|---------|---------|
| Non-blocking I/O | Server handles 1000s of concurrent client connections without threads |
| Memory Efficient | 50 workers per container = minimal overhead vs 50 threads |
| Easy Concurrency | `await` syntax is clearer than callback chains |
| Built-in Coordination | `asyncio.Event`, `asyncio.Lock`, `asyncio.Condition` for inter-task communication |
| Timeout Control | Can set deadlines on any async operation |

---

## 🔴 Redis - Distributed State & Task Queue

### Redis Architecture Diagram
```
┌─────────────────────────────────────────────────────────────┐
│                    Redis Database (7.4.7)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Data Structures:                                           │
│                                                              │
│  1. ATOMIC COUNTERS (for unique IDs)                       │
│     ├── next_machine_id (int)      → 0, 1, 2, ...         │
│     └── task_id_counter (int)      → 0, 1, 2, ...         │
│                                                              │
│  2. TASK QUEUE (FIFO list for producer-consumer)          │
│     └── tasks_queue (list)                                 │
│         ├── {id: 1, machine_id: 5, command: "START"}      │
│         ├── {id: 2, machine_id: 6, command: "START"}      │
│         └── {id: 3, machine_id: 5, command: "STOP"}       │
│                                                              │
│  3. MACHINE STATE STORAGE (persistent hashes)              │
│     ├── machine:1 (hash)                                   │
│     │   ├── id → "1"                                       │
│     │   ├── ip_address → "192.168.1.1"                   │
│     │   ├── name → ""                                      │
│     │   └── status → "UP" or "DOWN"                        │
│     ├── machine:2 (hash)                                   │
│     └── machine:N (hash)                                   │
│                                                              │
│  4. PUB/SUB CHANNELS (for shutdown signals)               │
│     └── shutdown (channel)                                 │
│         └── Message: "1" → all workers receive            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Key Redis Operations Used

#### 1. **Atomic Counter - INCR (Increment)**
```python
# main.py: Generate unique machine ID atomically
m.id = int(await state.redis.incr("next_machine_id"))
# Returns: 1, then 2, then 3, etc. (thread-safe across all containers)

# Generate unique task ID
tid = int(await state.redis.incr("task_id_counter"))
```

**Why Redis INCR?**
- Atomic operation: No race conditions even with multiple servers/workers
- Distributed: Works across all containers sharing the same Redis instance
- Fast: Single-command operation, O(1) time complexity

#### 2. **Hash Storage - HSET (Set Hash Fields)**
```python
# main.py: Store complete machine record
await state.redis.hset(
    f"machine:{m.id}",  # Hash key: "machine:1", "machine:2", etc.
    mapping={
        "id": str(m.id),
        "ip_address": m.ip_address,
        "name": m.name or "",
        "status": MachineStatus.DOWN.value  # "DOWN" as string
    }
)
```

**Why Hashes?**
- Structured data: Each machine record has multiple fields
- Efficient updates: Can update just the "status" field without rewriting entire record
- Memory efficient: Hashes use less memory than separate string keys
- Atomic updates: Full record written as single operation

#### 3. **Hash Retrieval - HGETALL (Get All Hash Fields)**
```python
# workers.py: Retrieve machine record from Redis
machine_data = await state.redis.hgetall(f"machine:{machine_id}")
# Returns: {b"id": b"1", b"ip_address": b"192.168.1.1", b"status": b"UP"}

if not machine_data:
    return f"error: machine {machine_id} not found"

current_status = machine_data.get(b"status", b"").decode("utf-8")
```

**Key Detail**: Redis returns bytes, not strings. Must `.decode("utf-8")` to convert.

#### 4. **Hash Field Update - HSET (Single Field)**
```python
# workers.py: Update just the status field after machine turns ON
await state.set_machine_status(machine_id, MachineStatus.UP.value)

# Implementation in appState.py:
async def set_machine_status(self, machine_id: int, status: str) -> None:
    await self.redis.hset(f"machine:{machine_id}", "status", status)
```

**Why Direct Field Update?**
- Doesn't require reading entire record first
- Atomic: Only the status field is updated
- Efficient: Other fields remain unchanged

#### 5. **Queue Operations - LPUSH (Left Push)**
```python
# main.py & workers.py: Queue task to Redis list
task_json = json.dumps({
    "id": tid,
    "machine_id": m.id,
    "command": "START"  # String, not enum object
})
await state.redis.lpush("tasks_queue", task_json)
```

**Why JSON Strings?**
- Redis stores arbitrary strings; must serialize Python objects to JSON
- String enums ("START", "STOP") instead of enum objects (serialization issue)
- Worker deserializes with `json.loads()` and converts string back to enum

#### 6. **Blocking Queue Pop - BRPOP (Right Pop with Blocking)**
```python
# workers.py: Wait for tasks (blocking, non-busy-wait)
task_data = await asyncio.wait_for(
    state.redis.brpop("tasks_queue", timeout=1),
    timeout=1.1
)

if task_data:
    task_dict = json.loads(task_data[1])  # Deserialize JSON
    task_dict["command"] = TaskType(task_dict["command"])  # "START" → TaskType.START
    task = Task(**task_dict)
    await process_tasks(state, task)
```

**Why BRPOP Instead of Polling?**
- **Blocking**: Worker waits until task available (no CPU spinning)
- **Timeout=1**: If no task in 1 second, return None (allows checking shutdown signal)
- **Efficient**: Single operation handles 50 workers without hammering Redis

#### 7. **Pub/Sub - SUBSCRIBE (Listen for Messages)**
```python
# workers.py: Subscribe to shutdown channel
pubsub = state.redis.pubsub()
await pubsub.subscribe("shutdown")

while True:
    message = await pubsub.get_message()
    if message and message["data"] == b"1":
        print("Shutdown signal received")
        break
```

**Why Pub/Sub?**
- **Publish from anywhere**: `redis.publish("shutdown", "1")` reaches all subscribers instantly
- **No polling**: Subscribers notified immediately, not checking repeatedly
- **Scalable**: Can have 100s of subscribers; Redis handles it

#### 8. **Publishing Shutdown Signal - PUBLISH**
```python
# main.py: Broadcast shutdown to all workers
await state.redis.publish("shutdown", "1")
```

**Effect**: All workers receive message and exit gracefully.

### Redis Data Flow Example (50 Machines)

**Step 1: Server receives IPs**
```
Client → Server: "192.168.1.1, 192.168.1.2, ..., 192.168.1.50"
```

**Step 2: Server stores in Redis & queues tasks**
```
For each machine i (1-50):
  HSET machine:i {id, ip_address, name, status="DOWN"}
  LPUSH tasks_queue {id, machine_id=i, command="START"}

Redis State After:
  machine:1 through machine:50 hashes (50 machines)
  tasks_queue with 50 START tasks (LIFO)
```

**Step 3: Workers consume & process**
```
Worker1: BRPOP tasks_queue → Gets task for machine:1, runs turn_on_machine()
Worker2: BRPOP tasks_queue → Gets task for machine:2, runs turn_on_machine()
...
Worker50: BRPOP tasks_queue → Gets task for machine:50, runs turn_on_machine()

Each worker:
  1. HGETALL machine:N (get current state)
  2. Sleep 1 second
  3. HSET machine:N status="UP" (update state)
  4. LPUSH tasks_queue {machine_id=N, command="STOP"} (queue next task)
```

**Step 4: STOP tasks processed similarly**
```
Workers consume STOP tasks in round-robin fashion
For each STOP task:
  1. HGETALL machine:N (verify status)
  2. Sleep 1 second
  3. HSET machine:N status="DOWN" (final state)

Final Redis State:
  machine:1 through machine:50 all have status="DOWN"
  tasks_queue is empty
```

### Redis Benefits
| Operation | Benefit |
|-----------|---------|
| INCR | Atomic ID generation (no duplicates across servers) |
| HSET/HGETALL | Structured machine records with efficient field updates |
| LPUSH/BRPOP | Reliable queue: works if workers crash/restart |
| PUBLISH | Instant shutdown signal to all workers (no polling) |
| Persistence | Machine state survives container restarts (via RDB) |

---

## 🐳 Docker - Containerization & Orchestration

### Dockerfile - Build Container Image

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1
CMD ["./entrypoint.sh"]
```

**Key Settings**:
- **python:3.11-slim**: Minimal Python image (without unnecessary system packages)
- **PYTHONUNBUFFERED=1**: Critical! Forces Python to write logs immediately (not buffered)
  - Without this, logs appear delayed or not at all in Docker
- **--no-cache-dir**: Don't cache pip packages (reduces image size)
- **entrypoint.sh**: Custom startup script (sets environment, runs Python)

### docker-compose.yml - Multi-Container Orchestration

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
```

**Redis Service**:
- **7-alpine**: Lightweight Alpine Linux base (small image)
- **Port 6379**: Default Redis port, exposed to host
- **redis_data volume**: Persists data if container restarts (RDB snapshots)

```yaml
  main_instance_1:
    build: .
    ports:
      - "8888:8888"
    environment:
      - REDIS_URL=redis://redis:6379
      - ROLE=server
    depends_on:
      - redis
```

**Server Service**:
- **build: .**: Build from local Dockerfile
- **Port 8888**: Server listens here
- **REDIS_URL=redis://redis:6379**: Internal Docker DNS (name "redis" resolves to Redis container)
- **ROLE=server**: Environment variable tells main.py to start as server
- **depends_on: redis**: Ensures Redis starts before server

```yaml
  worker_instance_1:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - ROLE=worker
      - NUM_WORKERS=50
    depends_on:
      - redis

  worker_instance_2:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - ROLE=worker
      - NUM_WORKERS=50
    depends_on:
      - redis
```

**Worker Services** (2 instances × 50 workers = 100 concurrent workers):
- **ROLE=worker**: Environment variable tells main.py to start as worker
- **NUM_WORKERS=50**: Each container spawns 50 async workers
- **No port mapping**: Workers don't accept TCP; they only consume Redis queue

**Horizontal Scaling**:
To handle 10,000 machines: Add more worker instances
```yaml
  worker_instance_3:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - ROLE=worker
      - NUM_WORKERS=100
```

```yaml
  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --interval 300 --cleanup
```

**Watchtower Service**:
- **Monitors Docker images** every 300 seconds
- **Auto-restarts containers** if image is updated
- Useful for CI/CD: Push new image → Watchtower detects → Containers restart automatically

### Docker Networking

```
┌─────────────────────────────────────────────────────┐
│           Docker Compose Network                     │
│  (Internal bridge network with DNS resolution)       │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Host: "redis" → IP: 172.20.0.2 (example)          │
│  Host: "main_instance_1" → 172.20.0.3              │
│  Host: "worker_instance_1" → 172.20.0.4            │
│  Host: "worker_instance_2" → 172.20.0.5            │
│                                                      │
│  ALL containers can resolve "redis://redis:6379"   │
│  NO need for localhost or IP addresses             │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Docker Commands Cheat Sheet

```bash
# Build containers
docker-compose build --no-cache

# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# View logs
docker-compose logs -f redis              # Follow Redis logs
docker-compose logs -f main_instance_1    # Follow server logs
docker-compose logs -f worker_instance_1  # Follow worker logs

# Execute command in running container
docker exec manage-machines-redis-1 redis-cli KEYS "machine:*"
docker exec manage-machines-redis-1 redis-cli HGETALL machine:1

# Check resource usage
docker stats

# Remove stopped containers and dangling images
docker-compose down --remove-orphans
```

### Docker Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│              Docker Host (macOS)                        │
│                                                         │
│  ┌──────────────────────────────────────────────────┐ │
│  │         Docker Engine                           │ │
│  │  ┌─────────────────────────────────────────┐   │ │
│  │  │  Docker Network: manage-machines        │   │ │
│  │  │  ┌───────┐ ┌───────┐ ┌────────────┐   │   │ │
│  │  │  │Redis  │ │Server │ │Worker x2   │   │   │ │
│  │  │  │:6379  │ │:8888  │ │(async)     │   │   │ │
│  │  │  └───────┘ └───────┘ └────────────┘   │   │ │
│  │  │       ↑       ↑            ↑           │   │ │
│  │  │       └───────┴────────────┘           │   │ │
│  │  │          (RPC via network)             │   │ │
│  │  └─────────────────────────────────────────┘   │ │
│  └──────────────────────────────────────────────────┘ │
│                   ↓ Port Mapping                      │
│  ┌──────────────────────────────────────────────────┐ │
│  │  Host Ports (macOS localhost)                   │ │
│  │    • 6379 → Redis                              │ │
│  │    • 8888 → Server                             │ │
│  └──────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 Data Flow Example: 50 Machines

### Timeline

```
t=0s   Server receives: "192.168.1.1, 192.168.1.2, ..., 192.168.1.50"
       └─→ Stores 50 machines in Redis (status="DOWN")
       └─→ Queues 50 START tasks

t=0-1s Workers pick up START tasks (round-robin across 100 workers)
       └─→ Worker 1: HGETALL machine:1, sleep 1s
       └─→ Worker 2: HGETALL machine:2, sleep 1s
       └─→ ... parallel execution ...
       └─→ Worker 50: HGETALL machine:50, sleep 1s

t=1s   All 50 machines have slept
       └─→ Worker 1: HSET machine:1 status="UP"
       └─→ Worker 2: HSET machine:2 status="UP"
       └─→ ... parallel updates ...
       └─→ Worker 50: HSET machine:50 status="UP"
       └─→ All 50 workers queue STOP tasks

t=1-2s Workers pick up STOP tasks
       └─→ Similar process: read machine, sleep 1s

t=2s   All 50 machines have status="DOWN" (final state)
       └─→ Queue empty
       └─→ System ready for next batch

Total Time: ~2 seconds for 50 machines (not 50s!) due to parallelism
```

---

## 🔑 Key Design Decisions

| Decision | Reasoning |
|----------|-----------|
| Asyncio instead of threads | Lower memory (50 workers/container), cleaner code, no GIL contention |
| Redis hashes for machines | Efficient field updates, atomic writes, supports persistence |
| JSON serialization of enums | JSON doesn't support Python enums; convert to strings for transmission |
| BRPOP with timeout | Workers sleep without spinning; timeout allows checking shutdown signal |
| Pub/Sub for shutdown | Instant broadcast vs. polling all containers |
| Docker multi-instance | Horizontal scaling; add workers without modifying server logic |
| PYTHONUNBUFFERED=1 | Essential for real-time Docker logs (default buffered output) |
| 0.0.0.0 server binding | Listen on all interfaces (inside Docker container) |

---

## 📈 Scalability Path

| Scale | Configuration |
|-------|---------------|
| 1K machines | 1 server, 2 workers × 50 workers = 100 concurrent |
| 10K machines | 1 server, 5 workers × 100 workers = 500 concurrent |
| 100K machines | 3 servers (load-balanced), 20 workers × 100 = 2000 concurrent |

Redis (single instance) can handle millions of operations/sec. The bottleneck is typically network bandwidth or worker processing speed.

---

## 🚀 Quick Start

```bash
# Build and run the system
docker-compose up -d

# Verify all containers running
docker-compose ps

# Send 50 test machines
bash -c '(echo "192.168.1.1, 192.168.1.2, ..., 192.168.1.50"; sleep 5) | nc localhost 8888'

# Watch worker processing
docker-compose logs -f worker_instance_1

# Check final Redis state
docker exec manage-machines-redis-1 redis-cli KEYS "machine:*" | wc -l
```

---

## 📚 Technology Stack Summary

| Technology | Purpose | Version | Link |
|-----------|---------|---------|------|
| Python | Core language | 3.11 | https://www.python.org/ |
| asyncio | Async I/O library | Built-in | https://docs.python.org/3/library/asyncio.html |
| redis[asyncio] | Redis async client | 4.5.0+ | https://github.com/redis/redis-py |
| Redis | Distributed queue & storage | 7.4.7 | https://redis.io/ |
| Docker | Containerization | Latest | https://www.docker.com/ |
| docker-compose | Orchestration | 3.8 | https://docs.docker.com/compose/ |
| Watchtower | Auto-update | Latest | https://containrrr.dev/watchtower/ |

---

## 🎯 Summary

This project demonstrates a production-ready distributed system using:

1. **Asyncio**: Handles 100+ concurrent tasks with minimal overhead
2. **Redis**: Decouples server from workers via reliable queue + persistent state
3. **Docker**: Enables seamless horizontal scaling (add more worker containers)

The combination provides **high concurrency**, **fault tolerance** (workers can restart without losing tasks), and **horizontal scalability** (handle 10K+ machines by adding containers).
