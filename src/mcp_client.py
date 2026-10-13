#!/usr/bin/env python3
"""Shared MCP subprocess client (issue #36).

Every screener talks to the Public MCP through this module — no exceptions.
Byte-identical transport logic to what each screener previously copy-pasted.
"""
import json
import os
import subprocess

CLI = os.environ.get("PUBLIC_MCP_CLI",
                      "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")


class McpError(RuntimeError):
    """Every transport/parse failure becomes McpError. Callers treat it as
    unknown data, never as zero."""


def _stderr_summary(stderr, max_chars=1800, max_lines=12):
    """Keep the traceback ending, where Python reports the root exception."""
    lines = (stderr or "").strip().splitlines()
    if not lines:
        return "no stderr output"
    summary = "\n".join(lines[-max_lines:])
    if len(summary) > max_chars:
        summary = "…" + summary[-(max_chars - 1):]
    return summary


def mcp_call(tool, args, timeout=120):
    """Call a Public MCP tool; return the parsed content payload.

    Raises McpError on timeout, non-zero exit, non-JSON output, unexpected
    response shape, API-level error, or unparseable content payload.
    """
    try:
        proc = subprocess.run([CLI, "call", tool, json.dumps(args)],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise McpError(f"{tool}: CLI timed out: {e}")
    if proc.returncode != 0:
        raise McpError(
            f"{tool}: CLI failed (exit {proc.returncode}); stderr tail:\n"
            f"{_stderr_summary(proc.stderr)}")
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise McpError(f"{tool}: CLI returned non-JSON output: {e}")
    if not isinstance(d, dict) or "content" not in d or not d["content"]:
        raise McpError(f"{tool}: unexpected response shape")
    if d.get("isError"):
        raise McpError(f"{tool}: {json.dumps(d)[:300]}")
    try:
        return json.loads(d["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        raise McpError(f"{tool}: unparseable content payload: {e}")
