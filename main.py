from fastapi import FastAPI
import mysql.connector
import os
import anthropic

app = FastAPI()

# DB connection (Railway env variables)
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=int(os.getenv("MYSQLPORT"))
    )

# Tool: get users
@app.get("/tool/get_users")
def get_users():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users")
    return cursor.fetchall()

# Claude setup
client = anthropic.Anthropic(
    api_key=os.getenv("CLAUDE_API_KEY")
)

@app.post("/chat")
async def chat(user_input: str):
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"""
            User query: {user_input}
            Available tools:
            - get_users()

            Decide tool in JSON:
            """
        }]
    )

    return {"response": str(response)}
