# OpenUI Serverless API

A standalone Python **FastAPI** server that exposes the [openui-lang](https://github.com/openuidev) generative-UI backend as a plain HTTP API.

Send a natural-language description → get back the raw `openui-lang` component text that the React frontend renders.

---

## Folder Structure

```
openui-serverless/
├── main.py          # FastAPI application (endpoints)
├── prompt.py        # Baked-in openui-lang system prompt
├── sessions.py      # Session management logic
├── requirements.txt
├── .env.example     # Copy to .env and fill in your key
├── start.bat        # Launches both Backend and Frontend
├── run.bat          # Launches Backend only
├── README.md
└── frontend/        # Vite React test application
    ├── src/
    ├── package.json
    └── vite.config.ts
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Node.js (for the test frontend)
- An OpenAI API key

### 2. Install dependencies

**Backend:**
```bash
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
```

### 3. Configure environment

```bash
copy .env.example .env
# then edit .env and set OPENAI_API_KEY
```

### 4. Run everything

The easiest way to start both the backend and the test frontend is:

```bash
start.bat
```

This will open two terminal windows:
- **Backend:** `http://localhost:8000`
- **Frontend:** `http://localhost:3001`

---

## Test Frontend

The `frontend/` folder contains a Vite React application designed to test the API endpoints.

### Key Features
- **Real-time Streaming:** Uses the `/generate/stream/compat` endpoint for token-by-token rendering.
- **Session Support:** Automatically tracks and passes the `X-Session-Id` back to the server to maintain conversation context.
- **New Chat:** A button to reset the session and start a fresh UI generation.
- **Built-in Proxy:** Vite is configured to proxy `/api` calls to the Python backend to avoid CORS issues during development.

The server starts at **`http://localhost:8000`**.  
Interactive Swagger docs: **`http://localhost:8000/docs`**

---

## API Reference

### `GET /health`

Liveness check.

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok", "model": "gpt-5.4" }
```

---

### `POST /generate` — Full response

Returns the complete openui-lang component once generation finishes.

**Request body:**

| Field     | Type            | Required | Description                                       |
|-----------|-----------------|----------|---------------------------------------------------|
| `message` | `string`        | ✅       | Natural-language UI description                  |
| `history` | `array \| null` | ❌       | Prior conversation turns (OpenAI message format) |

**Example:**

```bash
curl -X POST http://localhost:8000/generate \
     -H "Content-Type: application/json" \
     -d '{"message": "Create a login form with email and password"}'
```

**Response:**

```json
{
  "component": "root = Stack([title, form])\ntitle = TextContent(\"Login\", \"large-heavy\")\n...",
  "model": "gpt-5.4",
  "usage": {
    "prompt_tokens": 1253,
    "completion_tokens": 148,
    "total_tokens": 1401
  }
}
```

The `component` field is the raw openui-lang text — pass it directly to the `@openuidev/react-ui` renderer.

---

### `POST /generate/stream` — SSE streaming

Streams the component token-by-token via **Server-Sent Events**, mirroring the original Next.js frontend behaviour.

Each event: `data: {"chunk": "<text>"}\n\n`  
Final event: `data: [DONE]\n\n`

**Example:**

```bash
curl -X POST http://localhost:8000/generate/stream \
     -H "Content-Type: application/json" \
     -d '{"message": "Show a bar chart of monthly revenue for 2024"}' \
     --no-buffer
```

---

## Multi-turn Conversations

Pass prior turns in `history` to maintain context:

```json
{
  "message": "Now add a pie chart below the table",
  "history": [
    { "role": "user",      "content": "Show me a table of top 5 programming languages" },
    { "role": "assistant", "content": "root = Stack([title, tbl])\n..." }
  ]
}
```

---

## Environment Variables

| Variable        | Default  | Description              |
|-----------------|----------|--------------------------|
| `OPENAI_API_KEY` | —       | **Required**. OpenAI key |
| `OPENAI_MODEL`   | `gpt-5.4` | Model to use            |

---

## Connecting to the Next.js Frontend

To point the existing Next.js app at this server instead of its own `/api/chat` route, update `processMessage` in `page.tsx`:

```ts
processMessage={async ({ messages, abortController }) =>
  fetch("http://localhost:8000/generate/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: messages.at(-1)?.content }),
    signal: abortController.signal,
  })
}
```

> **Note:** the streaming format differs slightly from the OpenAI SDK stream — you may need to adjust the `streamProtocol` adapter on the frontend side.
