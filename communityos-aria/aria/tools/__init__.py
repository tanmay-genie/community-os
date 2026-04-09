"""
aria/tools/__init__.py — Tool registry.
Add new tool modules here.
"""

from aria.tools import member, admin


def register_all_tools(mcp, role: str = "member"):
    """
    Register tools based on user role.
    role: 'member' | 'admin' | 'both'
    """
    if role in ("member", "both"):
        member.register(mcp)

    if role in ("admin", "both"):
        admin.register(mcp)
