import json
from pathlib import Path
import re

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*([=<>!~]=?[^#;]+)?")
_GOMOD_REQUIRE = re.compile(r"^\s*([^\s]+)\s+(v[^\s]+)")

def _from_package_json(repo: Path) -> list[tuple[str, str]]:
	pj = repo / 'package.json'
	if not pj.exists():
		return []
	try:
		data = json.loads(pj.read_text())
	except (ValueError, OSError):
		return []

	out: list[tuple[str, str]] = []
	for key in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
		deps = data.get(key)
		if isinstance(deps, dict):
			out.extend((name, str(ver)) for name, ver in deps.items() if isinstance(name, str))
	return out

def _from_requirements(repo: Path) -> list[tuple[str, str]]:
	out: list[tuple[str, str]] = []

	for req in list(repo.glob('requirements*.txt')):
		try:
			lines = req.read_text().splitlines()
		except OSError:
			continue
		for line in lines:
			line = line.strip()
			if not line or line.startswith(('#', '-', 'git+', 'http://', 'https://')):
				continue
			m = _REQ_LINE.match(line)
			if m:
				out.append((m.group(1), (m.group(2) or "").strip()))
	return out

def _from_gomod(repo: Path) -> list[tuple[str, str]]:
	gm = repo / 'go.mod'
	if not gm.exists():
		return []
	try:
		lines = gm.read_text().splitlines()
	except OSError:
		return []
	out: list[tuple[str, str]] = []
	in_block = False

	for line in lines:
		s = line.strip()
		if s.startswith('require ('):
			in_block = True
			continue
		if in_block and s == ')':
			in_block = False
			continue
		target = s[len('require '):] if s.startswith('require ') and not s.endswith('(') else (s if in_block else "")
		m = _GOMOD_REQUIRE.match(target)
		if m:
			out.append((m.group(1), m.group(2)))
	return out


def parse_dependencies(repo: Path) -> list[tuple[str, str]]:
	pairs: list[tuple[str, str]] = []

	for parser in (_from_package_json, _from_gomod, _from_requirements):
		pairs.extend(parser(repo))
	seen: set[str] = set()
	deduped: list[tuple[str, str]] = []
	for name, version in pairs:
		if name and name not in seen:
			seen.add(name)
			deduped.append((name, version))
	return deduped