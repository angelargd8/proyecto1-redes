
import json, anyio
from typing import Dict, Any
from mcp import ClientSession
from mcp.client.sse import sse_client

async def _ztr_call_mcp_http(tool: str, args: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    async with sse_client(url=base_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as sess:
            await sess.initialize()
            res = await sess.call_tool(tool, args or {})
            for item in getattr(res, "content", []):
                if getattr(item, "value", None) is not None:
                    return item.value if isinstance(item.value, dict) else {"value": item.value}
                if getattr(item, "text", None):
                    try:
                        return json.loads(item.text)
                    except Exception:
                        return {"text": item.text}
    return {"error": "Respuesta vacía del MCP ZTR"}

def ztr_execute_tool_http(tool: str, args: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    try:
        return anyio.run(_ztr_call_mcp_http, tool, args, base_url)
    except Exception as e:
        import traceback
        return {"error": f"Fallo MCP SSE: {e}", "trace": traceback.format_exc(limit=3)}
