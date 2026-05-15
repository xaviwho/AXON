from enum import Enum


class SensorType(str, Enum):
    GAS = "gas"
    THERMAL = "thermal"
    ENV = "env"
    EQUIPMENT = "equipment"


class LatencyClass(str, Enum):
    URLLC = "URLLC"
    EMBB = "eMBB"
    MMTC = "mMTC"


class PermissionLevel(str, Enum):
    OPERATOR = "operator"
    ADMIN = "admin"
    SYSTEM = "system"


class ActionEffect(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
