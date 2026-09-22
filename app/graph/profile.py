from dataclasses import dataclass, field


@dataclass
class Profile:
	name: str

	# Shape to language specific usage if required configured with global object
	request_source_names: frozenset[str] = frozenset()

	# for a generic profile, all entry points should be tainted
	entrypoint_params_are_sources: bool = False

	# describe how handlers are wired in the language stack
	entrypoint_hint: str = ''

	# examples of where untrusted input enters; used by discovery agent
	source_examples: tuple[str, ...] = ()

	# examples of sink call names; bypass hardcoding in prompts
	sink_hints: dict[str, tuple[str, ...]] = field(default_factory=dict)


GENERIC = Profile(
	name='generic',
	request_source_names=frozenset(),
	entrypoint_params_are_sources=True,
	source_examples=(
		"the parameters of EntryPoint methods — query (:EntryPoint)-[:ENTERS_AT]->(:CpgMethod) and "
        "treat that method's parameters as untrusted input",
	),
	sink_hints={
        "code_exec": ("eval", "exec", "system", "spawn"),
        "sql": ("execute", "query", "raw"),
        "redirect": ("redirect",),
    },
	entrypoint_hint=(
        "No framework assumed: entry points are first-party methods that nothing else in the code "
        "calls (call-graph roots) — request handlers, exported API, main. Their parameters are the "
        "untrusted inputs."
    ),
)