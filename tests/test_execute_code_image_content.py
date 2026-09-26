# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Images travel once across the real MCP/Jupyter execution path."""

import json

import pytest

from .test_common import timeout_wrapper


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_execute_code_image_bytes_travel_once(mcp_client_parametrized):
    async with mcp_client_parametrized as client:
        result = await client._session.call_tool(
            "execute_code",
            arguments={
                "code": (
                    "import matplotlib\n"
                    "matplotlib.use('Agg')\n"
                    "import matplotlib.pyplot as plt\n"
                    "from IPython.display import Image, display\n"
                    "from io import BytesIO\n"
                    "fig, ax = plt.subplots(figsize=(4, 3))\n"
                    "ax.plot([0, 1], [0, 1])\n"
                    "buffer = BytesIO()\n"
                    "fig.savefig(buffer, format='png')\n"
                    "plt.close(fig)\n"
                    "display(Image(data=buffer.getvalue()))\n"
                )
            },
        )
        wire = result.model_dump(by_alias=True, exclude_none=True, mode="json")
        assert not wire.get("isError", False)
        images = [block for block in wire["content"] if block["type"] == "image"]
        assert len(images) == 1
        data = images[0]["data"]
        assert data
        assert data not in json.dumps(wire["structuredContent"])
        assert json.dumps(wire).count(data) == 1
        assert wire["structuredContent"]["images"] == 1
