# AgentDojo decision: DEFER

AgentDojo is relevant for adversarial tool-agent security evaluation, especially prompt injection. It is deferred in this gate because the primary Inspect/RAG contract is not yet symmetric across the frozen A/B SHAs. Adding a second framework now would expand dependencies and produce security numbers while the main comparison remains input-blocked.

Revisit after: (1) both A/B revisions expose the same harness contract, (2) the formal 100–200 case dataset is frozen, and (3) sandbox/network policy for AgentDojo is reviewed. Until then the nine-case prompt-injection entry is mechanism design only, not a security benchmark result.

Source reviewed: https://github.com/ethz-spylab/agentdojo
