import hashlib


NODE_KEY: dict[str, tuple[str, ...]] = {
	"CpgFile": ("scan_id", "uid"),
	"CpgMethod": ("scan_id", "full_name"),
	"CpgCall": ("scan_id", "uid"),
	"CpgModule": ("scan_id", "import_name"),
	"CpgParameter": ("scan_id", "uid"),
	"CpgReturn": ("scan_id", "uid"),
	"EntryPoint": ("scan_id", "uid"),
	"Dependency": ("scan_id", "name"),
	"CandidateFlow": ("scan_id", "uid")
}

def create_uid(scan_id: str, cpg_type: str, file_path, line, column, code) -> str:
	parts = [scan_id, cpg_type, file_path or "", str(line), str(column), code or ""]
	return hashlib.sha1("|".join(parts).encode('utf-8')).hexdigest()

class Batch:
	def __init__(self, scan_id: str) -> None:
		self.scan_id = scan_id
		self.nodes: list[tuple[str, dict]] = []
		self.edges: list[tuple[str, str, dict, str, dict, dict]] = []

	def emit_node(self, label: str, props: dict) -> None:
		props.setdefault("scan_id", self.scan_id)
		self.nodes.append((label, props))

	def emit_edge(self, rtype: str, from_label: str, from_key: dict, to_label: str, to_key: dict, props: dict | None = None) -> None:
		p = dict(props or {})
		p.setdefault("scan_id", self.scan_id)
		from_key = {**from_key, "scan_id": self.scan_id}
		to_key = {**to_key, "scan_id": self.scan_id}
		self.edges.append((rtype, from_label, from_key, to_label, to_key, p))