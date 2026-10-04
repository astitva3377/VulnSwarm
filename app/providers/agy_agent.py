import json
from pathlib import Path
import subprocess
from app.config import AgentConfig

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()

def _build_cmd(*, prompt: str, json_schema: str | dict | None = None, config: AgentConfig) -> list[str]:
	cmd = [
		"agy",
		"-p",
		prompt,
		"--output-format",
		"json"
	]

	if config.model:
		cmd += ["--model", config.model]
	if config.effort:
		cmd += ["--effort", config.effort]

	if json_schema is not None:
		schema_str = (
			json.dumps(json_schema)
			if isinstance(json_schema, dict)
			else json_schema
		)
		cmd += ["--json-schema", schema_str]

	return cmd

def _run_once(cmd: list[str]) -> dict:
	try:
		r = subprocess.run(
			cmd,
			text=True,
			capture_output=True,
			stdin=subprocess.DEVNULL,
			cwd=str(_REPO_ROOT)
		)
	except OSError as e:
		return {"_error": f"AGY call failed with {e}"}

	stdout = (r.stdout or "").strip()

	if not stdout:
		return {
			"_error": (
				f"agy exited {r.returncode} without JSON output"
				f" | stderr: {(r.stderr or '').strip()[:500]}"
			)
		}

	try:
		envelope = json.loads(stdout)
	except json.JSONDecodeError as e:
		return {
			"_error": (
				f"agy returned invalid JSON: {e}"
				f" | stdout: {stdout}"
			)
		}

	if r.returncode != 0:
		return {
			"_error": (
				f"agy exited {r.returncode}: "
				f"{envelope.get('error', (r.stderr or '').strip())}"
			)
		}

	if envelope.get('status') != "SUCCESS":
		return {
			"_error": (
				f"agy run failed: "
				f"{envelope.get('status')}: "
				f"{envelope.get('error', 'unknown error')}"
			)
		}

	structured = envelope.get("structured_output")

	if not isinstance(structured, dict):
		return {"_error": "agy response did not contain structured_output object"}

	return structured

def run_agent(system: str, message: str, *, json_schema: str | dict | None = None, config: AgentConfig) -> dict:
	prompt = f"""
{system}

USER TASK:
{message}
""".strip()

	cmd = _build_cmd(prompt=prompt, json_schema=json_schema, config=config)
	return _run_once(cmd)