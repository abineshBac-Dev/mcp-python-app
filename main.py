from fastapi import FastAPI
import mysql.connector
import os
import anthropic
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_input = body.get("user_input", "")

    # Step 1: Ask Claude which tool to use
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"""
User query: {user_input}

Available tools:
1. get_users - fetch all users from database

Reply ONLY in JSON:
{{ "tool": "tool_name" }}
"""
        }]
    )

    # Step 2: Extract Claude response
    try:
        content = response.content[0].text.strip()

        if "get_users" in content:
            return get_users()

        return {"message": "No tool matched", "claude": content}

    except Exception as e:
        return {"error": str(e)}

@app.get("/")
def home():
    return {"status": "running"}

# DB connection (Railway env variables)
def get_connection():
    url = os.getenv("MYSQL_PUBLIC_URL")

    parsed = urlparse(url)

    return mysql.connector.connect(
        host=parsed.hostname,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],  # remove '/'
        port=parsed.port
    )

# Tool: get users
@app.get("/tool/get_users")
def get_users():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users")
        return cursor.fetchall()
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
def health():
    return {"ok": True}

# Claude setup
client = anthropic.Anthropic(
    api_key=os.getenv("CLAUDE_API_KEY")
)
