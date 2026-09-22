from app.config import Config
from pathlib import Path

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
		self._discover()
		self._verify()
		self._report()

		return 0

	def _build_graph(self) -> None:
		from app.graph.build import GraphBuilder

		builder = GraphBuilder(repo=self.repo, config=self.config)

		try:
			builder.build()
		finally:
			builder.close()

	def _discover(self) -> None:
		print('Discovery in progress')

	def _verify(self) -> None:
		print('Verification in progress')

	def _report(self) -> None:
		print('Report')