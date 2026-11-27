# Isolation & Cleanup Specification (20261126T004342Z)
- `IsolationSandbox`: unique temp root, `resolve_confined_path` rejecting traversal/symlinks/reparse points.
- `OutboundGuard`: deny-by-default for external network and unallowlisted loopback ports.
- `OwnedResourceTracker`: bounded cleanup of owned tasks, threads, SQLite handles, and leases.
