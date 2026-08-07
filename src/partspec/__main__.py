"""`python -m partspec`.

Exists for callers that hold an interpreter rather than a PATH — the MCP
adapter invokes the CLI this way so it runs against its own environment.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
