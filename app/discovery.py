import asyncio
from dataclasses import replace
from typing import cast
from app import strategy
from app.config import AgentConfig
from app.providers import agy_agent
from app.schema import Lead, Shape
from app.strategy import get_system_prompt

SHAPES: tuple[str, ...] = ("A", "B", "C", "D")

def _to_leads(final_json: dict, shape: str) -> list[Lead]:
	if not isinstance(final_json, dict):
		return []

	raw = final_json.get("leads")
	if not isinstance(raw, list):
		return []

	leads: list[Lead] = []
	for i, item in enumerate(raw):
		if not isinstance(item, dict):
			continue
		text = item.get("text")
		evidence = item.get("evidence")
		if not text or not evidence:
			continue

		confidence = item.get("confidence")
		if confidence not in ("HIGH", "MEDIUM", "LOW"):
			confidence = "LOW"
		item_shape = item.get("shape")
		if item_shape not in ("A", "B", "C", "D"):
			item_shape = shape
		source_uid = item.get("source_uid") or None
		sink_uid = item.get("sink_uid") or None
		leads.append(Lead(
			index=i, shape=cast(Shape, item_shape), text=text,
			evidence=evidence, confidence=confidence,
			source_uid=source_uid, sink_uid=sink_uid
		))
	return leads

def _dedublicate(leads: list[Lead]) -> list[Lead]:
	seen_struct: set[tuple[str, str]] = set()
	seen_lex: set[tuple[str, str]] = set()

	kept: list[Lead] = []
	for lead in leads:
		if lead.source_uid and lead.sink_uid:
			key = (lead.source_uid, lead.sink_uid)
			if key in seen_struct:
				continue
			seen_struct.add(key)
		else:
			key = (lead.shape, lead.text[:80])
			if key in seen_lex:
				continue
			seen_lex.add(key)
		kept.append(lead)
	return [replace(lead, index=i) for i, lead in enumerate(kept)]

async def _run_shape(scan_id: str, shape: str, config: AgentConfig) -> list[Lead]:
	sys_prompt = get_system_prompt(shape, scan_id)
	message = (
		f'scan_id = {scan_id}. Begin your Shape {shape} sweep now. Every mcp__vulnswarm__run_cypher call must pass scan_id="{scan_id}" and filter the query by scan_id:$scan_id.'
	)

	try:
		result = await asyncio.to_thread(agy_agent.run_agent, sys_prompt, message, json_schema=strategy.LEADS_SCHEMA, config=config)
	except Exception as e:
		print(f'Caught error during discovery fleet working: {e}')
		return []

	if not isinstance(result, dict) or "_error" in result:
		print("Received error during discovery:\n"+result.get("_error", "malformed result"))
		return []

	leads = _to_leads(result, shape)
	return leads


async def _discover_async(scan_id: str, config: AgentConfig) -> list[Lead]:
	results = await asyncio.gather(*(_run_shape(scan_id, shape, config) for shape in SHAPES))
	all_leads = [lead for shape_leads in results for lead in shape_leads]
	return _dedublicate(all_leads)

def discover(scan_id: str, config: AgentConfig) -> list[Lead]:
	return asyncio.run(_discover_async(scan_id, config))