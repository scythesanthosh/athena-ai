import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import json
import datetime
import os
from pymongo import MongoClient
from bson.objectid import ObjectId
from pymongo.server_api import ServerApi
from fastapi.responses import StreamingResponse
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
import io
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
app = FastAPI()

@app.middleware("http")
async def log_errors(request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        raise e
API_KEY = os.getenv("OPENROUTER_API_KEY")  # 🔐 paste key
MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"  # or fixed model

# ---- MongoDB Connection ----
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = "cognitive_engine"
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
db = client[MONGO_DB]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with your specific domain
    allow_credentials=True,
    allow_methods=["*"], # This allows OPTIONS, POST, etc.
    allow_headers=["*"],
)
# ---- Request Schema ----
class ThoughtRequest(BaseModel):
    thought: str
    user_id: str

# ---- OpenRouter Call ----
def analyze_thought(user_input):
    print("Calling OpenRouter with user input:", user_input)
    prompt = f"""
You are a Cognitive Pattern Analysis Engine.
Do NOT provide therapy.
Do NOT diagnose mental illness.
Return ONLY valid JSON.

Analyze the following thought:

\"\"\"
{user_input}
\"\"\"

Return JSON in this format:

{{
  "summary": "",
  "emotional_tone": {{
    "primary": "",
    "intensity": "low | medium | high"
  }},
  "cognitive_patterns": [],
  "cognitive_distortions_detected": [],
  "attribution_style": "internal | external | mixed",
  "time_orientation": "past | present | future | mixed",
  "negativity_bias_score": 0.0,
  "self_critical_index": 0.0,
  "future_anxiety_index": 0.0,
  "evidence_quotes": []
}}
"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    result = response.json()
    print("Result from OpenRouter:", result)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    content = result["choices"][0]["message"]["content"].strip()

    try:
        return json.loads(content)
    except:
        raise HTTPException(status_code=500, detail="Invalid JSON from model")

# ---- Save Entry ----
def save_entry(user_id, entry_analysis):
    collection = db["user_entries"]
    
    entry_analysis["user_id"] = user_id
    entry_analysis["date"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    result = collection.insert_one(entry_analysis)
    entry_analysis["_id"] = str(result.inserted_id)  # Convert ObjectId to string for JSON serialization
    return str(result.inserted_id)

# ---- API Endpoint ----
@app.post("/analyze")
def analyze(request: ThoughtRequest):

    analysis = analyze_thought(request.thought)
    print("User:", request.user_id)
    print("Analysis", analysis)
    save_entry(request.user_id, analysis)

    return {
        "status": "success",
        "analysis": analysis
    }
def generate_weekly_report(user_id):
    from datetime import timedelta
    
    collection = db["user_entries"]
    
    # Calculate the date from 7 days ago
    seven_days_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    
    # Fetch entries from the last 7 days for the specific user
    entries = list(collection.find({
        "user_id": user_id,
        "date": {"$gte": seven_days_ago}  # Greater than or equal to 7 days ago
    }))
    print(entries)
    if not entries:
        raise HTTPException(status_code=404, detail="No entries found for this user in the last 7 days")
    
    # Convert ObjectId to string for JSON serialization
    for entry in entries:
        entry["_id"] = str(entry["_id"])
    
    # Use all entries for POC (later we filter by date)
    weekly_data = json.dumps(entries, indent=2)

    prompt = f"""
You are a Cognitive Reflection Report Generator.
Make Sure your Analysis is corrrect and based on the data provide.

You do NOT provide therapy.
You do NOT diagnose mental illness.
You analyze cognitive patterns only.

Analyze the following weekly cognitive data:

{weekly_data}

Generate a structured weekly report with sections:

1. Overall Cognitive Trend
2. Dominant Thinking Patterns
3. Distortion Frequency Analysis
4. Emotional Stability Trend
5. Evidence-Based Observations
6. 3 Cognitive Upgrade Strategies
7. What Improved
8. What Needs Attention

Additionally, classify the user's dominant Cognitive Archetype.

Available Archetypes:

- The Strategist
- The Self-Critic
- The Catastrophizer
- The Stoic Processor
- The Idealist
- The Reactor
- The Comparer
- The Optimizer

The archetype must be derived strictly from detected thinking patterns.

Return valid JSON in this format:

{{
  "overall_trend": "",
  "dominant_patterns": [],
  "distortion_analysis": "",
  "emotional_trend": "",
  "observations": "",
  "upgrade_strategies": [],
  "improvements": "",
  "attention_required": "",
  "archetype": {{
      "primary": "",
      "secondary": "",
      "confidence_score": 0.0,
      "justification": ""
  }}
}}
"""


    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    result = response.json()

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    content = result["choices"][0]["message"]["content"]

    try:
        return json.loads(content)
    except:
        raise HTTPException(status_code=500, detail="Invalid JSON from model")
@app.get("/mongo-test")
def test_mongo():
    try:
        print("Testing MongoDB connection...")

        # this forces MongoDB to respond
        client.admin.command("ping")

        collections = db.list_collection_names()

        return {
            "status": "MongoDB connected",
            "collections": collections
        }

    except Exception as e:
        print("MongoDB error:", e)
        traceback.print_exc()
        return {"error": str(e)}   
@app.get("/weekly-report/{user_id}")
def weekly_report(user_id: str):
    
    report = generate_weekly_report(user_id)

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    story = []
    styles['Normal'].fontName = 'DejaVu'
    styles['Heading2'].fontName = 'DejaVu'
    styles['Title'].fontName = 'DejaVu'
    logo = Image("logo.png", width=77, height=120)
    logo.hAlign = "CENTER"
    story.append(logo)
    story.append(Spacer(1,20))
    # Title
    story.append(Paragraph("<b>Athena's Report</b>", styles['Title']))
    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>Weekly Cognitive & Emotional Analysis Report</b>", styles['Title']))
    story.append(Spacer(1, 20))

    #story.append(Paragraph(f"User ID: {escape(str(user_id))}", styles['Normal']))
    #story.append(Spacer(1, 20))

    # Overall Trend
    story.append(Paragraph("<b>Overall Trend</b>", styles['Heading2']))
    story.append(Paragraph(escape(report.get("overall_trend", "No data")), styles['Normal']))
    story.append(Spacer(1, 15))

    # Dominant Patterns
    story.append(Paragraph("<b>Dominant Cognitive Patterns</b>", styles['Heading2']))
    patterns = report.get("dominant_patterns", [])
    if patterns:
        story.append(Paragraph(escape(", ".join(patterns)), styles['Normal']))
    else:
        story.append(Paragraph("None", styles['Normal']))
    story.append(Spacer(1, 15))

    # Distortion Analysis
    story.append(Paragraph("<b>Distortion Analysis</b>", styles['Heading2']))
    story.append(Paragraph(escape(report.get("distortion_analysis", "No data")), styles['Normal']))
    story.append(Spacer(1, 15))

    # Emotional Trend
    story.append(Paragraph("<b>Emotional Trend</b>", styles['Heading2']))
    story.append(Paragraph(escape(report.get("emotional_trend", "No data")), styles['Normal']))
    story.append(Spacer(1, 15))

    # Observations
    story.append(Paragraph("<b>Key Observations</b>", styles['Heading2']))
    story.append(Paragraph(escape(report.get("observations", "No data")), styles['Normal']))
    story.append(Spacer(1, 15))

    # Improvement Areas
    story.append(Paragraph("<b>Positive Improvements</b>", styles['Heading2']))
    story.append(Paragraph(escape(report.get("improvements", "No data")), styles['Normal']))
    story.append(Spacer(1, 15))

    # Strategies
    story.append(Paragraph("<b>Recommended Strategies</b>", styles['Heading2']))
    strategies = report.get("upgrade_strategies", [])
    if strategies:
        for s in strategies:
            story.append(Paragraph(f"• {escape(s)}", styles['Normal']))
    else:
        story.append(Paragraph("None", styles['Normal']))
    story.append(Spacer(1, 15))

    # Attention Required
    story.append(Paragraph("<b>Attention Required</b>", styles['Heading2']))
    story.append(Paragraph(escape(report.get("attention_required", "No data")), styles['Normal']))
    story.append(Spacer(1, 20))

    # Archetype
    archetype = report.get("archetype", {})
    if archetype:
        story.append(Paragraph("<b>Cognitive Archetype</b>", styles['Heading2']))
        story.append(Paragraph(f"Primary: {escape(archetype.get('primary','Unknown'))}", styles['Normal']))
        story.append(Paragraph(f"Secondary: {escape(archetype.get('secondary','Unknown'))}", styles['Normal']))
        story.append(Paragraph(f"Confidence Score: {archetype.get('confidence_score','N/A')}", styles['Normal']))
        story.append(Paragraph(
            f"Justification: {escape(archetype.get('justification','No explanation'))}",
            styles['Normal']
        ))

    doc = SimpleDocTemplate(buffer, pagesize=A4)
    doc.build(story)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=weekly_report_{user_id}.pdf"
        }
    )