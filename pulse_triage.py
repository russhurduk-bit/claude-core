#!/usr/bin/env python3
"""
Pulse Triage - a cheap first-pass filter running on free LLM tiers.

Reads the pulse context from stdin and decides: SKIP or NEED_CLAUDE.
On SKIP the expensive top-tier agent is never invoked, saving quota.

Output: a single JSON line on stdout:
  {"verdict":"SKIP|NEED_CLAUDE","reason":"...","urgency":"low|normal|high"}
Exit code is always 0 (if triage itself fails, it falls back to NEED_CLAUDE).

API keys are read from the environment (OPENROUTER_API_KEY, GROQ_API_KEY).
"""
import sys, os, json, urllib.request, urllib.error, time

# Fallback ladder of free models - if one returns 429, try the next.
FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
]

GROQ_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
]

APP_REFERER = os.environ.get("APP_REFERER", "https://example.com")


def find_openrouter_key():
    return os.environ.get("OPENROUTER_API_KEY")


def find_groq_key():
    return os.environ.get("GROQ_API_KEY")


SYSTEM_PROMPT = """You are the triage agent of a background AI "pulse" system.

Your job: look at the state of the infrastructure (systemd, disk, RAM, logs,
tasks) and decide whether the SENIOR agent (a top-tier model that costs quota)
needs to be woken up.

RULES:
- SKIP if everything is normal: no failed units, no critical log errors, no
  pending tasks, disk/RAM within limits.
- NEED_CLAUDE if:
  * failed systemd units
  * journal errors indicating a real problem (not warning, not info)
  * a pending task from the owner in the task queue
  * a stuck service (not answering its healthcheck)
  * disk >90% / swap active
  * an anomaly that requires analysis

Urgency:
- low - there is a problem but it is not on fire
- normal - standard case
- high - urgent, act immediately (service down, credits running out, breach)

OUTPUT FORMAT: exactly one JSON line, no explanations, no code blocks:
{"verdict":"SKIP","reason":"short reason","urgency":"low"}
or
{"verdict":"NEED_CLAUDE","reason":"what needs attention","urgency":"normal"}"""


def call_groq(key, model, user_content, timeout=30):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 400,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "pulse-triage/1.0",
        },
    )
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return r["choices"][0]["message"].get("content") or ""


def call_openrouter(key, model, user_content, timeout=30):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 400,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": APP_REFERER,
            "X-Title": "pulse-triage",
        },
    )
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    choice = r["choices"][0]["message"]
    content = choice.get("content") or ""
    # Some reasoning models put the final answer in `reasoning` with content=None
    if not content and choice.get("reasoning"):
        content = choice["reasoning"]
    return content


def parse_verdict(text):
    # Look for JSON in the last 10 lines
    for line in reversed([l.strip().strip("`").strip() for l in text.strip().split("\n") if l.strip()][-10:]):
        if line.startswith("{") and line.endswith("}"):
            try:
                j = json.loads(line)
                if "verdict" in j and j["verdict"] in ("SKIP", "NEED_CLAUDE"):
                    return j
            except Exception:
                pass
    # Hard fallback - if the text says SKIP and shows no problem markers
    if "SKIP" in text.upper() and "NEED_CLAUDE" not in text.upper():
        return {"verdict": "SKIP", "reason": "parsed from text", "urgency": "low"}
    return None


def main():
    context = sys.stdin.read()
    key = find_openrouter_key()
    if not key:
        print(json.dumps({"verdict": "NEED_CLAUDE", "reason": "triage: no OpenRouter key", "urgency": "normal"}))
        return

    for model in FREE_MODELS:
        try:
            t = time.time()
            reply = call_openrouter(key, model, context)
            elapsed = time.time() - t
            verdict = parse_verdict(reply)
            if verdict:
                verdict["_model"] = model
                verdict["_elapsed"] = round(elapsed, 1)
                print(json.dumps(verdict, ensure_ascii=False))
                return
            # couldn't parse - try the next model
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue  # rate limited - next model
            continue
        except Exception:
            continue

    # OpenRouter free tier is down - try Groq (also free tier)
    gkey = find_groq_key()
    if gkey:
        for gmodel in GROQ_MODELS:
            try:
                t = time.time()
                reply = call_groq(gkey, gmodel, context)
                elapsed = time.time() - t
                verdict = parse_verdict(reply)
                if verdict:
                    verdict["_model"] = f"groq/{gmodel}"
                    verdict["_elapsed"] = round(elapsed, 1)
                    print(json.dumps(verdict, ensure_ascii=False))
                    return
            except Exception:
                continue

    # Everything failed - safer to wake the senior agent
    print(json.dumps({"verdict": "NEED_CLAUDE", "reason": "triage: all free models failed (OR+Groq)", "urgency": "normal"}))


if __name__ == "__main__":
    main()
