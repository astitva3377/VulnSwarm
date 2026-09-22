from collections import deque
from dataclasses import dataclass
import hashlib
import json
from app.graph.profile import Profile
from app.graph.schema import Batch
import networkx as nx

_METHOD = "M"
_CALL = "C"

_TRAVERAL = {
	"CONTAINS_CALL": ((_METHOD, "full_name"), (_CALL, "uid")),
	"RESOLVES_TO": ((_CALL, "uid"), (_METHOD, "full_name")),
	"FLOWS_TO": ((_CALL, "uid"), (_CALL, "uid"))
}

_CENTRALITY_EXACT_MAX = 2000
_CENTRALITY_SAMPLE_K = 500
_CENTRALITY_SEED = 1

_SINK_SEVERITY = {
	"code_exec": 5, "deserialize": 5,
	"sql": 4, "nosql": 4, "ssrf": 4, "template": 4,
	"path": 3,
	"redirect": 2, "render": 2,
	"log": 1
}
_DEFAULT_SEVERITY = 3
_MAX_DEPTH = 12
_MAX_FLOWS = 300


@dataclass
class Reachability:
	total_methods: int
	total_calls: int
	reachable_methods: int
	reachable_calls: int

@dataclass
class Centrality:
	nodes: int
	edges: int
	max_centrality: float

@dataclass
class PathFind:
	sources: int
	sinks: int
	flows: int

def _node_props_index(batch: Batch) -> dict[tuple[str, str], list[dict]]:
	index: dict[tuple[str, str], list[dict]] = {}

	for label, props in batch.nodes:
		if label == 'CpgMethod':
			key = (_METHOD, str(props.get("full_name")))
		elif label == 'CpgCall':
			key = (_CALL, str(props.get('uid')))
		else:
			continue
		if key[1] is None:
			continue
		props['reachable_from_entry'] = False
		props['hop_distance'] = -1
		index.setdefault(key, []).append(props)
	return index

def _endpoint(kind_key: tuple[str, str], edge_key: dict):
	kind, prop = kind_key
	val = edge_key.get(prop)
	return (kind, val) if val is not None else None

def _adjacency_sources(batch: Batch):
	adj: dict[tuple[str, str], list[tuple[str, str]]] = {}
	sources: set[tuple[str, str]] = set()

	for rtype, _, from_key, _, to_key, _ in batch.edges:
		spec = _TRAVERAL.get(rtype)
		if spec is not None:
			src = _endpoint(spec[0], from_key)
			dst = _endpoint(spec[1], to_key)
			if src is not None and dst is not None:
				adj.setdefault(src, []).append(dst)
		elif rtype == 'ENTERS_AT':
			entry_method = _endpoint((_METHOD, 'full_name'), to_key)
			if entry_method is not None:
				sources.add(entry_method)
	return adj, sources

def reachability(batch: Batch) -> Reachability:
	index = _node_props_index(batch)
	adj, sources = _adjacency_sources(batch)

	dist: dict[tuple[str, str], int] = {}
	queue: deque[tuple[str, str]] = deque()

	for src in sources:
		if src not in dist:
			dist[src] = 0
			queue.append(src)
	while queue:
		node = queue.popleft()
		d = dist[node]
		for nbr in adj.get(node, {}):
			if nbr not in dist:
				dist[nbr] = d+1
				queue.append(nbr)

	for identity, d in dist.items():
		for props in index.get(identity, ()):
			props['reachable_from_entry'] = True
			props['hop_distance'] = d

	return Reachability(
		total_methods=sum(1 for k in index if k[0] == _METHOD),
		total_calls=sum(1 for k in index if k[0] == _CALL),
		reachable_methods=sum(1 for k in dist if k[0] == _METHOD and k in index),
		reachable_calls=sum(1 for k in dist if k[0] == _CALL and k in index)
	)


def _kind_index(batch: Batch) -> dict[tuple[str, str], list[dict]]:
	index: dict[tuple[str, str], list[dict]] = {}

	for label, props in batch.nodes:
		if label == 'CpgMethod':
			key = (_METHOD, str(props.get('full_name')))
		elif label == 'CpgCall':
			key = (_CALL, str(props.get('uid')))
		else:
			continue
		if key[1] is None:
			continue
		index.setdefault(key, []).append(props)
	return index

def centrality(batch: Batch) -> Centrality:
	index = _kind_index(batch)
	for plist in index.values():
		for props in plist:
			props['centrality'] = 0.0

	reachable = {
		ident for ident, plist in index.items()
		if any(p.get('reachable_from_entry') for p in plist)
	}
	adj, _ = _adjacency_sources(batch)

	graph = nx.DiGraph()
	graph.add_nodes_from(reachable)
	for src, nbrs in adj.items():
		if src in reachable:
			for dst in nbrs:
				if dst in reachable:
					graph.add_edge(src, dst)

	num_nodes = graph.number_of_nodes()
	if num_nodes == 0:
		return Centrality(nodes=0, edges=0, max_centrality=0.0)

	if num_nodes > _CENTRALITY_EXACT_MAX:
		centrality_value = nx.betweenness_centrality(
			graph, k=min(_CENTRALITY_SAMPLE_K, num_nodes),
			normalized=True, seed=_CENTRALITY_SEED
		)
	else:
		centrality_value = nx.betweenness_centrality(graph, normalized=True)

	for ident, c in centrality_value.items():
		for props in index.get(ident, ()):
			props['centrality'] = float(c)

	return Centrality(
		nodes=num_nodes,
		edges=graph.number_of_edges(),
		max_centrality=max(centrality_value.values(), default=0.0)
	)


def _severity(category: str) -> int:
	return _SINK_SEVERITY.get(category, _DEFAULT_SEVERITY)

def _classify_sink(props: dict, profile: Profile) -> str | None:
	if profile is None:
		return None

	name = str(props.get('name') or '').lower()
	code = str(props.get('code') or '').lower()
	best: str | None = None
	best_sev = -1

	for category, hints in profile.sink_hints.items():
		for hint in hints:
			hint = hint.lower()
			if hint and (hint in name or hint in code):
				sev = _severity(category)
				if sev > best_sev:
					best, best_sev = category, sev
				break
	return best

def _index_edges(batch: Batch):
	call_props: dict[str, dict] = {}
	for label, props in batch.nodes:
		if label == 'CpgCall':
			uid = props.get('uid')
			if uid is not None:
				call_props[uid] = {**call_props.get(uid, {}), **props}

	flows: dict[str, list[str]] = {}
	self_loops: set[str] = set()
	entry_methods: set[str] = set()
	contains: dict[str, list[str]] = {}

	for rtype, _, from_key, _, to_key, _ in batch.edges:
		if rtype == 'FLOWS_TO':
			src, dst = from_key.get('uid'), to_key.get('uid')
			if src is None or dst is None:
				continue
			if src == dst:
				self_loops.add(src)
			else:
				flows.setdefault(src, []).append(dst)
		elif rtype == 'ENTERS_AT':
			m = to_key.get('full_name')
			if m is not None:
				entry_methods.add(m)
		elif rtype == 'CONTAINS_CALL':
			m, c = from_key.get('full_name'), to_key.get('uid')
			if m is not None and c is not None:
				contains.setdefault(m, []).append(c)
	return call_props, flows, self_loops, entry_methods, contains

def _sources(self_loops: set[str], entry_methods: set[str], contains: dict[str, list[str]]) -> set[str]:
	srcs = set(self_loops)
	for m in entry_methods:
		srcs.update(contains.get(m, ()))
	return srcs

def _candidate_uid(scan_id: str, source_uid: str, sink_uid: str) -> str:
	return hashlib.sha1(f'{scan_id}|CandidateFlow|{source_uid}|{sink_uid}'.encode('utf-8')).hexdigest()

def pathfind(batch: Batch, profile: Profile) -> PathFind:
	call_props, flows, self_loops, entry_methods, contains = _index_edges(batch)
	sources = _sources(self_loops, entry_methods, contains)

	parent: dict[str, str | None] = {}
	origin: dict[str, str] = {}
	dist: dict[str, int] = {}
	queue: deque[str] = deque()

	for s in sources:
		if s not in dist:
			dist[s], parent[s], origin[s] = 0, None, s
			queue.append(s)

	while queue:
		u = queue.popleft()
		if dist[u] >= _MAX_DEPTH:
			continue
		for v in flows.get(u, ()):
			if v not in dist:
				dist[v], parent[v], origin[v] = dist[u] + 1, u, origin[u]
				queue.append(v)


	def _path(uid: str) -> list[str]:
		out = []
		current: str | None = uid
		while current is not None:
			out.append(current)
			current = parent.get(current)
		out.reverse()
		return out


	raw: list[tuple[int, float, int, str, str, str, list[str]]] = []
	for uid in dist:
		category = _classify_sink(call_props.get(uid, {}), profile)
		if category is None:
			continue
		centra = float(call_props.get(uid, {}).get('centrality') or 0.0)
		path = _path(uid)
		raw.append((_severity(category), centra, len(path), category, origin[uid], uid, path))

	raw.sort(key=lambda r: (-r[0], -r[1], r[2], r[5]))

	n_sinks = len(raw)

	for rank, (_, _, _, category, source_uid, sink_uid, path) in enumerate(raw[:_MAX_FLOWS]):
		batch.emit_node("CandidateFlow", {
			'uid': _candidate_uid(batch.scan_id, source_uid, sink_uid),
			'source_uid': source_uid,
			'sink_uid': sink_uid,
			'sink_category': category,
			'path_uids': json.dumps(path),
			'rank': rank
		})

	return PathFind(
		sources=len(sources),
		sinks=n_sinks,
		flows=min(n_sinks, _MAX_FLOWS)
	)