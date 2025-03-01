# CLAUDE.md - ista-calista

## Build/Test/Lint Commands
- Install dependencies: `pip install -r requirements.txt` or `pip install -e .`
- Install dev dependencies: `pip install -e ".[dev]"` (if configured)
- Lint code: `flake8 .` or `pylint .`
- Type checking: `mypy .`
- Format code: `black .` and `isort .`
- Testing: `pytest tests/`

## Code Style Guidelines
- Follow [Home Assistant development guidelines](https://developers.home-assistant.io/docs/development_guidelines)
- Imports: Sort with `isort` using standard sections
- Formatting: Use `black` with 88 character line length
- Type hints: Required for all function parameters and return values
- Naming: snake_case for variables/functions, PascalCase for classes
- Error handling: Use specific exceptions, log appropriately with `_LOGGER`
- Documentation: Docstrings for all public methods (Google style)
- Constants: Define in `const.py`, use uppercase names
- Avoid imports in `__init__.py` that might cause circular dependencies
- Follow Home Assistant's patterns for config flows and data coordinators