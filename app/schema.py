from dataclasses import dataclass
from typing import Literal

Shape = Literal["A", "B", "C", "D"]
Confidence = Literal["LOW", "MEDIUM", "HIGH"]
Decision = Literal["CONFIRM", "REJECT", "INCONCLUSIVE", "ERROR"]

@dataclass
class Lead:
	index: int
	shape: Shape
	text: str
	evidence: str
	confidence: Confidence
	source_uid: str | None = None
	sink_uid: str | None = None