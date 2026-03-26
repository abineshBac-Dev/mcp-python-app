from fastapi import FastAPI, Request
import mysql.connector
import os
import anthropic
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware
import json
import re

app = FastAPI()

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict to your Vercel domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CLAUDE SETUP
# =========================
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
        print("❌ DB Connection Error:", str(e))
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
        print("❌ DB Error:", str(e))
        return {"error": str(e)}

# =========================
# HELPER: Extract Claude text
# =========================
def extract_text(response):
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
    return text.strip()

# =========================
# CHAT ENDPOINT
# =========================
@app.post("/chat")
async def chat(request: Request):
    try:
        body = await request.json()
        user_input = body.get("user_input", "")

        print("🟢 User Input:", user_input)

        # =========================
        # STEP 1: Claude decides
        # =========================
        decision_prompt = f"""
User query: {user_input}

Available tools:

get_users:
- Use when user asks:
  - "show users"
  - "list users"
  - "how many users"
  - "user data"
- Returns list of users with id, name, email

Rules:
- If tool is needed → return:
  {{ "tool": "get_users" }}
- If NO tool needed → return:
  {{ "answer": "your natural response" }}

Return ONLY valid JSON.
"""

        decision_response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": decision_prompt}]
        )

        content = extract_text(decision_response)

        print("🟡 Claude Raw:", content)

        # Clean markdown if any
        content = re.sub(r"```json", "", content)
        content = re.sub(r"```", "", content).strip()

        print("🟣 Cleaned:", content)

        # =========================
        # STEP 2: Parse JSON
        # =========================
        try:
            parsed = json.loads(content)
        except Exception as e:
            print("❌ JSON Parse Error:", str(e))
            return {
                "error": "Invalid JSON from Claude",
                "claude_output": content
            }

        tool = parsed.get("tool")
        answer = parsed.get("answer")

        # =========================
        # STEP 3: TOOL FLOW
        # =========================
        if tool == "get_users":
            data = get_users()

            final_prompt = f"""
User question: {user_input}

Tool used: get_users
Tool result:
{data}

Instructions:
- If user asked "how many", return count
- If user asked "list/show", summarize users
- Keep response short and natural
"""

            final_response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=200,
                messages=[{"role": "user", "content": final_prompt}]
            )

            final_text = extract_text(final_response)

            return {
                "tool_used": "get_users",
                "raw_data": data,
                "answer": final_text
            }

        # =========================
        # STEP 4: DIRECT NLP FLOW
        # =========================
        if answer:
            return {
                "tool_used": None,
                "answer": answer
            }

        # =========================
        # STEP 5: FALLBACK
        # =========================
        return {
            "message": "No valid response",
            "claude_output": content
        }

    except Exception as e:
        print("❌ CHAT ERROR:", str(e))
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
