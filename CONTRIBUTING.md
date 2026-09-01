# Contributing to KAIROS

Thanks for your interest in contributing. KAIROS is licensed under the
**PolyForm Noncommercial License 1.0.0** — free for personal, educational, and
non-commercial use. Commercial use requires a separate license from the author.

## Ways to contribute

- Report bugs and suggest features via GitHub Issues.
- Improve the documentation (README, comments, this file).
- Fix bugs and submit pull requests.

## Before you start

1. Read [README.md](README.md) to understand the architecture.
2. Check the open issues to avoid duplicating work.
3. For anything large, open an issue first to discuss the approach.

## Development setup

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Run the agent: `python -m kairos.main`

## Code style

- Follow the existing code in each module (PEP 8, plain classes/functions).
- Do **not** add comments unless they explain something non-obvious.
- Keep it lightweight — no heavy dependencies unless justified.

## Important: never commit

- Secrets (Telegram tokens, LLM API keys, email passwords)
- User data (knowledge library, media, databases)
- Custom-created skills
- Virtual environments or build artifacts

The [.gitignore](.gitignore) already covers these. Run `git status` before committing.

## Pull request checklist

- [ ] Changes are tested locally (`python -m kairos.main` starts cleanly)
- [ ] No secrets, user data, or generated files are included
- [ ] README is updated if behavior changes
- [ ] PR description explains the what and the why

## License note

By contributing, you agree that your contributions are licensed under the same
PolyForm Noncommercial License 1.0.0 as the project.
