"""
OpenUI Serverless — FastAPI backend
Exposes the openui-lang generative-UI backend as a standalone HTTP API.
"""

import os
import json
import asyncio
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
import pandas as pd
import io
import sys
from contextlib import redirect_stdout

from prompt import OPENUI_SYSTEM_PROMPT, DATA_ONLY_PROMPT, DATA_ANALYST_PROMPT
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
app = FastAPI(title="OpenUI Serverless API", version="4.0.0")

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
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL, "active_sessions": len(store.list_sessions())}

@app.post("/upload")
async def upload_dataset(session_id: Optional[str] = Form(None), files: List[UploadFile] = File(...)):
    session, _ = store.get_or_create(session_id)
    print(f"[API] POST /upload | session: {session.id} | files: {len(files)}")
    
    try:
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        
        dfs = {}
        paths = []
        for file in files:
            contents = await file.read()
            file_path = os.path.join(upload_dir, file.filename)
            
            with open(file_path, "wb") as f:
                f.write(contents)
                
            dfs[file.filename] = file_path
            paths.append(f"`{file_path}`")
            
        schema_str = f"FILES UPLOADED. The raw files have been saved to the local disk at: {', '.join(paths)}. You must write a Python script using standard libraries (like pandas, PyPDF2, pdfplumber, or docx) to open, read, and extract the required metrics from these files."
        
        session.set_dataset(dfs, schema_str)
        
        return {"status": "success", "session_id": session.id, "schema_summary": {"type": "raw", "count": len(files)}}
            
    except Exception as e:
        print(f"[ERROR] Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

@app.post("/agentic_ai")
async def agentic_ai(request: GenerateRequest):
    """
    Mode 2: Data-Only Refresh
    Uses session cache for current data, returns updated data JSON.
    """
    session, _ = store.get_or_create(request.session_id)
    print(f"[API] POST /agentic_ai | session: {session.id}")
    
    if not session.has_cache():
        raise HTTPException(status_code=400, detail="No cached layout found for this session.")

    # TRUE DATA REFRESH (Zero-AI Pipeline)
    if session.dataset_df is not None and session.cached_script is not None and session.cached_schema is not None:
        print("[API] Evaluating True Data Refresh...")
        
        # Schema Verification Lock removed for pure Raw File execution
        print("[API] Running Cached Python Script against new raw file.")
        try:
            f = io.StringIO()
            first_sheet = list(session.dataset_df.keys())[0]
            local_vars = {"dfs": session.dataset_df, "df": session.dataset_df[first_sheet], "pd": pd, "json": __import__("json")}
            with redirect_stdout(f):
                exec(session.cached_script, local_vars)
                
            output = f.getvalue().strip()
            
            # Find the JSON block in case there are debug prints
            start = output.find('{')
            end = output.rfind('}')
            if start != -1 and end != -1:
                json_str = output[start:end+1]
                debug_logs = output[:start].strip()
                if debug_logs:
                    print(f"[AI SCRIPT LOGS]\n{debug_logs}")
                new_data = json.loads(json_str)
            else:
                new_data = json.loads(output)
                
            session.update_data(new_data)
            
            return JSONResponse(
                content={
                    "backend_Printed_layout_code": session.cached_layout,
                    "data_variables": session.cached_data,
                    "python_script": session.cached_script
                },
                headers={"Cache-Control": "no-cache", "X-Session-Id": session.id}
            )
        except Exception as e:
            print(f"[ERROR] True Data Refresh failed: {str(e)}")
            # By throwing a 400 with 'Schema mismatch detected', the frontend App.tsx will catch it 
            # and automatically fallback to a Full AI Generation for the new data structure!
            raise HTTPException(status_code=400, detail=f"Schema mismatch detected: The cached Python script crashed on the new data ({str(e)}).")

    # FALLBACK: LLM HALLUCINATION REFRESH
    try:
        inputs = [
            {"role": "user", "content": f"CURRENT DASHBOARD DATA:\n{json.dumps(session.cached_data)}\n\nUSER REQUEST:\n{request.message}\n\nCRITICAL INSTRUCTION: Return a JSON object containing EXACTLY ONE key: 'data_variables'. You are STRICTLY FORBIDDEN from generating a 'layout_code' key. If you output 'layout_code', the system will crash."}
        ]
        
        response = await client.responses.create(
            model=MODEL,
            instructions=DATA_ONLY_PROMPT,
            input=inputs,
            temperature=0
        )
        
        content = getattr(response, "output_text", None) or getattr(response, "text", None) or getattr(response, "content", "")
        if not content and hasattr(response, "choices"):
            content = response.choices[0].message.content or ""
        content = content.replace("```json", "").replace("```", "").strip()
        parsed_response = json.loads(content)
        
        # Update session data
        new_data = parsed_response.get("data_variables", {})
        session.update_data(new_data)
            
        return JSONResponse(
            content={
                "backend_Printed_layout_code": session.cached_layout,
                "data_variables": session.cached_data
            },
            headers={"Cache-Control": "no-cache", "X-Session-Id": session.id}
        )
        
    except Exception as e:
        print(f"[ERROR] Refresh failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generative_ui")
async def generative_ui(request: GenerateRequest):
    """
    Mode 1: Generates UI + Data.
    Stores layout_code and data_variables JSON in session.
    """
    session, _ = store.get_or_create(request.session_id)
    print(f"[API] POST /generative_ui | session: {session.id}")

    try:
        inputs = session.messages + [{"role": "user", "content": request.message}]
        
        response = await client.responses.create(
            model=MODEL,
            instructions=OPENUI_SYSTEM_PROMPT,
            input=inputs
        )
        
        content = getattr(response, "output_text", None) or getattr(response, "text", None) or getattr(response, "content", "")
        if not content and hasattr(response, "choices"):
            content = response.choices[0].message.content or ""
        content = content.replace("```json", "").replace("```", "").strip()
        parsed_response = json.loads(content)
        
        layout = parsed_response.get("layout_code", "")
        data_vars = parsed_response.get("data_variables", {})
        
        session.cache_dashboard(layout, data_vars, request.message)
        session.append("user", request.message)
        session.append("assistant", json.dumps(parsed_response))
        
        return JSONResponse(
            content=parsed_response,
            headers={"Cache-Control": "no-cache", "X-Session-Id": session.id}
        )
        
    except Exception as e:
        print(f"[ERROR] Full generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate_from_data")
async def generate_from_data(request: GenerateRequest):
    """
    Mode 3: Data Analyst
    Uses uploaded dataset to generate a dashboard via Custom Function Calling Loop.
    """
    session, _ = store.get_or_create(request.session_id)
    print(f"[API] POST /generate_from_data | session: {session.id}")
    
    if session.dataset_df is None:
        raise HTTPException(status_code=400, detail="No active dataset found for this session.")

    try:
        schema_str = session.dataset_schema
        
        system_prompt = DATA_ANALYST_PROMPT + (
            "\n\nYou have access to the `code_interpreter` tool. Use it to explore the dataset "
            "(a dictionary of file paths called `dfs`) and perfect your logic. "
            "Once you are done, you MUST return a single JSON object containing 'layout_code', "
            "'data_variables', and 'python_script'. The 'python_script' MUST be a standalone "
            "Python script that, when executed against `dfs`, prints exactly the `data_variables` JSON to stdout. "
            "CRITICAL: Do NOT hardcode specific filenames (like 'test1.xlsx') in your final python_script! "
            "The user will upload files with different names during data refreshes. "
            "You MUST iterate through `dfs.values()` dynamically (or check extensions) so the script works generically on any new files. "
            "Do NOT wrap your final output in markdown, just output raw JSON."
        )
        
        messages = [{"role": "system", "content": system_prompt}] + session.messages + [
            {"role": "user", "content": f"Attached is a dataset containing a dictionary of DataFrames called `dfs` with the following schema:\n{schema_str}\n\nUSER REQUEST: {request.message}"}
        ]
        
        code_interpreter_tool = {
            "type": "function",
            "function": {
                "name": "code_interpreter",
                "description": (
                    "Execute Python code in a safe sandbox to perform calculations, data analysis, "
                    "or process datasets. You have access to a dictionary of Pandas DataFrames named `dfs`. "
                    "Use this tool to inspect, filter, or aggregate the datasets. "
                    "You MUST print the final result or summary to stdout using print(), which will be returned to you."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The complete Python 3 code to execute.",
                        }
                    },
                    "required": ["code"],
                },
            },
        }
        
        for attempt in range(10):
            print(f"[API] Agentic Loop (Iteration {attempt+1}/10)")
            response = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=[code_interpreter_tool],
                temperature=0.2,
            )
            
            message = response.choices[0].message
            assistant_msg = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                assistant_msg["tool_calls"] = []
                for tc in message.tool_calls:
                    assistant_msg["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })
            messages.append(assistant_msg)
            
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "code_interpreter":
                        try:
                            args = json.loads(tool_call.function.arguments)
                            python_code = args.get("code", "")
                            print(f"[DEBUG] Executing Agent's Python Code:\n{python_code}")
                            
                            f = io.StringIO()
                            first_sheet = list(session.dataset_df.keys())[0]
                            local_vars = {"dfs": session.dataset_df, "df": session.dataset_df[first_sheet], "pd": pd, "json": __import__("json")}
                            
                            with redirect_stdout(f):
                                exec(python_code, local_vars)
                            output = f.getvalue().strip()
                            if not output:
                                output = "Code executed successfully but returned no stdout. Did you forget to print() the results?"
                        except Exception as e:
                            output = f"Error: {str(e)}"
                            
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": "code_interpreter",
                            "content": output
                        })
                continue
            else:
                # No tool calls, parse JSON
                output_text = message.content or ""
                try:
                    clean_text = output_text.replace("```json", "").replace("```", "").strip()
                    start = clean_text.find('{')
                    end = clean_text.rfind('}')
                    if start != -1 and end != -1:
                        clean_text = clean_text[start:end+1]
                    parsed_response = json.loads(clean_text)
                    
                    python_script = parsed_response.get("python_script", "")
                    layout_code = parsed_response.get("layout_code", "")
                    data_vars = parsed_response.get("data_variables", {})
                    
                    if not layout_code or not data_vars or not python_script:
                        raise ValueError("Missing 'layout_code', 'data_variables', or 'python_script'")
                    
                    session.cache_dashboard(layout_code, data_vars, request.message, script=python_script, schema=session.dataset_schema)
                    session.append("user", request.message)
                    session.append("assistant", json.dumps({"layout_code": layout_code, "data_variables": data_vars}))
                    
                    return JSONResponse(
                        content={"layout_code": layout_code, "data_variables": data_vars, "python_script": python_script},
                        headers={"Cache-Control": "no-cache", "X-Session-Id": session.id}
                    )
                except Exception as e:
                    error_msg = f"Failed to parse your final JSON: {str(e)}. Ensure you output ONLY valid JSON containing 'layout_code', 'data_variables', and 'python_script'."
                    print(f"[RETRY] {error_msg}")
                    messages.append({"role": "user", "content": error_msg})
                    continue
        
        raise HTTPException(status_code=500, detail="Agentic loop exceeded maximum iterations without a valid JSON response.")
        
    except Exception as e:
        print(f"[ERROR] Data Analyst failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions")
async def list_sessions():
    sessions = []
    for s_summary in store.list_sessions():
        s = store.get(s_summary["session_id"])
        if not s: continue
        first_user_msg = next((m["content"] for m in s.messages if m["role"] == "user"), None)
        label = (first_user_msg[:50] + "…") if first_user_msg and len(first_user_msg) > 50 else first_user_msg
        sessions.append({
            "session_id": s.id,
            "label": label or "New Chat",
            "message_count": len(s.messages),
            "has_cache": s.has_cache(),
            "last_active": s.last_active,
        })
    sessions.sort(key=lambda x: x["last_active"], reverse=True)
    return sessions

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    s = store.get(session_id)
    if not s: raise HTTPException(status_code=404)
    return s.to_dict()

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    store.delete(session_id)
    return {"status": "deleted"}

@app.get("/sessions/{session_id}/cache")
async def get_cache_info(session_id: str):
    s = store.get(session_id)
    if not s: raise HTTPException(status_code=404)
    return {
        "has_cache": s.has_cache(),
        "cache_version": s.cache_version,
        "cached_query": s.cached_query,
    }

