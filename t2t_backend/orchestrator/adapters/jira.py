"""
orchestrator/adapters/jira.py — Jira integration adapter.
Creates, updates, and deletes Jira issues as part of T2T workflows.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from orchestrator.adapters.base import AdapterResult, BaseAdapter, register_adapter

logger = logging.getLogger(__name__)

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://your-org.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "T2T")


class JiraAdapter(BaseAdapter):
    """
    Jira adapter — creates/updates/deletes issues.

    Params for execute:
      action:      "create_issue" | "update_issue" | "add_comment"
      summary:     Issue title
      description: Issue body
      issue_type:  "Task" | "Story" | "Bug"
      issue_key:   (for update/comment) e.g. "T2T-123"
      comment:     (for add_comment)

    Params for compensate:
      issue_key:   The key of the issue to delete/close
    """
    name = "jira"

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(username=JIRA_EMAIL, password=JIRA_API_TOKEN)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def execute(self, params: dict[str, Any]) -> AdapterResult:
        action = params.get("action", "create_issue")

        async with httpx.AsyncClient(base_url=JIRA_BASE_URL, auth=self._auth(), timeout=15) as client:
            if action == "create_issue":
                return await self._create_issue(client, params)
            elif action == "update_issue":
                return await self._update_issue(client, params)
            elif action == "add_comment":
                return await self._add_comment(client, params)
            else:
                return AdapterResult(success=False, output={}, error=f"Unknown action: {action}")

    async def _create_issue(
        self, client: httpx.AsyncClient, params: dict[str, Any]
    ) -> AdapterResult:
        payload = {
            "fields": {
                "project": {"key": JIRA_PROJECT_KEY},
                "summary": params.get("summary", "T2T Generated Task"),
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": params.get("description", "")}
                            ],
                        }
                    ],
                },
                "issuetype": {"name": params.get("issue_type", "Task")},
            }
        }
        try:
            resp = await client.post("/rest/api/3/issue", json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Jira issue created: %s", data.get("key"))
            return AdapterResult(
                success=True,
                output={"issue_key": data.get("key"), "issue_id": data.get("id")},
            )
        except httpx.HTTPStatusError as e:
            return AdapterResult(success=False, output={}, error=str(e))

    async def _update_issue(
        self, client: httpx.AsyncClient, params: dict[str, Any]
    ) -> AdapterResult:
        issue_key = params.get("issue_key")
        if not issue_key:
            return AdapterResult(success=False, output={}, error="issue_key required")
        payload = {"fields": {k: v for k, v in params.items() if k not in ("action", "issue_key")}}
        try:
            resp = await client.put(f"/rest/api/3/issue/{issue_key}", json=payload)
            resp.raise_for_status()
            return AdapterResult(success=True, output={"issue_key": issue_key, "updated": True})
        except httpx.HTTPStatusError as e:
            return AdapterResult(success=False, output={}, error=str(e))

    async def _add_comment(
        self, client: httpx.AsyncClient, params: dict[str, Any]
    ) -> AdapterResult:
        issue_key = params.get("issue_key")
        comment_text = params.get("comment", "")
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": comment_text}]}
                ],
            }
        }
        try:
            resp = await client.post(f"/rest/api/3/issue/{issue_key}/comment", json=payload)
            resp.raise_for_status()
            return AdapterResult(success=True, output={"issue_key": issue_key, "commented": True})
        except httpx.HTTPStatusError as e:
            return AdapterResult(success=False, output={}, error=str(e))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def compensate(self, params: dict[str, Any]) -> AdapterResult:
        """Closes the created issue as the compensation action."""
        issue_key = params.get("issue_key")
        if not issue_key:
            return AdapterResult(success=True, output={"skipped": "no issue_key"})

        async with httpx.AsyncClient(base_url=JIRA_BASE_URL, auth=self._auth(), timeout=15) as client:
            try:
                # Transition to "Done" or "Cancelled"
                payload = {"transition": {"id": "31"}}  # transition ID varies by project
                resp = await client.post(
                    f"/rest/api/3/issue/{issue_key}/transitions", json=payload
                )
                resp.raise_for_status()
                logger.info("Jira issue %s compensated (closed)", issue_key)
                return AdapterResult(success=True, output={"issue_key": issue_key, "closed": True})
            except httpx.HTTPStatusError as e:
                return AdapterResult(success=False, output={}, error=str(e))


# Auto-register
register_adapter(JiraAdapter())
