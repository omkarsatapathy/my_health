"""Local SigV4-signing proxy: browser -> this -> AgentCore InvokeAgentRuntime.

Run:  uv run python proxy.py
Then point the UI at http://localhost:9090/api/v1/chat/stream
"""
import os
import uuid
from pathlib import Path

import boto3
import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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


@app.post("/api/v1/chat/stream")
async def stream(request: Request):
    payload = await request.body()
    session_id = request.headers.get("x-session-id") or f"sess-{uuid.uuid4().hex}-{uuid.uuid4().hex}"

    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        payload=payload,
        accept="text/event-stream",
        contentType="application/json",
    )
    raw = resp["response"]._raw_stream  # urllib3 HTTPResponse — true progressive read

    async def gen():
        import anyio
        def read_once():
            return raw.read(amt=64, decode_content=True)
        while True:
            chunk = await anyio.to_thread.run_sync(read_once)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "runtime": RUNTIME_ARN}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
