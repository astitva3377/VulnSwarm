import os
from neo4j import GraphDatabase, Session
from pathlib import Path
from app import exploit
from app.config import Config
from app.exploit import METADATA_PATH
from app.graph.schema import Batch
from app.providers.embedding_provider import EmbeddingProviderFactory


VECTOR_INDEX_NAME = 'chunk_embedding_index'
EXPLOIT_VECTOR_INDEX_NAME = 'exploit_embedding_index'
EXPLOIT_LABEL = 'ExploitChunk'

METHOD_LINE_WINDOW = 40
BLOCK_LINES = 60


def _ensure_vector_index(session: Session, dimension: int) -> None:
	session.run(
		f"""
		CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS
		FOR (c:Chunk) ON (c.embedding)
		OPTIONS {{indexConfig: {{
			`vector.dimensions`: $dims,
			`vector.similarity_function`: 'cosine'
		}}}}
		""",
		dims=dimension
	)

def _ensure_exploit_vector_index(session: Session, dimension: int) -> None:
	session.run(
		f"""
		CREATE VECTOR INDEX {EXPLOIT_VECTOR_INDEX_NAME} IF NOT EXISTS
		FOR (c:{EXPLOIT_LABEL}) ON (c.embedding)
		OPTIONS {{indexConfig: {{
			`vector.dimensions`: $dims,
			`vector.similarity_function`: 'cosine'
		}}}}
		""", dims = dimension
	)

def _get_scan_from_graph(session: Session, scan_id: str) -> tuple[list[dict], list[str]]:
	methods = [
		dict(record)
		for record in session.run(
			"""
			MATCH (m:CpgMethod {scan_id: $scan_id})
			WHERE m.file_path IS NOT NULL
				AND m.line IS NOT NULL

			RETURN 
				m.full_name AS full_name,
				m.file_path AS file_path,
				m.line AS line
			
			ORDER BY m.file_path, m.line
			""",
			scan_id=scan_id
		)
	]

	files = [
		record['file_path']
		for record in session.run(
			"""
			MATCH (m:CpgFile {scan_id: $scan_id})
			RETURN m.file_path AS file_path
			ORDER BY m.file_path
			""",
			scan_id=scan_id
		)
	]

	return methods, files

def _read_window(repo: Path, file_path: str, start_line: int, num_lines: int):
	full = os.path.join(repo.resolve(), file_path)
	try:
		with open(full, 'r', encoding='utf-8', errors='replace') as f:
			lines = f.readlines()
	except OSError:
		return None

	start_idx = max(start_line-1, 0)
	if not lines or start_idx >= len(lines):
		return None

	end_idx = min(start_idx + num_lines, len(lines))
	text = "".join(lines[start_idx:end_idx])
	if not text.strip():
		return None
	return text, start_idx + (end_idx - start_idx)

def _build_chunks(repo: Path, methods: list[dict], files: list[str]) -> list[dict]:
	chunks: list[dict] = []
	files_with_methods: set[str] = set()

	for m in methods:
		file_path, line = m['file_path'], m['line']
		if file_path is None or line is None:
			continue

		window = _read_window(repo, file_path, line, METHOD_LINE_WINDOW)
		if window is None:
			continue

		text, end_line = window
		files_with_methods.add(file_path)
		chunks.append({
			'file': file_path,
			'span': f'{file_path}:{line}-{end_line}',
			'text': text
		})

	for file_path in files:
		if file_path in files_with_methods:
			continue
		full = os.path.join(repo.resolve(), file_path)

		try:
			with open(full, 'r', encoding='utf-8', errors='replace') as f:
				lines = f.readlines()
		except OSError:
			continue

		for start in range(0, len(lines), BLOCK_LINES):
			block = lines[start: start + BLOCK_LINES]
			if not any(line.strip() for line in block):
				continue
			chunks.append({
				'file': file_path,
				'span': f"{file_path}:{start+1}-{start + len(block)}",
				'text': "".join(block)
			})
	return chunks

# scan_id = '45591caa1bcd80bd28388b2b93b32404588a9833'
# driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4jneo4j"))
# methods, files = _get_scan_from_graph(driver, scan_id)

# print('Methods:')
# for method in methods:
# 	print(f"  {method['full_name']} ({method['file_path']}:{method['line']})")

# print('Files:')
# for file in files:
# 	print(f"  {file}")


class Embedder:
	def __init__(
		self,
		repo: Path,
		config: Config,
		db: str = 'VulnSwarm',
	) -> None:
		self.repo = repo
		self.driver = GraphDatabase.driver(
			uri=config.neo4j_config.url,
			auth=(config.neo4j_config.user, config.neo4j_config.password)
		)
		self.db = db
		self.embedder = EmbeddingProviderFactory.get_provider(config=config.embedder_config, batch_size=16, show_progress=True)

	def close(self):
		self.driver.close()

	def index(self, scan_id: str) -> None:
		with self.driver.session(database=self.db) as session:
			_ensure_vector_index(session=session, dimension=self.embedder.get_dimension)
			session.run('MATCH (c:Chunk {scan_id: $scan_id}) DETACH DELETE c', scan_id=scan_id)
			methods, files = _get_scan_from_graph(session, scan_id)

		chunks = _build_chunks(self.repo, methods, files)
		if not chunks:
			return

		texts = [c['text'] for c in chunks]
		vectors = self.embedder.embed(texts)
		rows = [
			{
				'file': c['file'],
				'span': c['span'],
				'text': c['text'],
				'embedding': vec
			} for c, vec in zip(chunks, vectors)
		]

		with self.driver.session(database=self.db) as session:
			session.run(
				"UNWIND $rows as row "
				"CREATE (c:Chunk {scan_id: $scan_id, file: row.file, span: row.span, "
				"text: row.text, embedding: row.embedding})",
				scan_id=scan_id, rows=rows
			)


	def exploit_index_ready(self) -> bool:
		with self.driver.session(database=self.db) as session:
			has_index = session.run(
				"SHOW INDEXES YIELD name WHERE = $name RETURN count(*) AS c",
				name=EXPLOIT_VECTOR_INDEX_NAME
			).single()
			if not has_index or not has_index['c']:
				return False
			n = session.run(f"MATCH (c:{EXPLOIT_LABEL}) RETURN count(c) AS c").single()
			if not n or not n['c']:
				return False
			return n['c'] > 0

	def index_exploits(self) -> int:
		metadata = exploit.load()
		docs = exploit.to_documents(metadata)

		with self.driver.session(database=self.db) as session:
			_ensure_exploit_vector_index(session, self.embedder.get_dimension)
			session.run(f"MATCH (c:{EXPLOIT_LABEL}) DETACH DELETE c")
		if not docs:
			return 0

		vectors = self.embedder.embed([d.text for d in docs])
		rows = [{
			'module': d.module, 'name': d.name, 'cves': list(d.cves), 'rank': d.rank,
			'mtype': d.mtype, 'disclosure_date': d.disclosure_date, 'path': d.path,
			'text': d.text, 'embedding': vec
		} for d, vec in zip(docs, vectors)]

		with self.driver.session(database=self.db) as session:
			session.run(
				f"UNWIND $rows AS row CREATE (c:{EXPLOIT_LABEL} {{"
				"module: row.module, name: row.name, cves: row.cves, rank: row.rank, "
				"mtype: row.mtype, disclosure_date: row.disclosure_date, path: row.path, "
				"text: row.text, embedding: row.embedding})",
				rows=rows
			)
			session.run("CALL db.awaitIndexes(60)")
		return len(rows)

	def ensure_exploit_index(self) -> bool:
		if self.exploit_index_ready():
			return True
		if not os.path.exists(METADATA_PATH):
			exploit.fetch_metadata()
		self.index_exploits()
		return True