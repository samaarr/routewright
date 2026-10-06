#!/usr/bin/env python3
"""Export the canonical API JSON Schema to schema.json.

Used by the frontend ``gen:types`` script to generate TypeScript types.
Run from the ``backend/`` directory::

    python scripts/export_schema.py [output_path]

Defaults to writing ``schema.json`` in the current directory.
The output path is typically ``../frontend/schema.json`` for the CI
drift-check workflow.
"""

import json
import os
import sys

# Use test environment so no real API keys or network calls are required.
os.environ.setdefault("APP_ENV", "test")

# Ensure the ``app`` package is importable when invoked as a script.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.response import ContractRoot

if __name__ == "__main__":
    output_path = sys.argv[1] if len(sys.argv) > 1 else "schema.json"
    schema = ContractRoot.model_json_schema()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
        f.write("\n")
    print(f"Schema written to {output_path}", file=sys.stderr)
