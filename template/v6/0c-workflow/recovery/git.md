# Git recovery

Fetch the configured remote again, compare observed local/remote refs with the
recorded expected and proposed result SHAs, and recompute the result tree.
Target movement invalidates old Git evidence. Never force a side of a conflict,
discard a candidate, or retry a protected update until its prior effect is
observed conclusively.
