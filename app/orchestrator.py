from app.config import Config
from pathlib import Path

class OrchestratorError(Exception):
	pass

class Orchestrator:
	def __init__(
			self,
			repo: Path,
			config: Config,
			watch: bool = False
	) -> None:
		self.repo = repo
		self.config = config
		self.watch = watch

	def run(self) -> int:
		self.config.ensure_directories()

		self._build_graph()
		# self._discover()
		# self._verify()
		# self._report()

		return 0

	def _build_graph(self) -> None:
		from app.graph.build import GraphBuilder, _scan_id_for
		from app.embedder import Embedder
		from app.graph_wrapper import GraphDB

		builder = GraphBuilder(repo=self.repo, config=self.config)
		embedder = Embedder(repo=self.repo, config=self.config)
		graph = GraphDB(config=self.config)

		try:
			scan_id = _scan_id_for(self.repo)
			builder.build(scan_id)
			embedder.index(scan_id)
			if not embedder.ensure_exploit_index():
				raise OrchestratorError('Unable to index exploit corpus')

			
		finally:
			builder.close()
			embedder.close()
			graph.close()

	def _discover(self) -> None:
		print('Discovery in progress')

	def _verify(self) -> None:
		print('Verification in progress')

	def _report(self) -> None:
		print('Report')