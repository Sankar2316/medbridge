```python
"""
MedBridge — Symptom Triage Lambda
Copy this to: medbridge/lambda/symptom_triage/index.py

Accepts symptoms in any language (Tamil, Hindi, English)
→ Returns urgency level + triage recommendation
"""

import json
import os
import uuid
from datetime import datetime

import boto3

bedrock = boto3.client("bedrock-runtime", region_name="ap-south-1")
dynamodb = boto3.resource("dynamodb")
triage_table = dynamodb.Table(os.environ["TRIAGE_TABLE"])
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

TRIAGE_SYSTEM_PROMPT = """You are MedBridge, an AI health triage assistant for rural India.
Your job is to assess symptom urgency and recommend the right level of care.

IMPORTANT RULES:
1. You are NOT a doctor. Always recommend consulting a healthcare professional.
2. You can understand symptoms described in Tamil, Hindi, or English.
3. Always respond in the SAME LANGUAGE the user used.
4. Be empathetic and use simple, non-medical language.
5. Never diagnose — only triage urgency.

URGENCY LEVELS:
- 🔴 EMERGENCY: Life-threatening symptoms. Rush to nearest hospital / call 108.
  Examples: chest pain, difficulty breathing, severe bleeding, unconsciousness, 
  stroke signs (face drooping, arm weakness, speech difficulty), poisoning, 
  severe burns, head injury with confusion
  
- 🟡 URGENT: Needs medical attention within 24 hours. Visit PHC/CHC.
  Examples: high fever (>103°F/39.4°C), persistent vomiting, moderate pain,
  cuts needing stitches, urinary problems, eye infections, ear pain

- 🟢 NON-URGENT: Can wait / self-care possible. Visit PHC if symptoms persist.
  Examples: common cold, mild headache, minor cuts, mild body pain,
  seasonal allergies, mild stomach upset

Respond in this EXACT JSON format:
{
  "urgency": "emergency" | "urgent" | "non_urgent",
  "urgency_emoji": "🔴" | "🟡" | "🟢",
  "title": "Short title of the condition (in user's language)",
  "assessment": "2-3 sentence assessment in simple language (in user's language)",
  "recommended_action": "What to do right now (in user's language)",
  "facility_type": "hospital" | "chc" | "phc" | "self_care",
  "first_aid_tips": ["tip1", "tip2", "tip3"],
  "warning_signs": ["sign that means you should escalate to higher care"],
  "emergency_numbers": {"ambulance": "108", "health_helpline": "104"},
  "detected_language": "ta" | "hi" | "en"
}"""


def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        symptoms = body.get("symptoms", "")
        age = body.get("age", "")
        gender = body.get("gender", "")

        if not symptoms:
            return response(400, {"error": "Please describe your symptoms / உங்கள் அறிகுறிகளை விவரிக்கவும்"})

        # Build the user message with context
        user_message = f"Patient details: Age: {age}, Gender: {gender}\nSymptoms: {symptoms}"

        # Call Bedrock (Claude)
        bedrock_response = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": TRIAGE_SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.1,  # Low temp for consistent triage
            }),
        )

        result = json.loads(bedrock_response["body"].read())
        ai_response = result["content"][0]["text"]

        # Parse AI response
        triage_result = json.loads(ai_response)

        # Save to history (async-safe)
        session_id = body.get("session_id", str(uuid.uuid4()))
        try:
            triage_table.put_item(Item={
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "symptoms": symptoms,
                "age": str(age),
                "gender": gender,
                "urgency": triage_result.get("urgency", "unknown"),
                "result": json.dumps(triage_result),
            })
        except Exception:
            pass  # Don't fail the request if logging fails

        return response(200, {
            "success": True,
            "triage": triage_result,
            "session_id": session_id,
        })

    except json.JSONDecodeError:
        return response(400, {"error": "Invalid JSON in AI response. Please try again."})
    except Exception as e:
        print(f"Error: {str(e)}")
        return response(500, {"error": "Something went wrong. Please try again."})


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
```