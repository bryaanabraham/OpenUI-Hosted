"""
OpenUI Serverless — FastAPI backend
Exposes the openui-lang generative-UI backend as a standalone HTTP API.
"""

import asyncio
import json
import os
import time
from typing import AsyncGenerator, Optional, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from prompt import OPENUI_SYSTEM_PROMPT
from sessions import store

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set. Check your .env file.")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="OpenUI Serverless API", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],
)

@app.on_event("startup")
async def start_reaper():
    async def _reaper():
        while True:
            await asyncio.sleep(600)
            removed = store.reap_expired()
            if removed:
                print(f"[session-reaper] Removed {removed} expired session(s).")
    asyncio.create_task(_reaper())

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_messages(session_messages: list[dict], user_message: str) -> list[dict]:
    return [
        {"role": "system", "content": OPENUI_SYSTEM_PROMPT},
        *session_messages,
        {"role": "user", "content": user_message},
    ]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL, "active_sessions": len(store.list_sessions())}

@app.post("/generate/stream/compat")
async def generate_stream_compat(request: GenerateRequest):
    """
    OpenAI-compatible NDJSON streaming.
    
    The @openuidev/react-headless 'openAIReadableStreamAdapter' expects 
    raw JSON objects delimited by newlines (NDJSON), NOT SSE 'data: ' prefixes.
    """
    print(f"[API] POST /generate/stream/compat | session: {request.session_id}")
    session, _ = store.get_or_create(request.session_id)
    
    async def ndjson_generator():
        try:
            messages = _build_messages(session.messages, request.message)
            stream = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                stream=True,
            )
            
            created = int(time.time())
            full_content = []
            
            async for chunk in stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta.content
                if delta:
                    full_content.append(delta)
                    payload = {
                        "id": f"chatcmpl-{session.id[:8]}",
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": MODEL,
                        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
                    }
                    # Send raw JSON + newline (NDJSON format)
                    yield json.dumps(payload) + "\n"
            
            # Finalize session
            session.append("user", request.message)
            session.append("assistant", "".join(full_content))
            
            # Final stop chunk in NDJSON
            stop_payload = {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            yield json.dumps(stop_payload) + "\n"
            
        except Exception as e:
            print(f"[ERROR] Streaming: {str(e)}")
            yield json.dumps({"error": str(e)}) + "\n"

    return StreamingResponse(
        ndjson_generator(),
        media_type="application/x-ndjson", # Correct type for NDJSON
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session.id,
        },
    )

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    s = store.get(session_id)
    if not s: raise HTTPException(status_code=404)
    return s.to_dict()

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    store.delete(session_id)
    return {"status": "deleted"}
