"""AgentCore streaming proxy for Lambda (Lambda Web Adapter).

No AWS_PROFILE — Lambda IAM role provides credentials via instance metadata.
Set env var AGENTCORE_RUNTIME_ARN before invoking.
"""
import os
import uuid

import anyio
import boto3
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
REGION = os.environ.get("AWS_REGION", "ap-south-1")

_client = None


def get_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _client


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["content-type", "x-session-id"],
)


@app.post("/stream")
async def stream(request: Request):
    payload = await request.body()
    session_id = request.headers.get("x-session-id") or f"sess-{uuid.uuid4().hex}-{uuid.uuid4().hex}"

    resp = get_client().invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        payload=payload,
        accept="text/event-stream",
        contentType="application/json",
    )
    raw = resp["response"]._raw_stream

    async def gen():
        while True:
            chunk = await anyio.to_thread.run_sync(
                lambda: raw.read(amt=64, decode_content=True)
            )
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
