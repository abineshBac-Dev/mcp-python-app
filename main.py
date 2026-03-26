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

@app.get("/init-db")
def init_db():
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
            CREATE TABLE `BOOKING_DETAILS` (
              `BookingDetailsKey` bigint(20) NOT NULL AUTO_INCREMENT,
              `Tracking_Number` varchar(50) NOT NULL,
              `Billing_Mode` varchar(50) DEFAULT NULL,
              `Number_of_Pieces` int(11) DEFAULT NULL,
              `Booked_By_Cust_Type` varchar(25) DEFAULT NULL,
              `Booked_By_Cust_Code` varchar(25) DEFAULT NULL,
              `Booked_By_Cust_Name` varchar(100) DEFAULT NULL,
              `Package_Type` varchar(25) DEFAULT NULL,
              `Validation` varchar(50) DEFAULT NULL,
              `Source_Application` varchar(70) DEFAULT NULL,
              `Eway_Bill` varchar(25) DEFAULT NULL,
              `Eway_Bill_Amount` double(10,2) DEFAULT NULL,
              `Shipment_Type` varchar(30) DEFAULT NULL,
              `Commodity_Details` varchar(250) DEFAULT NULL,
              `Inco_Term` varchar(50) DEFAULT NULL,
              `Shipment_Term` varchar(50) DEFAULT NULL,
              `Shipment_Term_SPL` varchar(10) DEFAULT NULL,
              `Security_Pouch_No` varchar(50) DEFAULT NULL,
              `Length` double(10,4) DEFAULT NULL,
              `Breadth` double(10,4) DEFAULT NULL,
              `Height` double(10,4) DEFAULT NULL,
              `Booking_Weight` double(10,4) DEFAULT NULL,
              `Dead_Weight` double(10,4) DEFAULT NULL,
              `Volumetric_Weight` double(10,4) DEFAULT NULL,
              `Chargeable_Weight` double(10,4) DEFAULT NULL,
              `Weight_Unit` varchar(10) DEFAULT NULL,
              `Connection_Service_Code` varchar(10) DEFAULT NULL,
              `Connection_Service_Name` varchar(50) DEFAULT NULL,
              `Connection_Vendor_Name` varchar(50) DEFAULT NULL,
              `Book_Service_Vendor_Name` varchar(50) DEFAULT NULL,
              `Vendor_Ref_No` varchar(50) DEFAULT NULL,
              `Expected_Agent` varchar(50) DEFAULT NULL,
              `In_Favour` varchar(50) DEFAULT NULL,
              `Product` varchar(50) DEFAULT NULL,
              `Gor_Vol_Weight` decimal(8,3) DEFAULT NULL,
              `Wdm_Status` varchar(5) DEFAULT NULL,
              `FRDP_Code` varchar(20) DEFAULT NULL,
              `Desc_Goods` varchar(255) DEFAULT NULL,
              `Content_Desc` varchar(250) DEFAULT NULL,
              `Booked_By_Sub_Account_Code` varchar(30) DEFAULT NULL,
              `Booked_By_Child_Code` varchar(20) DEFAULT NULL,
              `CreateTs` timestamp NOT NULL DEFAULT current_timestamp(),
              `CreatedBy` varchar(50) DEFAULT NULL,
              `ModifyTs` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
              `ModifiedBy` varchar(50) DEFAULT NULL,
              PRIMARY KEY (`BookingDetailsKey`),
              KEY `idx_trx_nm` (`Tracking_Number`),
              KEY `idx_CreateTs` (`CreateTs`)
            )
            """)
        conn.commit()
        conn.close()

        return {"status": "Table created successfully"}

    except Exception as e:
        return {"error": str(e)}
