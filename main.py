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
# GLOBAL STATE (single-user for now)
# =========================
pending_action = None
chat_history = []
CONFIRM_WORDS = ["yes", "yes proceed", "confirm", "go ahead"]

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
# TOOL 1: SCHEMA METADATA
# =========================
def get_schema_metadata():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SHOW TABLES")
        tables = [list(row.values())[0] for row in cursor.fetchall()]

        schema = {}

        for table in tables:
            cursor.execute(f"DESCRIBE {table}")
            columns = cursor.fetchall()

            cursor.execute(f"SHOW INDEX FROM {table}")
            indexes = cursor.fetchall()

            schema[table] = {
                "columns": columns,
                "indexes": indexes
            }

        cursor.close()
        conn.close()

        return schema

    except Exception as e:
        return {"error": str(e)}

# =========================
# TOOL 2: SAFE SQL EXECUTION
# =========================
def is_safe_query(query: str):
    query_lower = query.lower()
    forbidden = ["drop", "truncate"]
    return not any(word in query_lower for word in forbidden)

    #forbidden = ["drop", "truncate"]
    #for word in forbidden:
    #    if word in query_lower:
    #        return False
    #return True

def execute_sql(query: str):
    try:
        if not is_safe_query(query):
            return {"error": "Unsafe query blocked"}

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(query)

        if query.strip().lower().startswith("select"):
            result = cursor.fetchall()
        else:
            conn.commit()
            result = {"affected_rows": cursor.rowcount}

        cursor.close()
        conn.close()

        return result

    except Exception as e:
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
    global pending_action, chat_history
    try:
        body = await request.json()
        user_input = body.get("user_input", "")
        user_lower = user_input.lower().strip()

        print("🟢 User:", user_input)

        # =========================
        # HANDLE CONFIRMATION FIRST
        # =========================
        if user_lower in CONFIRM_WORDS:
            if pending_action:
                print("🟠 Executing pending action...")
        
                sql = pending_action["query"]
                pending_action = None
        
                data = execute_sql(sql)
                return {
                    "tool_used": "execute_sql",
                    "data": data,
                    "answer": f"✅ Done. Rows affected: {data.get('affected_rows', 0)}"
                }
            else:
                return {
                    "answer": "Nothing pending to confirm."
                }

        # =========================
        # STORE USER MESSAGE
        # =========================
        chat_history.append({
            "role": "user",
            "content": user_input
        })

        # =========================
        # STEP 1: DECISION
        # =========================
        decision_prompt = f"""
You are a helpful backend data assistant.

User query:
{user_input}

Capabilities:
- Query ANY table dynamically
- Perform SELECT, INSERT, UPDATE, DELETE, ALTER, CREATE
- Handle JOINs and indexes

Available tools:

1. get_schema_metadata
    - Returns all tables, columns, and indexes
2. execute_sql
    - Executes SQL queries

IMPORTANT RULES:
- Do NOT introduce yourself
- Do NOT mention databases unless asked
- Be direct and natural

SQL RULES:
- NEVER use DROP, TRUNCATE
- SHOW TABLES is allowed
- DESCRIBE table is allowed
- Prefer SELECT for read queries

LOGIC:
1. For any database operation:
   - SELECT → MUST call execute_sql
   - INSERT → MUST call execute_sql
   - UPDATE → MUST call execute_sql
   - DELETE → MUST call execute_sql
   - ALTER → MUST call execute_sql
   - CREATE → MUST call execute_sql
2. If user asks:
   - "list tables", "show tables", "schema", "table structure"
     → call get_schema_metadata
3. If user asks ANYTHING related to data:
   → generate SQL
   → call execute_sql
4. If request is NOT related to database:
   → return "answer"
5. SAFETY RULES:
   - DELETE without WHERE → DO NOT execute → ask for confirmation
   - UPDATE without WHERE → DO NOT execute → ask for confirmation
6. If user says:
   "insert sample data"
   → auto-generate realistic values and execute
7. If query fails:
   → fix SQL and retry once


OUTPUT JSON ONLY:

If tool needed:
{{
  "tool": "tool_name",
  "input": {{
    "query": "SQL query if needed",
    "reason": "why this tool"
  }}
}}

If no tool:
{{
  "answer": "your natural response"
}}
"""

        decision_response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            #messages=[{"role": "user", "content": decision_prompt}]
            messages = chat_history[-10:] + [
                {"role": "user", "content": decision_prompt}
            ]
        )

        content = extract_text(decision_response)
        content = re.sub(r"```json", "", content)
        content = re.sub(r"```", "", content).strip()

        print("🟡 Claude Decision:", content)

        chat_history.append({
            "role": "assistant",
            "content": content
        })

        try:
            parsed = json.loads(content)
        except:
            return {"error": "Invalid JSON", "raw": content}

        tool = parsed.get("tool")
        tool_input = parsed.get("input", {})
        answer = parsed.get("answer")

        # =========================
        # STEP 2: TOOL EXECUTION
        # =========================
        if tool == "get_schema_metadata":
            data = get_schema_metadata()

        elif tool == "execute_sql":
            query = tool_input.get("query")
            #data = execute_sql(query)
            if not query:
                return {"error": "No query provided"}
                
            query_lower = query.lower()
            
            # =========================
            # SAFETY CHECK
            # =========================
            if ("delete" in query_lower or "update" in query_lower):
                if "where" not in query_lower:
                    return {
                        "answer": "❌ Unsafe query blocked (missing WHERE clause)"
                    }
        
                # STORE pending action instead of executing
                pending_action = {
                    "type": "write",
                    "query": query
                }
        
                return {
                    "answer": "⚠️ This will modify data. Type 'yes proceed' to confirm."
                }
        
            # SAFE → EXECUTE
            data = execute_sql(query)

        elif answer:
            return {"tool_used": None, "answer": answer}

        else:
            return {"error": "Invalid tool decision"}

        print("🟣 Tool Output:", data)

        # =========================
        # STEP 3: FINAL RESPONSE
        # =========================
        final_prompt = f"""
User question: {user_input}
Tool used: {tool}

Tool result:
{data}

Instructions:

- If schema data:
  → List only table names clearly

- If SELECT:
  → Summarize results

- If INSERT → confirm how many rows inserted
- If UPDATE → confirm rows updated
- If DELETE → confirm rows deleted

- If user asked "how many":
  → return count only

- Keep response short and natural
- Do NOT mention internal tools
"""

        final_response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10000,
            messages=[{"role": "user", "content": final_prompt}]
        )

        final_text = extract_text(final_response)

        return {
            "tool_used": tool,
            "data": data,
            "answer": final_text
        }

    except Exception as e:
        print("❌ ERROR:", str(e))
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
