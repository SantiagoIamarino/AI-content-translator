import sys
try:
    from .cli import main
except ModuleNotFoundError as exc:
    sys.exit(f"Missing runtime dependency {exc.name}. Use a configured environment with requirements-runtime.txt; see README setup.")
raise SystemExit(main())
