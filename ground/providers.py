"""Model providers for the pilot. Two roles, several backends, one interface each.

System One (fast typed judgments over a state + questions):
  - TypeSafeSystemOne   : jev via https://api.typesafe.ai/v1/systemone   (default)
  - OpenAISystemOne     : any OpenAI-compatible chat endpoint (OpenAI, LM Studio, llama.cpp, vLLM),
                          emulates the same answer shape with a JSON response
System Two (slow reasoning: pick a goal, look at the frame):
  - ClaudeCli           : the local `claude` CLI in print mode with a JSON schema (default; Sonnet 5)
  - AnthropicApi        : the Anthropic Messages API when ANTHROPIC_API_KEY is set
  - OpenAIChat          : an OpenAI-compatible chat endpoint

Both roles return plain dicts so the pilot never depends on a vendor SDK.
"""
import base64
import json
import os
import subprocess
import time

import requests

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def load_env_key(name, extra_files=()):
    if os.environ.get(name):
        return os.environ[name].strip()
    for f in extra_files:
        if os.path.exists(f):
            for line in open(f, encoding="utf-8"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return None


# ---------------------------------------------------------------- System One
class TypeSafeSystemOne:
    name = "jev"

    def __init__(self, api_key, model="jev-latest"):
        self.api_key, self.model = api_key, model

    def ask(self, state, questions):
        t0 = time.time()
        r = requests.post(TYPESAFE_ENDPOINT, headers={"Authorization": f"Bearer {self.api_key}"},
                          json={"state": state, "model": self.model, "questions": questions}, timeout=10)
        r.raise_for_status()
        body = r.json()
        return {"answers": body["answers"], "latency_ms": int((time.time() - t0) * 1000), "model": body.get("model", self.model),
                "request_id": r.headers.get("x-typesafe-request-id"), "usage": body.get("usage")}


class OpenAISystemOne:
    """Same contract as TypeSafeSystemOne over a chat endpoint; one JSON object with a choice per question."""
    name = "openai-compatible"

    def __init__(self, base_url, api_key="none", model="gpt-4o-mini"):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def ask(self, state, questions):
        t0 = time.time()
        spec = {qid: {"question": q["instructions"]["question"], "options": {k: v["what"] for k, v in q["criteria"].items()}}
                for qid, q in questions.items()}
        prompt = ("You are a System One judge: answer every question with exactly one of its option names. "
                  "Reply with a JSON object mapping question id to the chosen option name and nothing else.\n"
                  f"STATE:\n{json.dumps(state)}\nQUESTIONS:\n{json.dumps(spec)}")
        r = requests.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"},
                          json={"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                                "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        picked = json.loads(text)
        answers = {}
        for qid, q in questions.items():
            options = list(q["criteria"])
            c = picked.get(qid) if picked.get(qid) in options else options[0]
            answers[qid] = {"type": "choice", "choice": c, "confidence": 1.0, "probabilities": {o: float(o == c) for o in options}}
        return {"answers": answers, "latency_ms": int((time.time() - t0) * 1000), "model": self.model}


# ---------------------------------------------------------------- System Two
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "enum": ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]},
        "steer_hint": {"type": "string", "enum": ["none", "ahead", "left", "right", "behind"]},
        "frame_rate_hz": {"type": "integer", "minimum": 0, "maximum": 20},
        "rationale": {"type": "string", "maxLength": 300},
        "frame_note": {"type": "string", "maxLength": 200},
    },
    "required": ["goal", "rationale"],
    "additionalProperties": False,
}

SYSTEM_TWO_PROMPT = (
    "You are the tactical planner (System Two) for a Doom player flown through a real mission stack: "
    "your decisions become SET_GOAL commands uplinked through Yamcs to an F Prime flight computer that "
    "hosts the game. A fast System One model (jev) handles the moment-to-moment controls; you set the goal it "
    "serves. You get the latest telemetry in words and, when available, the last downlinked frame. "
    "Nobody knows the level layout: the onboard navigator builds its own map from a range camera and explores toward "
    "unexplored frontiers; pickups and enemies count only once they have been seen. Choose the goal for the next few seconds. "
    "Prefer survival, then combat, then supplies, then exploring to find the exit. If the frame shows an opening, a door, "
    "a lit corridor or an exit sign worth heading for, give steer_hint (ahead/left/right/behind) and the navigator will favour "
    "frontiers that way for a while; otherwise say none. "
    "Say in one or two sentences why. If the frame shows something the telemetry does not, mention it in frame_note. "
    "Optionally lower frame_rate_hz if the downlink looks congested (frames arriving late), otherwise omit it."
)


class ClaudeCli:
    name = "claude-cli"

    def __init__(self, model="sonnet", exe=None):
        self.model = model
        self.exe = exe or os.environ.get("CLAUDE_EXE", "claude")

    def structured(self, system, prompt, schema):
        """One schema-constrained call with no tools: the plain CLI path uses Sonnet only."""
        cmd = [self.exe, "-p", "--model", self.model, "--no-session-persistence", "--output-format", "json",
               "--json-schema", json.dumps(schema), "--system-prompt", system]
        env = dict(os.environ, CLAUDECODE="", DISABLE_NON_ESSENTIAL_MODEL_CALLS="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=300, env=env)
        if out.returncode != 0:
            raise RuntimeError(f"claude exited {out.returncode}: {out.stderr[-400:]}")
        result = json.loads(out.stdout)
        data = result.get("structured_output") or json.loads(result.get("result", "{}"))
        usage = result.get("modelUsage", {})
        data["model"] = ",".join(usage.keys()) or self.model
        data["cost_usd"] = result.get("total_cost_usd")
        data["tokens"] = {m: [u.get("inputTokens", 0) + u.get("cacheReadInputTokens", 0) + u.get("cacheCreationInputTokens", 0), u.get("outputTokens", 0)] for m, u in usage.items()}
        return data

    def plan(self, situation, image_path=None):
        prompt = "SITUATION (telemetry as words):\n" + json.dumps(situation, indent=1)
        cmd = [self.exe, "-p", "--model", self.model, "--no-session-persistence", "--output-format", "json",
               "--json-schema", json.dumps(PLAN_SCHEMA), "--system-prompt", SYSTEM_TWO_PROMPT]
        if image_path and os.path.exists(image_path):
            # Reading the image makes the CLI run a ~1k-token Haiku helper (tool plumbing); the plan itself is
            # Sonnet. A Sonnet-only run uses --system-two anthropic (API key) or --no-vision.
            cmd += ["--allowedTools", "Read"]
            prompt += f"\n\nThe last downlinked frame is the image file {image_path}. Read it before deciding."
        t0 = time.time()
        env = dict(os.environ, CLAUDECODE="")
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=180, env=env)
        if out.returncode != 0:
            raise RuntimeError(f"claude exited {out.returncode}: {out.stderr[-400:]}")
        result = json.loads(out.stdout)
        plan = result.get("structured_output") or json.loads(result.get("result", "{}"))
        plan["latency_ms"] = int((time.time() - t0) * 1000)
        plan["cost_usd"] = result.get("total_cost_usd")
        usage = result.get("modelUsage", {})
        plan["model"] = ",".join(usage.keys()) or self.model
        plan["tokens"] = {m: [u.get("inputTokens", 0) + u.get("cacheReadInputTokens", 0) + u.get("cacheCreationInputTokens", 0), u.get("outputTokens", 0)] for m, u in usage.items()}
        return plan


class AnthropicApi:
    name = "anthropic-api"

    def __init__(self, api_key, model="claude-sonnet-5"):
        self.api_key, self.model = api_key, model

    def structured(self, system, prompt, schema):
        tool = {"name": "reply", "description": "Return the structured reply", "input_schema": schema}
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                          json={"model": self.model, "max_tokens": 4000, "system": system, "tools": [tool],
                                "tool_choice": {"type": "tool", "name": "reply"},
                                "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        r.raise_for_status()
        body = r.json()
        data = next(b["input"] for b in body["content"] if b["type"] == "tool_use")
        data["model"] = body.get("model", self.model)
        u = body.get("usage", {})
        data["tokens"] = {self.model: [u.get("input_tokens", 0), u.get("output_tokens", 0)]}
        return data

    def plan(self, situation, image_path=None):
        content = [{"type": "text", "text": "SITUATION (telemetry as words):\n" + json.dumps(situation, indent=1)}]
        if image_path and os.path.exists(image_path):
            data = base64.b64encode(open(image_path, "rb").read()).decode()
            content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
        tool = {"name": "set_plan", "description": "Commit the plan", "input_schema": PLAN_SCHEMA}
        t0 = time.time()
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                          json={"model": self.model, "max_tokens": 400, "system": SYSTEM_TWO_PROMPT, "tools": [tool],
                                "tool_choice": {"type": "tool", "name": "set_plan"},
                                "messages": [{"role": "user", "content": content}]}, timeout=120)
        r.raise_for_status()
        body = r.json()
        plan = next(b["input"] for b in body["content"] if b["type"] == "tool_use")
        plan.update(latency_ms=int((time.time() - t0) * 1000), model=body.get("model", self.model))
        return plan


class OpenAIChat:
    name = "openai-chat"

    def __init__(self, base_url, api_key="none", model="gpt-4o-mini"):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def structured(self, system, prompt, schema):
        r = requests.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"},
                          json={"model": self.model, "temperature": 0.2,
                                "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}},
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}, timeout=180)
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        data["model"] = self.model
        return data

    def plan(self, situation, image_path=None):
        content = [{"type": "text", "text": "SITUATION (telemetry as words):\n" + json.dumps(situation, indent=1)
                    + "\nReply with a JSON object with keys goal (one of REACH_EXIT, KILL_ENEMY, STOCK_AMMO, RESTORE_HEALTH, "
                      "ADD_ARMOR, UPGRADE_WEAPON, SCOUT, HOLD), steer_hint (none|ahead|left|right|behind), rationale, frame_note."}]
        if image_path and os.path.exists(image_path):
            data = base64.b64encode(open(image_path, "rb").read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
        t0 = time.time()
        r = requests.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"},
                          json={"model": self.model, "temperature": 0.2, "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": SYSTEM_TWO_PROMPT}, {"role": "user", "content": content}]},
                          timeout=120)
        r.raise_for_status()
        plan = json.loads(r.json()["choices"][0]["message"]["content"])
        plan.update(latency_ms=int((time.time() - t0) * 1000), model=self.model)
        return plan


# ---------------------------------------------------------------- factories
def make_system_one(kind, args):
    if kind == "typesafe":
        key = load_env_key("TYPESAFE_API_KEY", args.env_files)
        if not key:
            raise SystemExit("TYPESAFE_API_KEY not set (env or .env)")
        return TypeSafeSystemOne(key, args.system_one_model or "jev-latest")
    if kind == "openai":
        return OpenAISystemOne(args.openai_base_url, load_env_key("OPENAI_API_KEY", args.env_files) or "none",
                               args.system_one_model or "gpt-4o-mini")
    raise SystemExit(f"unknown System One provider {kind}")


def make_system_two(kind, args):
    if kind == "none":
        return None
    if kind == "claude-cli":
        return ClaudeCli(args.system_two_model or "sonnet")
    if kind == "anthropic":
        key = load_env_key("ANTHROPIC_API_KEY", args.env_files)
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY not set")
        return AnthropicApi(key, args.system_two_model or "claude-sonnet-5")
    if kind == "openai":
        return OpenAIChat(args.openai_base_url, load_env_key("OPENAI_API_KEY", args.env_files) or "none",
                          args.system_two_model or "gpt-4o-mini")
    raise SystemExit(f"unknown System Two provider {kind}")
