"""List all extensions from FreePBX.

Usage:
    export FREEPBX_HOST=pbx.example.com
    export FREEPBX_API_TOKEN=your-token
    python examples/list_extensions.py
"""

from pyfreepbx import FreePBX

with FreePBX.from_env() as pbx:
    extensions = pbx.extensions.list()
    for ext in extensions:
        print(f"  {ext.extension:6s}  {ext.name}")
    print(f"\nTotal: {len(extensions)} extensions")
