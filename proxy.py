"""Local SigV4-signing proxy: browser -> this -> AgentCore InvokeAgentRuntime.

Run:  uv run python proxy.py
Then point the UI at http://localhost:9090/api/v1/chat/stream
"""
import os
import uuid
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import DEFAULT_USER_ID, settings
from app.core.chat_store import delete_session, get_session, get_session_detail, list_sessions, rename_session

ROOT = Path(__file__).parent
CFG = yaml.safe_load((ROOT / ".bedrock_agentcore.yaml").read_text())
AGENT_NAME = CFG["default_agent"]
AGENT = CFG["agents"][AGENT_NAME]
RUNTIME_ARN = AGENT["bedrock_agentcore"]["agent_arn"]
REGION = AGENT["aws"]["region"]
PROFILE = os.environ.get("AWS_PROFILE", "personal-dev")

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
client = session.client("bedrock-agentcore")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RenameSessionPayload(BaseModel):
    title: str


@app.post("/api/v1/chat/stream")
async def stream(request: Request):
    payload = await request.body()
    session_id = request.headers.get("x-session-id") or f"sess-{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    print(f"[proxy] -> AgentCore session={session_id[:24]}… bytes={len(payload)}", flush=True)

    try:
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            qualifier="DEFAULT",
            runtimeSessionId=session_id,
            payload=payload,
            accept="text/event-stream",
            contentType="application/json",
        )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        code = err.get("Code", type(exc).__name__)
        message = err.get("Message", str(exc))
        print(f"[proxy] !! invoke_agent_runtime failed: {code}: {message}", flush=True)
        return JSONResponse(
            status_code=502,
            content={"error": code, "message": message, "hint": "Check CloudWatch /aws/bedrock-agentcore/runtimes/* for the agent-side traceback."},
        )
    except Exception as exc:
        print(f"[proxy] !! invoke_agent_runtime failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse(status_code=500, content={"error": type(exc).__name__, "message": str(exc)})

    raw = resp["response"]._raw_stream  # urllib3 HTTPResponse — true progressive read

    async def gen():
        import anyio
        def read_once():
            return raw.read(amt=64, decode_content=True)
        total = 0
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(read_once)
                if not chunk:
                    break
                total += len(chunk)
                yield chunk
        finally:
            print(f"[proxy] <- stream done session={session_id[:24]}… bytes_out={total}", flush=True)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/sessions")
def sessions(user_id: str = DEFAULT_USER_ID, limit: int = settings.session_list_page_size, cursor: str | None = None):
    items, next_cursor = list_sessions(user_id, limit=limit, cursor=cursor)
    return {"sessions": [item.model_dump() for item in items], "next_cursor": next_cursor}


@app.get("/api/v1/sessions/{session_id}/messages")
def session_messages(session_id: str, user_id: str = DEFAULT_USER_ID):
    detail = get_session_detail(user_id, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@app.patch("/api/v1/sessions/{session_id}")
def update_session(session_id: str, payload: RenameSessionPayload, user_id: str = DEFAULT_USER_ID):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    summary = rename_session(user_id, session_id, title)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return summary


@app.delete("/api/v1/sessions/{session_id}", status_code=204)
def remove_session(session_id: str, user_id: str = DEFAULT_USER_ID):
    if not get_session(user_id, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    delete_session(user_id, session_id)
    return None


@app.get("/health")
def health():
    return {"status": "ok", "runtime": RUNTIME_ARN}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
