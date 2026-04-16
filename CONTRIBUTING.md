# Contributing to pyfreepbx

Thanks for your interest in contributing.

## Development Setup

```bash
git clone https://github.com/dannielperez/pyfreepbx.git
cd pyfreepbx
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Checks

```bash
pytest                    # unit tests
ruff check src/ tests/    # lint
mypy src/                 # type check
```

All three must pass before submitting a PR.

## Code Style

- Ruff handles formatting and import sorting
- Type annotations on all public functions
- Pydantic models for all structured data
- `extra="allow"` on models with provisional fields

## Architecture Rules

- **GraphQL** for config/inventory data, **AMI** for live operational state
- AMI is always optional — services must degrade gracefully when it's absent
- Use `NotSupportedError` for operations not yet confirmed via schema introspection
- Don't add async, ARI, or direct DB access — those are out of scope

## Submitting Changes

1. Open an issue describing the change
2. Fork and create a branch from `main`
3. Write tests for new behavior
4. Ensure all checks pass
5. Submit a PR referencing the issue
