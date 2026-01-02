

from dataclasses import dataclass
from models.enums.taskType import TaskType

@dataclass
class Task:
    id: int
    machine_id: int
    command: TaskType