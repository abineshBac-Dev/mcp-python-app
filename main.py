from fastapi import FastAPI, Request
import mysql.connector
import os
import anthropic
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

# ✅ CORS (allow frontend from Vercel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict to your Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Claude setup
client = anthropic.Anthropic(
    api_key=os.getenv("CLAUDE_API_KEY")
)

# =========================
# DB CONNECTION
# =========================
def get_connection():
    try:
        url = os.getenv("MYSQL_PUBLIC_URL")
        parsed = urlparse(url)

        return mysql.connector.connect(
            host=parsed.hostname,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:],
            port=parsed.port
        )
    except Exception as e:
        print("DB Connection Error:", str(e))
        raise e

# =========================
# TOOL: GET USERS
# =========================
def get_users():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users")
        result = cursor.fetchall()

        cursor.close()
        conn.close()

        return result
    except Exception as e:
        print("DB Error:", str(e))
        return {"error": str(e)}

# =========================
# CHAT ENDPOINT (AI + TOOLS)
# =========================
@app.post("/chat")
async def chat(request: Request):
    try:
        body = await request.json()
        user_input = body.get("user_input", "")

        print("User Input:", user_input)

        # 🔥 Step 1: Ask Claude
        response = client.messages.create(
            model="claude-2.1",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""
User query: {user_input}

Available tools:
1. get_users - fetch all users from database

Return ONLY valid JSON:
{{ "tool": "get_users" }}
"""
            }]
        )

        # 🔥 Step 2: Extract text safely
        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text

        content = content.strip()

        print("Claude Raw Output:", content)

        # 🔥 Step 3: Parse JSON safely
        try:
            parsed = json.loads(content)
            tool = parsed.get("tool")
        except Exception:
            return {
                "error": "Invalid JSON from Claude",
                "claude_output": content
            }

        # 🔥 Step 4: Tool routing
        if tool == "get_users":
            data = get_users()
            return {
                "tool_used": "get_users",
                "data": data
            }

        return {
            "message": "No valid tool selected",
            "claude_output": content
        }

    except Exception as e:
        print("CHAT ERROR:", str(e))
        return {"error": str(e)}

# =========================
# HEALTH CHECK
# =========================
@app.get("/")
def home():
    return {"status": "running"}

@app.get("/health")
def health():
    return {"ok": True}
