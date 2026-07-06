# Security Policy

This project drives a real (patched, sandboxed) browser via `camoufox`
against ricardo.ch's public pages and writes local CSV/JSON files. It
doesn't handle credentials, accept untrusted input beyond CLI arguments you
control, or run a server — so its attack surface is small, but real (e.g.
how URLs are constructed from input, how the pinned browser build is
fetched and verified, or how dependencies are pinned).

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue:

- Preferred: use [GitHub's private vulnerability reporting](https://github.com/danyk20/ricardo-scraper/security/advisories/new)
  for this repository.
- Alternatively, email vulnerability@danielkosc.eu with a description and,
  if possible, steps to reproduce.

Please allow a reasonable amount of time to respond and address the issue
before any public disclosure. This is a small, single-maintainer project —
response time is best-effort, not guaranteed on an SLA.

## Supported versions

Only the latest commit on `main` is supported. There are no long-term
maintenance branches.
