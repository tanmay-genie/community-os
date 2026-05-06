"""
server.py — ARIA MCP Server (Chat Mode)
Run: uv run aria
Starts FastMCP server on port 9000 (SSE transport).
Chat clients connect here. Voice agent also uses this as tool source.
"""
 
from mcp.server.fastmcp import FastMCP
from aria.tools import register_all_tools
from aria.config import settings
 
# Single MCP instance — registers both member + admin tools
# Role-based filtering happens at the agent/prompt level
mcp = FastMCP(
    name=settings.ARIA_SERVER_NAME,
    instructions=(
        "You are ARIA — CommunityOS AI Assistant. "
        "You help residents book amenities, raise tickets, check events, "
        "and manage dues. Admins get insights, escalation management, "
        "and content generation. Always be helpful, warm, and efficient."
    ),
)
 
# Register all tools (member + admin)
register_all_tools(mcp, role="both")
 
 
def main():
    import uvicorn
 
    try:
        # FastMCP >= 2.x
        app = mcp.sse_app()
    except AttributeError:
        try:
            app = mcp.streamable_http_app()
        except AttributeError:
            app = mcp.get_asgi_app()
 
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.MCP_SERVER_PORT,  # 9000 from config / .env
    )
 
 
if __name__ == "__main__":
    main()