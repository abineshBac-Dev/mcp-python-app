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
            CREATE TABLE `PAYMENT_DETAILS` (
              `PaymentDetailsKey` bigint(20) NOT NULL AUTO_INCREMENT,
              `Tracking_Number` varchar(50) NOT NULL,
              `Invoice_Value` decimal(10,2) DEFAULT NULL,
              `Insurance_Option` varchar(25) DEFAULT NULL,
              `Collected_Amount` decimal(10,2) DEFAULT NULL,
              `Payment_Mode` varchar(20) DEFAULT NULL,
              `Collected_By` varchar(50) DEFAULT NULL,
              `Collected_By_Hub_Code` varchar(25) DEFAULT NULL,
              `Collected_By_Hub_Name` varchar(50) DEFAULT NULL,
              `CDS_Status` varchar(20) DEFAULT NULL,
              `CDS_Date` datetime DEFAULT NULL,
              `CDS_Number` varchar(20) DEFAULT NULL,
              `Vas_Prod_Code` varchar(10) DEFAULT NULL,
              `Vas_Amount_COD` double(10,2) DEFAULT NULL,
              `Vas_Amount_FOD` double(10,2) DEFAULT NULL,
              `Mode_of_Collection` varchar(50) DEFAULT NULL,
              `Declared_Value` varchar(20) DEFAULT NULL,
              `Declared_Value_Currency` varchar(20) DEFAULT NULL,
              `GST_Percent` double(10,2) DEFAULT NULL,
              `Amount` double(10,2) DEFAULT NULL,
              `Total_Amount` double(10,2) DEFAULT NULL,
              `Currency` varchar(20) DEFAULT NULL,
              `cds_ref_no` varchar(100) DEFAULT NULL,
              `approved_ref_no` varchar(50) DEFAULT NULL,
              `Remittance_Status` varchar(25) DEFAULT NULL,
              `Remittance_Date` datetime DEFAULT NULL,
              `SAP_coll_doc_no` varchar(30) DEFAULT NULL,
              `UTR_Number` varchar(30) DEFAULT NULL,
              `Recon_Ref_No` varchar(25) DEFAULT NULL,
              `Cheque_Number` varchar(20) DEFAULT NULL,
              `Cheque_Date` date DEFAULT NULL,
              `FavourOf` varchar(50) DEFAULT NULL,
              `NC_TRANS_STATUS_XI` char(1) DEFAULT NULL,
              `Exception_Remarks` varchar(40) DEFAULT NULL,
              `CDS_HandoverTs` datetime DEFAULT NULL,
              `CDS_ClosureTs` datetime DEFAULT NULL,
              `Stmt_No` varchar(20) DEFAULT NULL,
              `Pdn_Status` decimal(2,0) DEFAULT NULL,
              `Delivery_Charge` double(10,4) DEFAULT NULL,
              `Actual_Delivery_Charge` double(10,4) DEFAULT NULL,
              `Risk_Charge` decimal(8,2) DEFAULT NULL,
              `Actual_Risk_Charge` decimal(8,2) DEFAULT NULL,
              `Pickup_Charge` decimal(10,2) DEFAULT NULL,
              `Pickup_Status` varchar(4) DEFAULT NULL,
              `Rate_Calc_Date` datetime DEFAULT NULL,
              `Pickup_Charge_Type` varchar(25) DEFAULT NULL,
              `Pickup_Eligibility_Status` char(2) DEFAULT NULL,
              `Pickup_Franchisee_Code` varchar(25) DEFAULT NULL,
              `Pickup_Statement_Number` varchar(15) DEFAULT NULL,
              `Pickup_Reason` varchar(50) DEFAULT NULL,
              `Pr_Number` varchar(25) DEFAULT NULL,
              `Cod_Remarks` varchar(50) DEFAULT NULL,
              `Fod_Remarks` varchar(50) DEFAULT NULL,
              `Ins_Amount` double(10,2) DEFAULT NULL,
              `ReceiverGstin` varchar(20) DEFAULT NULL,
              `Invoice_Number` varchar(50) DEFAULT NULL,
              `Invoice_Date` date DEFAULT NULL,
              `Dispatch_AWB` varchar(15) DEFAULT NULL,
              `CreateTs` timestamp NOT NULL DEFAULT current_timestamp(),
              `CreatedBy` varchar(50) DEFAULT NULL,
              `ModifyTs` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
              `ModifiedBy` varchar(50) DEFAULT NULL,
              PRIMARY KEY (`PaymentDetailsKey`),
              KEY `idx_approved_ref_no` (`approved_ref_no`),
              KEY `idx_cds_ref_no` (`cds_ref_no`),
              KEY `idx_CreateTs` (`CreateTs`),
              KEY `idx_Tracking_Number` (`Tracking_Number`),
              KEY `idx_CDS_Number` (`CDS_Number`),
              KEY `idx_comb` (`Tracking_Number`,`CDS_Number`)
            )
            """)
        conn.commit()
        conn.close()

        return {"status": "Table created successfully"}

    except Exception as e:
        return {"error": str(e)}
