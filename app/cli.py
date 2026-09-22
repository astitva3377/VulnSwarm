from app.orchestrator import Orchestrator
from app.config import Config
import argparse
from pathlib import Path
import sys
import pyfiglet

def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog='VulnSwarm',
		description='Agentic Code Scanner for your Repository\'s Security Needs'
	)

	subparsers = parser.add_subparsers(
		dest='command',
		required=True
	)

	scan_parser = subparsers.add_parser(
		'scan',
		help='Scan a source repo'
	)

	scan_parser.add_argument(
		'repo',
		type=Path,
		help='Path to repository'
	)

	scan_parser.add_argument(
		'--watch',
		action='store_true',
		help='Show live progress'
	)

	return parser

def validate_repository(repo: Path) -> Path:
	repo = repo.expanduser().resolve()

	if not repo.exists():
		raise ValueError(f'Repository path does not exist: {repo}')

	if not repo.is_dir():
		raise ValueError(f'Path is not a directory: {repo}')

	return repo

def run_scan(repo: Path, watch: bool) -> int:
	print(pyfiglet.figlet_format('VulnSwarm', font='slant'))
	print('Repository:', repo)
	print('Watch mode:', watch)
	print()
	print()


	config = Config.from_env()

	orchestrator = Orchestrator(
		repo=repo,
		config=config,
		watch=watch
	)

	return orchestrator.run()

def main() -> int:
	parser = build_parser()
	args = parser.parse_args()

	if args.command == 'scan':
		try:
			repo = validate_repository(args.repo)
		except ValueError as e:
			parser.error(str(e))

		return run_scan(repo=repo, watch=args.watch)

	parser.error('Unknown arguments')
	return 2

if __name__ == '__main__':
	sys.exit(main())