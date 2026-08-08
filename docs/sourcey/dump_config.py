"""Dump jupyter_mcp_server's configuration surface from the installed package
(pydantic model fields with descriptions/defaults) to JSON for the generated
configuration page.

    python dump_config.py <out.json>
"""

import json
import sys

from jupyter_mcp_server import config as cfg_mod

model = None
for attr in dir(cfg_mod):
    obj = getattr(cfg_mod, attr)
    if isinstance(obj, type) and hasattr(obj, "model_fields") and obj.model_fields:
        if model is None or len(obj.model_fields) > len(model.model_fields):
            model = obj

fields = []
for name, f in model.model_fields.items():
    default = f.get_default()
    try:
        json.dumps(default)
    except TypeError:
        default = repr(default)
    fields.append(
        {
            "name": name,
            "type": str(f.annotation).replace("typing.", ""),
            "default": default,
            "description": f.description or "",
        }
    )

out = {"model": model.__name__, "source_file": "jupyter_mcp_server/config.py", "fields": fields}
# newline="\n" so regenerating on Windows produces the same bytes as CI does.
with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, indent=1)
    fh.write("\n")
print(model.__name__, len(fields), "fields ->", sys.argv[1])
