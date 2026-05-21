"""AgentCore SigV4 proxy — Lambda Function URL handler (zip deploy).

Lambda IAM role signs all requests; no AWS_PROFILE needed.
Env vars required: AGENTCORE_RUNTIME_ARN
"""
import json
import os
import uuid

import boto3

RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
REGION = os.environ.get("AWS_REGION", "ap-south-1")

_client = None

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type,x-session-id",
    "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
}


def get_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _client


def handler(event, context):
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "POST")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    if method == "GET":
        return {
            "statusCode": 200,
            "headers": {**CORS, "Content-Type": "application/json"},
            "body": json.dumps({"status": "ok", "runtime": RUNTIME_ARN}),
        }

    try:
        body = json.loads(event.get("body") or "{}")
        h = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        session_id = h.get("x-session-id") or f"sess-{uuid.uuid4().hex}-{uuid.uuid4().hex}"

        resp = get_client().invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            qualifier="DEFAULT",
            runtimeSessionId=session_id,
            payload=json.dumps(body).encode(),
            accept="text/event-stream",
            contentType="application/json",
        )
        raw = resp["response"]._raw_stream

        chunks = []
        while True:
            chunk = raw.read(amt=4096, decode_content=True)
            if not chunk:
                break
            chunks.append(chunk)

        return {
            "statusCode": 200,
            "headers": {
                **CORS,
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
            },
            "body": b"".join(chunks).decode("utf-8", errors="replace"),
        }

    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": {**CORS, "Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }
