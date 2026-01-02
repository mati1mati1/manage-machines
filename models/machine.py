
from dataclasses import dataclass, field

from models.enums.machineStatus import MachineStatus


@dataclass
class Machine:
    id: int
    name: str
    ip_address: str
    status: MachineStatus = field(default=MachineStatus.DOWN) 