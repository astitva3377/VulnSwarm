from dataclasses import dataclass
from pathlib import Path
import json
from app.graph.profile import Profile
from app.graph.schema import Batch, create_uid

MAPPED_LABELS = {
	"FILE",
	"METHOD",
	"CALL",
	"IMPORT",
	"METHOD_PARAMETER_IN",
	"METHOD_RETURN"
}

MAPPED_EDGES = {
	"CONTAINS": ("METHOD", "CALL"),
	"CALL": ("CALL", "METHOD"),
	"SOURCE_FILE": ("METHOD", "FILE")
}

NODE_PROPS = {
	"FILE": ["NAME"],

	"METHOD": [
		"FULL_NAME",
		"NAME",
		"IS_EXTERNAL",
		"FILENAME",
		"LINE_NUMBER"
	],

	"CALL": [
		"METHOD_FULL_NAME",
		"NAME",
		"CODE",
		"LINE_NUMBER",
		"COLUMN_NUMBER"
	],

	"IMPORT": [
		"IMPORTED_AS",
		"IMPORTED_ENTITY",
		"CODE",
		"LINE_NUMBER"
	],

	"METHOD_PARAMETER_IN": [
		"NAME",
		"INDEX",
		"LINE_NUMBER",
		"CODE"
	],

	"METHOD_RETURN": [
		"LINE_NUMBER",
		"CODE"
	]
}

_SOURCE_ANNOTATIONS: frozenset[str] = frozenset()
_EMPTY_PATHS = frozenset({"", "<empty>", "N/A", "<unknown>"})

def _unwrap(x):
	if isinstance(x, dict) and "@value" in x:
		return _unwrap(x["@value"])
	if isinstance(x, list):
		return [_unwrap(i) for i in x]
	return x

def _prop(vertex, key, default=None):
	entry = vertex.get("properties", {}).get(key)
	if entry is None:
		return None
	
	entries = entry if isinstance(entry, list) else [entry]

	vals = []
	for e in entries:
		v = _unwrap(e)
		vals.extend(v) if isinstance(v, list) else vals.append(v)
	if not vals:
		return default
	return vals[0] if len(vals) == 1 else vals
	

def _deepint(x):
	while isinstance(x, dict) and "@value" in x:
		x = x["@value"]
	return x if isinstance(x, int) else None

def _is_real_call(label, method_full_name):
	return label == 'CALL' and not str(method_full_name or "").startswith("<operator>")

def _clean(v):
	if v is None or not isinstance(v, str):
		return None
	return None if v in _EMPTY_PATHS else v

def _call_files_map(graph: dict) -> dict:
	vertices = {_unwrap(v['id']): v for v in graph.get("vertices", [])}
	ast_parent: dict = {}

	for e in graph.get("edges", []):
		if e['label'] == 'AST':
			ast_parent[_unwrap(e['inV'])] = _unwrap(e['outV'])

	method_file = {
		vid: _clean(_prop(v, "FILENAME"))
		for vid, v in vertices.items() if v['label'] == 'METHOD'
	}

	file_map: dict = {}
	for vid, v in vertices.items():
		if v['label'] != 'CALL':
			continue

		current, guard = vid, 0
		while current is not None and guard < 256:
			guard += 1
			node = vertices.get(current)
			if node is None:
				break
			if node['label'] == 'METHOD':
				file_map[vid] = method_file.get(current)
				break
			current = ast_parent.get(current)
	return file_map

def _entry_method_ids_from(method_vertices: dict, called: set, has_param: set, callbacks_full: set) -> set:
	entries: set = set()

	for vid, v in method_vertices.items():
		if bool(_prop(v, "IS_EXTERNAL")):
			continue
		if _clean(_prop(v, 'FILENAME')) is None or vid not in has_param:
			continue
		name = _prop(v, "NAME") or ""
		if str(name).startswith('<') or name == ':program':
			continue
		is_callback = _prop(v, 'FULL_NAME') in callbacks_full
		if vid in called and not is_callback:
			continue
		entries.add(vid)

	return entries

def _entry_method_ids(graph: dict) -> set:
	vertices = {_unwrap(v['id']): v for v in graph.get('vertices', [])}
	method_vertices = {vid: v for vid, v in vertices.items() if v['label'] == 'METHOD'}

	callbacks_full: set = {mfn for v in vertices.values() if v['label'] == 'METHOD_REF' and isinstance((mfn := _prop(v, "METHOD_FULL_NAME")), str) and mfn}
	called: set = set()
	has_param: set = set()

	for e in graph.get('edges', []):
		o, i = _unwrap(e['outV']), _unwrap(e['inV'])
		lbl = e['label']
		if lbl == 'CALL' and vertices.get(i, {}).get('label') == 'METHOD':
			called.add(i)
		elif (lbl == 'AST' and vertices.get(o, {}).get('label') == 'METHOD' and vertices.get(i, {}).get('label') == 'METHOD_PARAMETER_IN'):
			has_param.add(o)
	return _entry_method_ids_from(method_vertices, called, has_param, callbacks_full)


@dataclass
class GraphSONData:
	nodes: list[dict]
	edges: list[dict]
	entry_methods: list

def collapse_flows(
	inner_graph: dict,
	*,
	request_source_names: frozenset[str] = frozenset({"req", "request"}),
	entrypoint_method_ids: frozenset | None = None
) -> list:
	vertices = {
		_unwrap(v['id']): v
		for v in inner_graph.get("vertices", [])
	}

	rd: dict = {} # REACHING_DEF outV->inV
	arg_parent: dict = {} # child_id->parent_call_id
	arg_index: dict = {} # child_id->ARGUMENT_INDEX
	arg_children: dict = {} # parent_call_id->{index:child_id}
	callee: dict = {} # call_site_id->METHOD_id resolved
	mparams: dict = {} # method_id->{param_index:param_id}
	param_annotations: dict = {} # param_id->annotation name

	for e in inner_graph.get('edges', []):
		lbl = e['label']

		if lbl == 'REACHING_DEF':
			rd.setdefault(_unwrap(e['outV']), []).append(_unwrap(e['inV']))


		elif lbl == 'ARGUMENT':
			ch = _unwrap(e['inV'])
			parent = _unwrap(e['outV'])
			arg_parent[ch] = parent
			if ch in vertices:
				idx = _deepint(_prop(vertices[ch], "ARGUMENT_INDEX"))
				arg_index[ch] = idx
				arg_children.setdefault(parent, {})[idx] = ch


		elif lbl == 'CALL':
			o, i = _unwrap(e['outV']), _unwrap(e['inV'])
			if vertices.get(o, {}).get('label') == 'CALL' and vertices.get(i, {}).get('label') == 'METHOD':
				callee[o] = i


		elif lbl == 'AST':
			o, i = _unwrap(e['outV']), _unwrap(e['inV'])
			olbl = vertices.get(o, {}).get('label')
			ilbl = vertices.get(i, {}).get('label')
			if olbl == 'METHOD' and ilbl == 'METHOD_PARAMETER_IN':
				mparams.setdefault(o, {})[_deepint(_prop(vertices[i], 'INDEX'))] = i
			elif olbl == 'METHOD_PARAMETER_IN' and ilbl == 'ANNOTATION':
				names = param_annotations.setdefault(o, set())
				for key in (_prop(vertices[i], "FULL_NAME"), _prop(vertices[i], "NAME")):
					if isinstance(key, str) and key:
						names.add(key)


	def enclosing_real_arg(n):
		current = n
		while current in arg_parent:
			pa = arg_parent[current]
			pv = vertices.get(pa)
			if pv is not None and _is_real_call(pv['label'], _prop(pv, "METHOD_FULL_NAME")):
				return pa, arg_index.get(current)
			current = pa
		return None, None

	def stitch_target(call_node, idx):
		m = callee.get(call_node)
		return mparams.get(m, {}).get(idx) if m is not None else None


	real_calls = [
		vid for vid, v in vertices.items()
		if _is_real_call(v['label'], _prop(v, 'METHOD_FULL_NAME'))
	]
	best: dict = {}

	for call in real_calls:
		seen = {(call, False)}
		stack = [(m, False) for m in rd.get(call, [])]

		while stack:
			n, crossed = stack.pop()
			if (n, crossed) in seen:
				continue
			seen.add((n, crossed))

			rc, idx = enclosing_real_arg(n)
			if rc is not None and rc != call:
				key = (call, rc, idx)
				best[key] = best.get(key, True) and crossed
				tgt = stitch_target(rc, idx)
				if tgt is not None:
					stack.append((tgt, True))
				continue

			for m in rd.get(n, []):
				if (m, crossed) not in seen:
					stack.append((m, crossed))


	def _base_root_name(fa):
		current, guard = fa, 0
		while guard < 32:
			guard += 1
			v = vertices.get(current)
			if v is None:
				return None
			if v['label'] == 'IDENTIFIER':
				return _prop(v, "NAME")
			if v['label'] == 'CALL' and _prop(v, 'METHOD_FULL_NAME') == '<operator>.fieldAccess':
				current = arg_children.get(current, {}).get(1)
				if current is None:
					return None
				continue
			return None
		return None


	source_params = [p for p, names in param_annotations.items() if names & _SOURCE_ANNOTATIONS]
	if entrypoint_method_ids:
		for m in entrypoint_method_ids:
			source_params.extend(mparams.get(m, {}).values())
	request_source_fas = [
		vid for vid, v in vertices.items()
		if v['label'] == 'CALL' and _prop(v, 'METHOD_FULL_NAME') == '<operator>.fieldAccess'
	]

	param_flows: set = set()
	for p in source_params + request_source_fas:
		pseen: set = set()
		stack = [(m, False) for m in rd.get(p, [])]

		while stack:
			n, crossed = stack.pop()
			if (n, crossed) in pseen:
				continue

			pseen.add((n, crossed))
			rc, idx = enclosing_real_arg(n)
			if rc is not None:
				param_flows.add((rc, idx))
				tgt = stitch_target(rc, idx)
				if tgt is not None:
					stack.append((tgt, True))
				continue

			for m in rd.get(n, []):
				if (m, crossed) not in pseen:
					stack.append((m, crossed))


	flows = [
		{'label': 'FLOWS_TO', 'out': a, 'in': b, 'arg_index': i, 'provenance': 'inferred' if crossed else 'proven'}
		for (a, b, i), crossed in best.items()
	]
	flows += [
		{'label': 'FLOWS_TO', 'out': rc, 'in': rc, 'arg_index': idx, 'provenance': 'inferred'}
		for (rc, idx) in param_flows
	]
	return flows


def normalize(nodes: list[dict], edges: list[dict], entry_methods: list, scan_id: str, dependencies: list[tuple[str, str]] | None = None, entry_funcs: list[str] | None = None) -> Batch:
	dependencies = dependencies or []
	entry_funcs = entry_funcs or []
	batch = Batch(scan_id)

	id_to_method_fullname: dict = {}
	id_to_call_uid: dict = {}
	id_to_file_uid: dict = {}
	method_by_name: dict[str, list[str]] = {}

	for n in nodes:
		if n["label"] == "FILE":

			path = _clean(n["props"].get("NAME"))
			if path is None:
				continue

			uid = create_uid(scan_id=scan_id, cpg_type="FILE", file_path=path, line=0, column=0, code=path)

			batch.emit_node("CpgFile", {
				"uid": uid,
				"file_path": path
			})
			id_to_file_uid[n['id']] = uid


		if n['label'] == "METHOD":

			full = n["props"].get("FULL_NAME")
			if full is None:

				continue

			name = n['props'].get("NAME") or full.rsplit(".", 1)[-1]
			props = {"full_name": full, "name": name, "is_external": bool(n["props"].get("IS_EXTERNAL"))}
			fp = _clean(n['props'].get("FILENAME"))
			if fp is not None:
				props['file_path'] = fp
			line = n['props'].get("LINE_NUMBER")
			if isinstance(line, int):
				props['line'] = line
			batch.emit_node("CpgMethod", props)
			id_to_method_fullname[n['id']] = full
			method_by_name.setdefault(name, []).append(full)


		if n['label'] == 'IMPORT':

			import_name = _clean(n['props'].get("IMPORTED_AS")) or _clean(n['props'].get("IMPORTED_ENTITY"))
			if import_name is None:
				continue
			batch.emit_node("CpgModule", {"import_name": import_name})


		if n['label'] == 'CALL':

			props_in = n['props']
			code = props_in.get("CODE") or props_in.get("NAME") or ""
			name = props_in.get("NAME") or ""
			line = props_in.get("LINE_NUMBER") if isinstance(props_in.get("LINE_NUMBER"), int) else 0
			col = props_in.get("COLUMN_NUMBER") if isinstance(props_in.get("COLUMN_NUMBER"), int) else 0
			fp = _clean(props_in.get("file_path")) or "<unknown>"
			uid = create_uid(scan_id=scan_id, cpg_type="CALL", file_path=fp, line=line, column=col, code=code)
			batch.emit_node("CpgCall", {
				"uid": uid, "name": name, "code": code,
				"method_full_name": props_in.get("METHOD_FULL_NAME") or "<unknownFullName>",
				"file_path": fp, "line": line, "column": col
			})
			id_to_call_uid[n['id']] = uid


		if n['label'] == "METHOD_PARAMETER_IN":
			name = n['props'].get("NAME")
			if name is None:
				continue

			line = n['props'].get("LINE_NUMBER") if isinstance(n['props'].get("LINE_NUMBER"), int) else 0
			uid = create_uid(scan_id=scan_id, cpg_type="METHOD_PARAMETER_IN", file_path="<param>", line=line, column=0, code=name)
			p = {"uid": uid, "name": name}
			idx = n["props"].get("INDEX")
			if isinstance(idx, int):
				p["index"] = idx
			batch.emit_node("CpgParameter", p)


		if n['label'] == 'METHOD_RETURN':
			line = n['props'].get('LINE_NUMBER') if isinstance(n['props'].get('LINE_NUMBER'), int) else 0
			uid = create_uid(scan_id=scan_id, cpg_type="METHOD_RETURN", file_path="<return>", line=line, column=0, code=str(n['id']))
			batch.emit_node("CpgReturn", {'uid': uid})



	for e in edges:

		if e['label'] == 'CONTAINS':
			m = id_to_method_fullname.get(e['out'])
			c = id_to_call_uid.get(e['in'])
			if m is not None and c is not None:
				batch.emit_edge("CONTAINS_CALL", "CpgMethod", {"full_name": m}, "CpgCall", {"uid": c})

		elif e['label'] == 'CALL':
			c = id_to_call_uid.get(e['out'])
			m = id_to_method_fullname.get(e['in'])
			if c is not None and m is not None:
				batch.emit_edge("RESOLVES_TO", "CpgCall", {"uid": c}, "CpgMethod", {"full_name": m})

		elif e['label'] == 'SOURCE_FILE':
			m = id_to_method_fullname.get(e['out'])
			f = id_to_file_uid.get(e['in'])
			if m is not None and f is not None:
				batch.emit_edge("DEFINED_IN", "CpgMethod", {"full_name": m}, "CpgFile", {"uid": f})

		elif e['label'] == "FLOWS_TO":
			src = id_to_call_uid.get(e['out'])
			dst = id_to_call_uid.get(e['in'])
			if src is not None and dst is not None:
				props = {}
				if isinstance(e.get("arg_index"), int):
					props['arg_index'] = e['arg_index']
				batch.emit_edge("FLOWS_TO", "CpgCall", {"uid": src}, "CpgCall", {"uid": dst}, props)


	emitted_fulls = set(id_to_method_fullname.values())
	seen_entry: set[str] = set()

	for full in entry_methods:
		if full not in emitted_fulls or full in seen_entry:
			continue
		seen_entry.add(full)
		uid = create_uid(scan_id, "ENTRYPOINT", full, 0, 0, 'structural')
		batch.emit_node('EntryPoint', {
			'uid': uid, 'kind': 'handler',
			'method_full_name': full, 'exposure': 'reachable'
		})
		batch.emit_edge('ENTERS_AT', 'EntryPoint', {'uid': uid}, 'CpgMethod', {'full_name': full})

	for ep in entry_funcs:
		candidates = method_by_name.get(ep)
		if not candidates or candidates[0] in seen_entry:
			continue
		full = candidates[0]
		seen_entry.add(full)
		uid = create_uid(scan_id, 'ENTRYPOINT', full, 0, 0, ep)
		batch.emit_node('EntryPoint', {'uid': uid, 'kind': 'http', 'method_full_name': full, 'exposure': 'exposed'})
		batch.emit_edge('ENTERS_AT', 'EntryPoint', {'uid': uid}, 'CpgMethod', {'full_name': full})

	for name, version in dependencies:
		batch.emit_node('Dependency', {'name': name, 'version': version})

	return batch

def read_graphson(path: Path, profile: Profile) -> GraphSONData:
	with open(path, encoding='utf-8') as f:
		graph = json.load(f)

	graph = graph["@value"] if "@type" in graph else graph

	call_files = _call_files_map(graph=graph)
	src_names = profile.request_source_names

	entry_ids = _entry_method_ids(graph)
	entry_taint = frozenset(entry_ids) if (profile is not None and profile.entrypoint_params_are_sources) else None

	nodes = []
	for v in graph.get("vertices", []):
		label = v['label']
		if label not in MAPPED_LABELS:
			continue

		props = {k: _prop(v, k) for k in NODE_PROPS[label]}

		if label == 'CALL':
			props['file_path'] = call_files.get(_unwrap(v['id']))

		nodes.append({
			'label': label,
			'id': _unwrap(v['id']),
			'props': props
		})

	edges = []
	for e in graph.get('edges', []):
		label = e['label']

		want = MAPPED_EDGES.get(label)
		if want is None or (e.get('outVLabel'), e.get('inVLabel')) != want:
			continue

		edges.append({
			'label': label,
			'out': _unwrap(e['outV']), 'in': _unwrap(e['inV']),
			'out_label': e.get('OutVLabel'), 'in_label': e.get('inVLabel')
		})

	edges.extend(collapse_flows(graph, request_source_names=src_names, entrypoint_method_ids=entry_taint))
	verts = {_unwrap(v['id']): v for v in graph.get('vertices', [])}
	entry_methods = sorted({
		fn for e in entry_ids
		if verts.get(e) is not None and
		(fn := _prop(verts[e], 'FULL_NAME')) is not None
		and isinstance(fn, str)
	})
	return GraphSONData(
		nodes=nodes,
		edges=edges,
		entry_methods=entry_methods
	)