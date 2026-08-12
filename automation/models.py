from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Condition:
    """
    Represents a single rule condition.
    Example:
        field="lead_score"
        operator=">"
        value=80
    """

    field: str
    operator: str
    value: Any


@dataclass
class Action:
    """
    Represents an action to execute.
    Example:
        name="create_followup"
        params={"days": 2}
    """

    name: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutomationRule:
    """
    Complete automation rule.
    """

    id: str
    name: str
    enabled: bool = True

    conditions: List[Condition] = field(default_factory=list)

    actions: List[Action] = field(default_factory=list)

    stop_after_match: bool = False

    description: str = ""