from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass(frozen=True)
class Config:

	# Application
	app_name: str = "VulnSwarm"
	work_dir: Path = Path(".vulnswarm")

	# Neo4j
	neo4j_url: str = "neo4j://127.0.0.1:7687"
	neo4j_user: str = "neo4j"
	neo4j_password: str = "neo4jneo4j"

	chunk_size: int = 5000
	persist_concurrency: int = 4

	# Joern
	joern_binary: str = "joern-parse.bat"

	# Model
	model_provider: str = "lm-studio"
	model_name: str = "qwen2.5-coder"

	@classmethod
	def from_env(cls) -> "Config":
		return cls(
			neo4j_url=os.getenv("NEO4J_URI", cls.neo4j_url),
			neo4j_user=os.getenv("NEO4J_USER", cls.neo4j_user),
			neo4j_password=os.getenv("NEO4J_PASSWORD", cls.neo4j_password),
			joern_binary=os.getenv("JOERN_BINARY", cls.joern_binary),
			model_provider=os.getenv("MODEL_PROVIDER", cls.model_provider),
			model_name=os.getenv("MODEL_NAME", cls.model_name),
			work_dir=Path(os.getenv("WORK_DIR", cls.work_dir)),
			chunk_size=int(os.getenv("CHUNK_SIZE", cls.chunk_size)),
			persist_concurrency=int(os.getenv("PERSIST_CONCURRENCY", cls.persist_concurrency))
		)

	def ensure_directories(self) -> None:
		self.work_dir.mkdir(parents=True, exist_ok=True)