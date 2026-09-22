from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import cast
from neo4j import GraphDatabase, Query, Session
from neo4j.exceptions import Neo4jError, DriverError
from tqdm import tqdm
from app.graph.schema import NODE_KEY, Batch


class GraphPersistenceError(RuntimeError):
	pass

@dataclass
class PersistenceLog:
	scan_id: str
	nodes: int
	edges: int

def _index_name(label: str) -> str:
	return f'vulnswarm_nodekey_{label}'

def _node_create_query(label: str) -> str:
	return f'UNWIND $rows AS row CREATE (n:`{label}`) SET n += row.props'

def _edge_create_query(
	rtype: str, from_label: str, to_label: str,
	from_keys: tuple[str, ...], to_keys: tuple[str, ...]
) -> str:
	fpat = ', '.join(f'`{k}`: row.fk.`{k}`' for k in from_keys)
	tpat = ', '.join(f'`{k}`: row.tk.`{k}`' for k in to_keys)

	return (
		f'UNWIND $rows as row '
		f'MATCH (a:`{from_label}` {{{fpat}}}) '
		f'MATCH (b:`{to_label}` {{{tpat}}})'
		f'CREATE (a)-[r:`{rtype}`]->(b) SET r += row.props'
	)

def _chunk(rows: list, size: int):
	step = max(1, size)
	for i in range(0, len(rows), step):
		yield rows[i : i+step]

def _node_rows(nodes) -> dict[str, list[dict]]:
	by_label: dict[str, dict[tuple, dict]] = defaultdict(dict)
	for label, props in nodes:
		key = tuple(props[k] for k in NODE_KEY[label])
		by_label[label][key] = {**by_label[label].get(key, {}), **props}
	return {label: [{'props': p} for p in keyed.values()] for label, keyed in by_label.items()}

def _edges_rows(edges) -> dict[tuple, list[dict]]:
	flows: dict[tuple, list[dict]] = defaultdict(list)
	struct: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
	order: list[tuple] = []

	for rtype, fl, fk, tl, tk, props in edges:
		sig = (rtype, fl, tl, tuple(fk.keys()), tuple(tk.keys()))
		if rtype == 'FLOWS_TO':
			if sig not in flows:
				order.append(sig)
			flows[sig].append({'fk': fk, 'tk': tk, 'props': props})
		else:
			if sig not in struct:
				order.append(sig)
			endpoint = (tuple(fk.values()), tuple(tk.values()))
			prev = struct[sig].get(endpoint)
			merged = {**(prev['props'] if prev else {}), **props}
			struct[sig][endpoint] = {'fk': fk, 'tk': tk, 'props': merged}
	out: dict[tuple, list[dict]] = {}
	for sig in order:
		out[sig] = flows[sig] if sig[0] == 'FLOWS_TO' else list(struct[sig].values())
	return out

def _run_write(tx, cypher: str, rows: list) -> None:
	tx.run(cypher, rows=rows)

def _edge_jobs(edges, size) -> list[tuple[str, list]]:
	return [
		(_edge_create_query(*sig), chunk)
		for sig, rows in _edges_rows(edges).items()
		for chunk in _chunk(rows, size)
	]

def _node_jobs(nodes, size) -> list[tuple[str, list]]:
	return [
		(_node_create_query(label), chunk)
		for label, rows in _node_rows(nodes).items()
		for chunk in _chunk(rows, size)
	]



class Persister:
	def __init__(
		self,
		url: str,
		user: str,
		pwd: str,
		db: str = "VulnSwarm",
		chunk_size: int = 1,
		concurrency: int = 1
	) -> None:
		self.db = db
		self.driver = GraphDatabase.driver(
			url,
			auth=(user, pwd)
		)
		self.chunk_size = chunk_size
		self.concurrency = concurrency


	def verify_connection(self) -> None:
		try:
			self.driver.verify_connectivity()
			print('Connected to Neo4j instance')
		except Neo4jError as e:
			raise GraphPersistenceError(f'Connection to Neo4j Failed with error: {e}') from e
		except DriverError as e:
			raise GraphPersistenceError(f'Could not connect to server: {e}') from e

	def close(self) -> None:
		self.driver.close()

	def clear(self, scan_id: str):
		labels = list(NODE_KEY.keys())
		with self.driver.session(database=self.db) as s:
			s.execute_write(lambda tx: tx.run(
				'MATCH (n {scan_id:$sid}) WHERE any(l IN labels(n) WHERE l IN $labels) DETACH DELETE n',
				sid=scan_id, labels=labels
			))
	
	def _ensure_indexes(self) -> None:
		with self.driver.session(database=self.db) as session:
			for label, keys in NODE_KEY.items():
				props = ', '.join(f'n.`{k}`' for k in keys)
				session.run(cast(
					Query,
					f'CREATE RANGE INDEX `{_index_name(label)}` IF NOT EXISTS FOR (n: `{label}`) ON ({props})'
				))

			for label in NODE_KEY:
				session.run('CALL db.awaitIndex($name, 300)', name=_index_name(label))

	def _run_jobs(self, jobs: list[tuple[str, list]], desc) -> None:
		if not jobs:
			return

		if self.concurrency <= 1:
			with self.driver.session(database=self.db) as s:
				for cypher, rows in tqdm(jobs, total=len(jobs), desc=desc):
					s.execute_write(_run_write, cypher, rows)
			return

		def _one(job: tuple[str, list]) -> None:
			cypher, rows = job
			with self.driver.session(database=self.db) as s:
				s.execute_write(_run_write, cypher, rows)

		with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
			futures = [ex.submit(_one, job) for job in jobs]

			for future in tqdm(
				as_completed(futures),
				total=len(futures),
				desc=desc
			):
				future.result()

	def persist(self, batch: Batch) -> None:
		try:
			self._ensure_indexes()

			self.clear(scan_id=batch.scan_id)

			self._run_jobs(_node_jobs(batch.nodes, self.chunk_size), 'Nodes')
			self._run_jobs(_edge_jobs(batch.edges, self.chunk_size), 'Edges')

		except Exception as e:
			raise GraphPersistenceError(f'Encountered error: {e}') from e