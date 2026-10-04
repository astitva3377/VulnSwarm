from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=Path(__file__).parent.parent.resolve() / '.env')

@dataclass(frozen=True)
class EmbedderConfig:
	model: str = "jinaai/jina-embeddings-v2-base-code"
	provider: str | None = None
	base_url: str | None = None
	api_key: str | None = None
	device: str = 'cpu'
	dimensions: int | None = None # if not set and provider is OpenAI compliant: sends a single character to find dimensions
	hf_home: Path | None = None

	@classmethod
	def from_env(cls) -> "EmbedderConfig":
		return cls(
			model=os.getenv("EMBEDDING_MODEL", cls.model),
			provider=os.getenv("EMBEDDING_PROVIDER", cls.provider),
			base_url=os.getenv("EMBEDDING_BASE_URL", cls.base_url),
			api_key=os.getenv("EMBEDDING_API_KEY", cls.api_key),
			device=os.getenv("EMBEDDING_DEVICE", cls.device),
			dimensions=int(dim) if (dim:=os.getenv("EMBEDDING_DIMENSIONS")) is not None else cls.dimensions,
			hf_home=Path(hf_path) if (hf_path:=os.getenv("HF_HOME")) is not None else cls.hf_home
		)

@dataclass(frozen=True)
class PersistenceConfig:
	url: str = "neo4j://127.0.0.1:7687"
	user: str = "neo4j"
	password: str = "neo4j"
	database: str = 'neo4j'
	chunk_size: int = 5000
	concurrency: int = 4

	@classmethod
	def from_env(cls) -> "PersistenceConfig":
		return cls(
			url=os.getenv("NEO4J_URI", cls.url),
			user=os.getenv("NEO4J_USER", cls.user),
			password=os.getenv("NEO4J_PASSWORD", cls.password),
			database=os.getenv("NEO4J_DATABASE", cls.database),
			chunk_size=int(os.getenv("CHUNK_SIZE", cls.chunk_size)),
			concurrency=int(os.getenv("PERSIST_CONCURRENCY", cls.concurrency)),
		)

@dataclass(frozen=True)
class AgentConfig:
	model: str | None = None
	effort: str | None = None

	@classmethod
	def from_env(cls) -> "AgentConfig":
		return cls(
			model=os.getenv("AGENT_MODEL", cls.model),
			effort=os.getenv("AGENT_EFFORT", cls.effort)
		)

@dataclass(frozen=True)
class Config:

	# Embedder
	embedder_config: EmbedderConfig

	# Neo4j
	neo4j_config: PersistenceConfig

	# Model
	agent_config: AgentConfig

	# Application
	app_name: str = "VulnSwarm"
	work_dir: Path = Path(".vulnswarm")

	# Joern
	joern_binary: str = "joern-parse.bat"


	@classmethod
	def from_env(cls) -> "Config":
		return cls(
			joern_binary=os.getenv("JOERN_BINARY", cls.joern_binary),
			work_dir=Path(os.getenv("WORK_DIR", cls.work_dir)),
			neo4j_config=PersistenceConfig.from_env(),
			embedder_config=EmbedderConfig.from_env(),
			agent_config=AgentConfig.from_env()
		)

	def ensure_directories(self) -> None:
		self.work_dir.mkdir(parents=True, exist_ok=True)