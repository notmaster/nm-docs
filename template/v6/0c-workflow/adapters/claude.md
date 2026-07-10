# Claude Code adapter

The Claude Code adapter owns provider permission names, instruction discovery,
session behavior, structured result parsing, cancellation, and capability
probing. Missing native resume or subagent support falls back to fresh isolated
sessions without changing core semantics.
