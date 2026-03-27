import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
import pandas as pd
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration
app = FastAPI(title="ABM EduPilote AI Service")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalysisRequest(BaseModel):
    data_type: str  # 'attendance', 'students', 'performance'
    raw_data: list
    question: str = None

@app.post("/analyze")
async def analyze_data(request: AnalysisRequest):
    try:
        # Transformation des données en DataFrame Pandas pour analyse accrue
        df = pd.DataFrame(request.raw_data)
        
        # Création d'un résumé statistique pour le contexte de l'IA
        summary = df.describe().to_string()
        context = f"Données de l'établissement ({request.data_type}):\n{summary}\n\nDonnées brutes (échantillon):\n{df.head(10).to_string()}"
        
        prompt = request.question or "Analyse ces données universitaires et donne-moi 3 insights stratégiques pour améliorer l'établissement."

        # Appel à Groq (Llama 3 70B pour une connaissance accrue)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Tu es l'expert IA d'ABM EduPilote. Tu analyses les données universitaires pour aider les administrateurs africains à optimiser leurs écoles."
                },
                {
                    "role": "user",
                    "content": f"{context}\n\nQuestion: {prompt}"
                }
            ],
            model="llama3-70b-8192",
            temperature=0.5,
        )

        return {
            "success": True,
            "analysis": chat_completion.choices[0].message.content,
            "stats": {
                "count": len(df),
                "columns": df.columns.tolist()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
