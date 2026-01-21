# 🤖 Gemini-Powered Customer Service System

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Flask](https://img.shields.io/badge/Flask-2.x-black.svg)
![Scikit-Learn](https://img.shields.io/badge/Scikit--Learn-ML-orange.svg)
![Gemini](https://img.shields.io/badge/Google-Gemini_API-red.svg)

An **end-to-end intelligent customer service assistant** integrating modern **Large Language Models (LLMs)** with **traditional Machine Learning algorithms**.  
Developed as part of the *Applications of Artificial Intelligence* course, this project demonstrates how to build **stateful, multimodal AI agents** for industrial use cases such as logistics and sentiment-driven customer support.

---

## ✨ Key Technical Highlights

- **Hybrid AI Architecture**  
  Google Gemini API for natural language generation + Scikit-learn models  
  (Logistic Regression for sentiment analysis & Linear Regression for delivery time forecasting)

- **Multimodal Interaction**  
  gTTS-powered voice responses alongside text-based chat

- **State-Aware Dialogue**  
  Session-based conversation memory across multi-turn interactions

- **Operational Intelligence**  
  Cargo tracking, tax calculation, and database-driven complaint logging

---

## 🖥️ Demo

> Replace the file below with your own demo recording

![Demo GIF](assets/demo.gif)

Or watch the demo video:  
[▶️ Demo Video](assets/demo_video.mp4)

---

## 📸 Screenshots

| Chat Interface | Voice Response | Database Logs |
|----------------|----------------|---------------|
| ![Chat](assets/screenshot_chat.png) | ![Voice](assets/screenshot_voice.png) | ![DB](assets/screenshot_db.png) |

> Place your screenshots inside an `assets/` folder.

---

## ⚙️ Prerequisites & Installation

### 🔑 Google Gemini API Key

1. Go to: https://aistudio.google.com/  
2. Log in with your Google account  
3. Click **"Get API Key"** and generate a new key

---

### 📥 Clone the Repository

```bash
git clone https://github.com/dogaece-koca/ai_customerservice.git
cd ai_customerservice
pip install -r requirements.txt

###🛠️ Environment Configuration

Create a .env file in the root directory:

GEMINI_API_KEY=your_actual_api_key_here

Ensure .env is included in .gitignore to prevent key exposure.


Project Structure

ai_customerservice/
│
├── webhook.py
│   └─ Main Flask server handling API routing & frontend
│
├── modules/
│   ├── gemini_ai.py
│   │   └─ LLM orchestration & prompt engineering
│   │
│   ├── ml_modulu.py
│   │   └─ Sentiment & delivery-time ML models
│   │
│   └── database.py
│       └─ SQLite persistence layer
│
├── db_simulasyon_kurulum.py
│   └─ Database initialization script
│
└── assets/
    └─ Screenshots & demo media


Running the Application

1) Initialize the Database

python db_simulasyon_kurulum.py

2) Start the Server

python webhook.py

3) Open Web Interface

http://127.0.0.1:5000


Features Demonstrated

- LLM-powered conversational agent with structured intent handling
- Classical ML integration inside LLM-driven workflows
- Context-aware multi-turn conversation management
- Database-backed customer service simulation
- Voice-enabled assistant responses


Notes

This project is developed for academic and demonstration purposes.
Model performance and dataset size can be extended for production deployment.


Possible Future Improvements

- Docker containerization
- REST API documentation (Swagger)
- Multi-language support
- Real shipment tracking API integration


Author

Doğa Ece Koca
GitHub: https://github.com/dogaece-koca
LinkedIn: (optional — add if you want)

If you find this project useful, consider giving it a star!


Assets Folder Guide

assets/
├── demo.gif
├── demo_video.mp4
├── screenshot_chat.png
├── screenshot_voice.png
└── screenshot_db.png
