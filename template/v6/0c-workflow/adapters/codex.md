# Codex adapter

The Codex adapter owns current CLI flags, structured-output parsing, session
polling, cancellation, and capability probing. It receives only the V6 request
envelope and isolated workspace. Native subagents or resume are optional and do
not change core scheduling, gates, or authorization.
