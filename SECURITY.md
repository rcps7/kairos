# Security Policy

Kairos is a self-hosted, single-workstation agent. This document describes the
security model, the hardening measures in place, and how to report issues.

## Trust model

- **Local-first.** All user data (config, keys, databases, skills) lives under
  `~/.kairos` and the configured storage root. The self-updater never touches
  user data.
- **Secrets** (Telegram token, LLM API keys, MiroFish Zep key, email password)
  are stored in the **OS keyring**, never in `config.json`. If the keyring is
  unavailable, secrets are *not* written to disk.
- **Skills are untrusted code.** They run in an isolated subprocess with a
  temporary working directory and a stripped environment, and may only call a
  small whitelisted subset of engine capabilities via RPC. This is process
  isolation, not a hardened OS sandbox.
- **Peer collaboration** uses TLS with certificate **fingerprint pinning** plus
  a challenge–response client authentication and a human-verified **SAS**.

## Hardening measures

| Area | Measure |
|------|---------|
| Telegram | **Manual allowlist** of user IDs; every command and button is authorized. |
| Skills | Name validation + path confinement; subprocess sandbox; whitelisted engine RPC. |
| Secrets | Keyring-only; never persisted on keyring failure; config ACL-restricted. |
| Config | Atomic writes (tmp + replace) under a lock; recursive default backfill. |
| Updater | GitHub release asset **sha256** verification; safe archive extraction (no zip-slip); explicit install confirmation. |
| Runtime bootstrap | Safe archive extraction; prefers trusted DLL sources. |
| Collaboration | SSRF host policy (loopback/link-local/metadata blocked); frame caps; strict message schemas; rate limits; cert-expiry check. |
| Watchdog | Kill socket requires a per-run **token**; PID image verified before terminating. |

## Reporting

Report vulnerabilities privately to the repository owner (`rcps7`) via GitHub
Security Advisories. Please do not open public issues for security problems.
