# Agent and lease recovery

Fence the old lease, inspect the standalone workspace and provider session, and
validate any structured result against Operation, Attempt, deadline, and fencing
token. Reject late or malformed results. Re-dispatch only when the prior actor
cannot mutate authority and no external effect remains unreconciled.
