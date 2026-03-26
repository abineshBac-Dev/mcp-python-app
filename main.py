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
            CREATE TABLE `CONSIGNMENT` (
              `ConsignmentKey` bigint(20) NOT NULL AUTO_INCREMENT,
              `Tracking_Number` varchar(50) NOT NULL,
              `CN_Type` varchar(25) DEFAULT NULL,
              `Reference_No` varchar(100) DEFAULT NULL,
              `Customer_Code` varchar(25) DEFAULT NULL,
              `Customer_Name` varchar(100) DEFAULT NULL,
              `Sender_Name` varchar(100) DEFAULT NULL,
              `Origin_City` varchar(50) DEFAULT NULL,
              `Origin_Pincode` varchar(20) DEFAULT NULL,
              `Origin_Branch_Code` varchar(20) DEFAULT NULL,
              `Origin_Branch_Name` varchar(100) DEFAULT NULL,
              `Origin_Zone` varchar(100) DEFAULT NULL,
              `Origin_Ro` varchar(100) DEFAULT NULL,
              `Destination_City` varchar(50) DEFAULT NULL,
              `Destination_Pincode` varchar(20) DEFAULT NULL,
              `Destination_Branch_Code` varchar(20) DEFAULT NULL,
              `Destination_Branch_Name` varchar(50) DEFAULT NULL,
              `Destination_Zone` varchar(100) DEFAULT NULL,
              `Destination_Ro` varchar(100) DEFAULT NULL,
              `BookingTs` datetime DEFAULT NULL,
              `BookingType` varchar(20) DEFAULT NULL,
              `Service_Code` varchar(20) DEFAULT NULL,
              `Service_Name` varchar(50) DEFAULT NULL,
              `Service_Product_Name` varchar(25) DEFAULT NULL,
              `Packet_Manifest_Number` varchar(25) DEFAULT NULL,
              `Bag_Manifest_Number` varchar(20) DEFAULT NULL,
              `Dispatch_Number` int(11) DEFAULT NULL,
              `Mode` varchar(20) DEFAULT NULL,
              `Ops_EDD` datetime DEFAULT NULL,
              `Ops_REDD` datetime DEFAULT NULL,
              `Cust_Prom_EDD` datetime DEFAULT NULL,
              `Cust_Prom_REDD` datetime DEFAULT NULL,
              `Ops_EDD_Parameters` varchar(20) DEFAULT NULL,
              `Cust_EDD_Parameters` varchar(20) DEFAULT NULL,
              `Current_Status_Code` varchar(20) DEFAULT NULL,
              `Current_StatusTs` datetime DEFAULT NULL,
              `Current_Hub_Code` varchar(15) DEFAULT NULL,
              `Current_Hub_Name` varchar(100) DEFAULT NULL,
              `Current_Location` varchar(100) DEFAULT NULL,
              `Current_Location_Code` varchar(20) DEFAULT NULL,
              `Receiver_Name` varchar(70) DEFAULT NULL,
              `ReceiverTs` datetime DEFAULT NULL,
              `Receiver_Location` varchar(70) DEFAULT NULL,
              `Relationship` varchar(70) DEFAULT NULL,
              `Delivered_By_Hub_Type` varchar(15) DEFAULT NULL,
              `Delivered_By_Hub_Code` varchar(15) DEFAULT NULL,
              `Delivered_By_Hub_Name` varchar(70) DEFAULT NULL,
              `Delivered_By_Biker_Code` varchar(15) DEFAULT NULL,
              `Delivered_By_Biker_Name` varchar(70) DEFAULT NULL,
              `Delivered_By_Mobile` varchar(25) DEFAULT NULL,
              `Delivered_By_MailId` varchar(70) DEFAULT NULL,
              `DeliveredTs` datetime DEFAULT NULL,
              `RTO_Tracking_Number` varchar(15) DEFAULT NULL,
              `Parent_Tracking_Number` varchar(15) DEFAULT NULL,
              `Movement_Type` varchar(15) DEFAULT NULL,
              `Return_Type` varchar(15) DEFAULT NULL,
              `Reason_Code` varchar(25) DEFAULT NULL,
              `Reason_Description` varchar(250) DEFAULT NULL,
              `Feedback_Rating` varchar(10) DEFAULT NULL,
              `CTBS_Entry_Time` datetime DEFAULT NULL,
              `CreateTs` timestamp NOT NULL DEFAULT current_timestamp(),
              `CreatedBy` varchar(50) DEFAULT NULL,
              `ModifyTs` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
              `ModifiedBy` varchar(50) DEFAULT NULL,
              PRIMARY KEY (`ConsignmentKey`),
              UNIQUE KEY `Tracking_Number` (`Tracking_Number`),
              KEY `idx_CreateTs` (`CreateTs`),
              KEY `idx_ModifyTs` (`ModifyTs`),
              KEY `idx_current_status_code` (`Current_Status_Code`),
              KEY `idx_Destination_Branch_Code` (`Destination_Branch_Code`),
              KEY `idx_Packet_Manifest_Number` (`Packet_Manifest_Number`),
              KEY `idx_bag_packet_manifest` (`Bag_Manifest_Number`,`Packet_Manifest_Number`),
              KEY `idx_bookingts` (`BookingTs`),
              KEY `idx_ref_cus` (`Reference_No`,`Customer_Code`),
              KEY `idx_RTO_Tr` (`RTO_Tracking_Number`),
              KEY `idx_cons_RTO` (`ConsignmentKey`,`RTO_Tracking_Number`),
              KEY `idx_Parent_Tracking_Number` (`Parent_Tracking_Number`),
              KEY `idx_test` (`Tracking_Number`,`Delivered_By_Hub_Code`,`Parent_Tracking_Number`),
              KEY `idx_disN` (`Dispatch_Number`),
              KEY `Idx_customer` (`Customer_Code`)
            )
            """)
        conn.commit()
        conn.close()

        return {"status": "Table created successfully"}

    except Exception as e:
        return {"error": str(e)}
