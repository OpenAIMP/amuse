#!/usr/bin/env python3
"""Second-opinion verification via musellm (issue #13).

Routes amuse recommendations through an independent second opinion before
they become actionable. Supports two interfaces:

1. A2A agent: musellm as a separate agent (subagent or external service)
2. API: musellm as an LLM endpoint (OpenAI-compatible API)

Fail-closed: on disagreement or error, the recommendation requires human
review. All opinions are logged with the recommendation/ledger.

Configuration via gates.yaml `second_opinion:` section or environment:
    MUSELLM_MODE: "a2a" | "api" | "disabled"
    MUSELLM_API_URL: endpoint URL (api mode)
    MUSELLM_API_KEY: bearer token (api mode, via env only)
    MUSELLM_MODEL: model name (api mode)
    MUSELLM_AGENT_ID: agent identifier (a2a mode)
    MUSELLM_TIMEOUT: seconds before fail-closed (default 30)
"""

import json
import os
import time
import urllib.request
import urllib.error

# ---- configuration ----

def _config():
    """Load second-opinion config from env with sane defaults."""
    return {
        "mode": os.environ.get("MUSELLM_MODE", "disabled").lower(),
        "api_url": os.environ.get("MUSELLM_API_URL", ""),
        "api_key": os.environ.get("MUSELLM_API_KEY", ""),
        "model": os.environ.get("MUSELLM_MODEL", "musellm-1"),
        "agent_id": os.environ.get("MUSELLM_AGENT_ID", ""),
        "timeout": int(os.environ.get("MUSELLM_TIMEOUT", "30")),
    }


# ---- evidence packaging ----

def build_evidence(candidate, stock_data=None):
    """Package supporting evidence for the second opinion.

    Sends evidence, not just the conclusion, so musellm can independently
    verify the recommendation.
    """
    return {
        "symbol": candidate.get("symbol"),
        "strategy": candidate.get("strategy"),
        "recommendation": candidate.get("recommendation"),
        "credit_total": candidate.get("credit_total"),
        "max_loss_total": candidate.get("max_loss_total"),
        "expected_value": candidate.get("expected_value_delta_proxy"),
        "win_prob_est": candidate.get("win_prob_est_delta_proxy"),
        "return_on_risk": candidate.get("return_on_risk"),
        "dte": candidate.get("dte"),
        "expiration": candidate.get("expiration"),
        "gates": [
            {"step": s.get("step"), "name": s.get("name"),
             "status": s.get("status"), "detail": s.get("detail")}
            for s in (candidate.get("steps") or [])
        ],
        "reasons": candidate.get("reasons", []),
        "kelly_sizing": candidate.get("kelly_sizing", {}),
    }


def build_prompt(evidence):
    """Build the verification prompt for musellm."""
    return (
        "You are an independent options-trading reviewer. "
        "Verify the following recommendation. Respond with JSON: "
        '{"verdict": "concur" | "dissent", "confidence": 0.0-1.0, "reasons": [...]}\n\n'
        f"Evidence:\n{json.dumps(evidence, indent=2)}\n\n"
        "Check: (1) Are the Greeks and pricing reasonable? "
        "(2) Do the gate results support the recommendation? "
        "(3) Is the risk/reward sane? "
        "(4) Any red flags in the evidence?"
    )


# ---- A2A adapter ----

def _query_a2a(evidence, cfg):
    """Query musellm as an A2A agent.

    In production, this would use the agent's messaging protocol.
    For now, this is a stub that documents the interface — the actual
    agent invocation depends on the deployment (subagent, HTTP, etc.).
    """
    agent_id = cfg.get("agent_id")
    if not agent_id:
        return {"error": "MUSELLM_AGENT_ID not configured for a2a mode"}

    # Stub: in a real deployment, this would send the evidence to the
    # agent and await a structured response.
    # The agent contract:
    #   Input: {"evidence": {...}, "prompt": "..."}
    #   Output: {"verdict": "concur"|"dissent", "confidence": float, "reasons": [...]}
    return {
        "error": "a2a agent invocation not yet wired — configure agent transport",
        "agent_id": agent_id,
    }


# ---- API adapter ----

def _query_api(evidence, cfg):
    """Query musellm as an OpenAI-compatible LLM API endpoint."""
    url = cfg.get("api_url")
    api_key = cfg.get("api_key")
    if not url:
        return {"error": "MUSELLM_API_URL not configured for api mode"}
    if not api_key:
        return {"error": "MUSELLM_API_KEY not configured for api mode"}

    prompt = build_prompt(evidence)
    payload = json.dumps({
        "model": cfg.get("model", "musellm-1"),
        "messages": [
            {"role": "system",
             "content": "You are an independent options-trading reviewer."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }).encode("utf-8")

    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 30)) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = (result.get("choices", [{}])[0]
                   .get("message", {}).get("content", ""))
        # Parse the JSON verdict from the response
        # Handle markdown code fences
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())
    except urllib.error.URLError as e:
        return {"error": f"API unreachable: {e}"}
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return {"error": f"bad API response: {e}"}
    except Exception as e:
        return {"error": f"api query failed: {e}"}


# ---- main entry point ----

def get_second_opinion(candidate, stock_data=None, cfg=None):
    """Get musellm's second opinion on a candidate.

    Returns a dict with:
      - verdict: "concur" | "dissent" | "abstain" (on error/timeout)
      - confidence: 0.0-1.0 (if provided)
      - reasons: list of strings
      - latency_ms: query time
      - mode: "a2a" | "api" | "disabled"
      - error: set on failure

    Fail-closed: any error or dissent means human review is required.
    """
    cfg = cfg or _config()
    mode = cfg.get("mode", "disabled")
    evidence = build_evidence(candidate, stock_data)

    if mode == "disabled":
        return {
            "verdict": "abstain",
            "mode": "disabled",
            "reasons": ["second opinion disabled"],
            "latency_ms": 0,
        }

    start = time.time()
    if mode == "a2a":
        result = _query_a2a(evidence, cfg)
    elif mode == "api":
        result = _query_api(evidence, cfg)
    else:
        result = {"error": f"unknown mode: {mode}"}
    latency_ms = int((time.time() - start) * 1000)

    # Normalize the result
    if "error" in result:
        return {
            "verdict": "abstain",
            "mode": mode,
            "reasons": [result["error"]],
            "latency_ms": latency_ms,
            "error": result["error"],
        }

    verdict = result.get("verdict", "abstain")
    if verdict not in ("concur", "dissent"):
        verdict = "abstain"

    return {
        "verdict": verdict,
        "confidence": result.get("confidence"),
        "reasons": result.get("reasons", []),
        "mode": mode,
        "latency_ms": latency_ms,
    }


def is_actionable(candidate, second_opinion):
    """Fail-closed gate: is this recommendation actionable?

    Returns (actionable: bool, reason: str).
    - concur -> actionable
    - dissent -> NOT actionable, needs human review
    - abstain (error/timeout/disabled) -> NOT actionable, needs human review
      (unless mode is disabled, in which case defer to primary recommendation)
    """
    verdict = second_opinion.get("verdict")
    mode = second_opinion.get("mode")

    if mode == "disabled":
        # No second opinion configured; defer to primary
        return True, "second opinion disabled, primary recommendation stands"

    if verdict == "concur":
        conf = second_opinion.get("confidence")
        return True, f"musellm concurs (confidence {conf})"

    if verdict == "dissent":
        reasons = "; ".join(second_opinion.get("reasons", ["no reason given"]))
        return False, f"musellm dissents: {reasons} — human review required"

    # abstain: fail closed
    reasons = "; ".join(second_opinion.get("reasons", ["no reason given"]))
    return False, f"second opinion unavailable ({reasons}) — human review required"


def log_opinion(candidate, second_opinion, log_path=None):
    """Log the second opinion alongside the recommendation.

    Appends a JSON line to the log file (or returns the record).
    """
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "symbol": candidate.get("symbol"),
        "strategy": candidate.get("strategy"),
        "primary_recommendation": candidate.get("recommendation"),
        "second_opinion": second_opinion,
    }
    if log_path:
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    return record
