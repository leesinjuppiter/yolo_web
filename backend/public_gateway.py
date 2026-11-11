"""Authenticated, temporary public test entry for the loopback workbench."""

import base64
import binascii
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = Path(os.environ["WORKBENCH_PUBLIC_CREDENTIALS"])
    credentials = json.loads(path.read_text(encoding="utf-8"))
    app.state.login = f"{credentials['username']}:{credentials['password']}".encode()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5186",
                                timeout=httpx.Timeout(300, connect=10), trust_env=False) as client:
        app.state.upstream = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def authorized(request: Request) -> bool:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        supplied = base64.b64decode(token, validate=True)
    except (ValueError, binascii.Error):
        return False
    return hmac.compare_digest(supplied, request.app.state.login)


@app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def forward(request: Request, path: str):
    if not authorized(request):
        return Response("Authentication required", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="Vision Workbench", charset="UTF-8"',
                                 "Cache-Control": "no-store"})
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("sec-fetch-site") == "cross-site":
        return Response("Cross-site changes are not allowed", status_code=403)
    connection_headers = {item.strip().lower() for item in request.headers.get("connection", "").split(",")}
    excluded = HOP_HEADERS | connection_headers | {"host", "authorization", "content-length"}
    headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded}
    url = request.app.state.upstream.base_url.copy_with(
        raw_path=request.scope["raw_path"] + (b"?" + request.scope["query_string"] if request.scope["query_string"] else b""))
    outgoing = request.app.state.upstream.build_request(request.method, url, headers=headers,
                                                       content=request.stream())
    try:
        upstream = await request.app.state.upstream.send(outgoing, stream=True)
    except httpx.HTTPError:
        return Response("Workbench upstream unavailable", status_code=502)
    excluded_response = HOP_HEADERS | {item.strip().lower() for item in upstream.headers.get("connection", "").split(",")}
    response_headers = {key: value for key, value in upstream.headers.items() if key.lower() not in excluded_response}
    response_headers["Cache-Control"] = "no-store"
    response_headers["X-Content-Type-Options"] = "nosniff"
    return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                             headers=response_headers, background=BackgroundTask(upstream.aclose))
