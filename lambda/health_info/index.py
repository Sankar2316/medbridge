```python
"""
MedBridge — Health Info Cards Lambda
Copy this to: medbridge/lambda/health_info/index.py

Generates simple, jargon-free health information cards
for common conditions in the user's language.
"""

import json
import os

import boto3

bedrock = boto3.client("bedrock-runtime", region_name="ap-south-1")
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

HEALTH_INFO_SYSTEM_PROMPT = """You are MedBridge Health Info, generating simple health education cards 
for rural India. Your audience may have limited health literacy.

RULES:
1. Use the SAME LANGUAGE as the user's query (Tamil, Hindi, or English).
2. Use simple, everyday words — avoid medical jargon.
3. Include practical advice that works in rural settings.
4. Be culturally sensitive to Indian context.
5. Mention when to see a doctor.

Respond in this EXACT JSON format:
{
  "condition": "Name of condition (in user's language)",
  "what_is_it": "1-2 sentence explanation a 10-year-old can understand",
  "common_causes": ["cause1", "cause2", "cause3"],
  "home_remedies": ["remedy1", "remedy2", "remedy3"],
  "prevention": ["tip1", "tip2", "tip3"],
  "when_to_see_doctor": "Clear signs that mean 'go to the doctor now'",
  "myths_vs_facts": [
    {"myth": "common myth", "fact": "the truth"}
  ],
  "detected_language": "ta" | "hi" | "en"
}"""


def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        query = body.get("query", "")

        if not query:
            return response(400, {"error": "Please specify a health topic."})

        bedrock_response = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": HEALTH_INFO_SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": f"Give me health info about: {query}"}
                ],
                "temperature": 0.2,
            }),
        )

        result = json.loads(bedrock_response["body"].read())
        ai_response = result["content"][0]["text"]
        health_info = json.loads(ai_response)

        return response(200, {
            "success": True,
            "health_info": health_info,
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return response(500, {"error": "Failed to generate health info."})


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