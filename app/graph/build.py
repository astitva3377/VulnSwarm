import hashlib
from pathlib import Path
from app.config import Config
from app.graph.joern import JoernAdapter
from app.graph.persist import Persister
from app.graph.profile import GENERIC
from app.graph.deps import parse_dependencies
from app.graph.analysis import reachability, centrality, pathfind
from app.graph.joern_util import normalize, read_graphson

def _scan_id_for(repo: Path) -> str:
	return hashlib.sha1(f'{repo.resolve()}'.encode('utf-8')).hexdigest()

class GraphBuilder:
	def __init__(
			self,
			repo: Path,
			config: Config
	) -> None:
		self.repo = repo
		self.config = config

		self.joern = JoernAdapter()

		self.neo4j = Persister(config=config.neo4j_config)

	def build(self, scan_id: str) -> str:
		cpg_dir = (
			self.config.work_dir
			/ self.repo.name
		)
		graph_dir = (
			self.config.work_dir
			/ self.repo.name
			/ "graph"
		)

		cpg_dir.mkdir(parents=True, exist_ok=True)

		print('Running Joern')
		parse_result = self.joern.parse(repo=self.repo, output_dir=cpg_dir)
		print(f'Created CPG @ {parse_result.cpg_path}')
		print()

		print('Exporting CPG as Neo4j CSV')
		export_result = self.joern.export_graph(cpg_path=parse_result.cpg_path, output_dir=graph_dir)
		print(f'Neo4j GraphSON @ {export_result.output_dir}')
		print()

		print('Reading Graph Objects')
		graph = read_graphson(export_result.output_dir / "export.json", GENERIC)
		print('Graph Read')
		print('  - Nodes: ', len(graph.nodes))
		print('  - Edges: ', len(graph.edges))
		print('  - EntryMethods: ', len(graph.entry_methods))

		deps = parse_dependencies(repo=self.repo)
		print('  - Dependencies: ', len(deps))
		print()

		scan_id = _scan_id_for(self.repo)
		print()
		print('Scan ID', scan_id)
		print()

		batch = normalize(nodes=graph.nodes, edges=graph.edges, entry_methods=graph.entry_methods, scan_id=scan_id, dependencies=deps)
		print('Normalized Batch')
		print('  - Nodes: ', len(batch.nodes))
		print('  - Edges: ', len(batch.edges))
		print()

		reach = reachability(batch)
		print('Reachability Analysis')
		print('  - Reachable Methods: ', f'{reach.reachable_methods}/{reach.total_methods}')
		print('  - Reachable Calls: ', f'{reach.reachable_calls}/{reach.total_calls}')
		print()

		centra = centrality(batch)
		print('Reachability Analysis')
		print('  - Nodes: ', centra.nodes)
		print('  - Edges: ', centra.edges)
		print('  - Max Centrality: ', centra.max_centrality)
		print()

		pathfinding = pathfind(batch, GENERIC)
		print('Pathfinding Analysis')
		print('  - Sources: ', pathfinding.sources)
		print('  - Sinks: ', pathfinding.sinks)
		print('  - Flows: ', pathfinding.flows)
		print()

		print('Building Graph in DB')
		self.neo4j.verify_connection()
		self.neo4j.persist(batch=batch)
		print()

		return scan_id

	def close(self) -> None:
		self.neo4j.close()