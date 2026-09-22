from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess


class JoernError(RuntimeError):
	pass

@dataclass(slots=True)
class JoernResult:
	repo: Path
	output_dir: Path
	cpg_path: Path

@dataclass
class JoernExportResult:
	output_dir: Path
	cpg_path: Path

class JoernAdapter:

	parse_binary: str = "joern-parse.bat"
	export_binary: str = "joern-export.bat"

	def __init__(
		self,
		timeout: int = 1800
	) -> None:
		self.timeout = timeout

	def validate(self, binary: str) -> None:
		executable = shutil.which(binary)

		if executable is None:
			raise JoernError(f"Joern executable '{binary}' was not found in PATH")

	def parse(
		self,
		repo: Path,
		output_dir: Path
	) -> JoernResult:

		repo = repo.resolve()
		output_dir = output_dir.resolve()

		if not repo.exists():
			raise JoernError(f'Repo does not exist: {repo}')
		if not repo.is_dir():
			raise JoernError(f'Repo is not a directory: {repo}')

		output_dir.mkdir(parents=True, exist_ok=True)

		self.validate(JoernAdapter.parse_binary)

		cpg_path = output_dir / 'cpg.bin'

		if cpg_path.is_file():
			print('  - Skipping CPG creation')
			return JoernResult(
				repo=repo,
				output_dir=output_dir,
				cpg_path=cpg_path
			)

		command = [
			JoernAdapter.parse_binary,
			str(repo),
			"--output",
			str(cpg_path)
		]

		try:
			completed = subprocess.run(
				command,
				capture_output=True,
				text=True,
				timeout=self.timeout,
				check=False
			)
		except subprocess.TimeoutExpired as e:
			raise JoernError(f'Joern timed out after {self.timeout} seconds') from e
		except OSError as e:
			raise JoernError(f'Failed to execute Joern: {e}') from e

		if completed.returncode != 0:
			raise JoernError(
				'Joern Failed\n\n'
				f'stdout:\n{completed.stdout}\n\n'
				f'stderr:\n{completed.stderr}\n\n'
			)

		if not cpg_path.exists():
			raise JoernError(f'Joern completed execution successfully but expected CPG was not found at: {cpg_path}')

		return JoernResult(
			repo=repo,
			output_dir=output_dir,
			cpg_path=cpg_path
		)

	def export_graph(self, cpg_path: Path, output_dir: Path) -> JoernExportResult:
		cpg_path = cpg_path.resolve()
		output_dir = output_dir.resolve()

		if not cpg_path.exists():
			raise JoernError(f'CPG Path does not exist: {cpg_path}')
		
		if output_dir.exists():
			print('  - Skipping export')
			return JoernExportResult(
				cpg_path=cpg_path,
				output_dir=output_dir
			)

		self.validate(JoernAdapter.export_binary)

		command = [
			JoernAdapter.export_binary,
			str(cpg_path),
			"--out",
			str(output_dir),
			"--repr=all",
			"--format=graphson"
		]

		try:
			completed = subprocess.run(
				command,
				capture_output=True,
				text=True,
				timeout=self.timeout,
				check=False
			)
		except subprocess.TimeoutExpired as e:
			raise JoernError(f'Joern export failed after {self.timeout}') from e
		except OSError as e:
			raise JoernError(f'Failed to export from Joern: {e}')

		if completed.returncode != 0:
			raise JoernError(
				"Joern export failed\n\n"
				f'stdout:\n{completed.stdout}\n\n'
				f'stderr:\n{completed.stderr}\n\n'
			)

		return JoernExportResult(
			cpg_path=cpg_path,
			output_dir=output_dir
		)