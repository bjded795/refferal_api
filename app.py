from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from urllib.parse import quote_plus
from googlesearch import search
import google.generativeai as genai
import requests, re, time
from datetime import datetime

app = Flask(__name__)

# === GEMINI SETUP ===
GEMINI_API_KEY = "AIzaSyCa9yfmM-D69p6dpu-7lt52aiIPBPDFB0E"
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# === MONGODB SETUP ===
raw_username = "vinayaksharmalion20715"
raw_password = "vinayak@123"
username = quote_plus(raw_username)
password = quote_plus(raw_password)
MONGO_URI = f"mongodb+srv://{username}:{password}@cluster0.o7s3xjj.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(MONGO_URI)
db = client["referral_scraper"]
collection = db["emails_grouped"]

# === COUNTRY MAP ===
country_tld_map = {
    "India": "in", "Germany": "de", "UK": "co.uk", "France": "fr", "Canada": "ca", "USA": "us",
    "Australia": "au", "Netherlands": "nl", "Brazil": "br", "Japan": "jp", "Spain": "es", "Italy": "it",
    "Singapore": "sg", "Mexico": "mx", "Sweden": "se", "Poland": "pl", "Norway": "no", "South Korea": "kr",
    "China": "cn", "Russia": "ru", "Indonesia": "id", "Nigeria": "ng", "Pakistan": "pk", "Bangladesh": "bd",
    "Egypt": "eg", "Philippines": "ph", "Vietnam": "vn", "Turkey": "tr", "Iran": "ir", "Thailand": "th",
    "South Africa": "za", "Argentina": "ar", "Colombia": "co", "Malaysia": "my", "Saudi Arabia": "sa",
    "Ukraine": "ua", "Algeria": "dz", "Morocco": "ma", "United Arab Emirates": "ae", "New Zealand": "nz",
    "Switzerland": "ch", "Belgium": "be", "Austria": "at", "Denmark": "dk", "Finland": "fi", "Ireland": "ie",
    "Portugal": "pt", "Chile": "cl", "Peru": "pe"
}

personal_domains = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "protonmail.com", "aol.com", "icloud.com", "live.com"
}

def is_corporate_email(email):
    return email.split("@")[-1].lower() not in personal_domains

def extract_company_from_email(email):
    return email.split("@")[-1].split(".")[0]

def extract_emails_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=7)
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()
        email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
        emails = re.findall(email_pattern, text)
        return [
            e for e in emails
            if not e.endswith(("png", "jpg", "jpeg"))
            and is_corporate_email(e)
        ]
    except Exception as e:
        print(f"[!] Error scraping {url}: {e}")
        return []

def scrape_emails(job_profile, country):
    existing = collection.find_one({"country": country, "job_profile": job_profile})
    if existing:
        return existing["emails"], True

    tld = country_tld_map.get(country, "")
    query = f"{job_profile} referral hiring email {country} site:linkedin.com OR site:x.com OR site:reddit.com"
    if tld:
        query += f" site:.{tld}"

    seen_urls = set()
    collected_emails = []
    results_to_fetch = 10
    max_emails = 30

    while len(collected_emails) < max_emails and results_to_fetch <= 100:
        urls = list(search(query, num_results=results_to_fetch))
        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            found = extract_emails_from_url(url)
            for email in found:
                if any(e["email"] == email for e in collected_emails):
                    continue
                company = extract_company_from_email(email)
                collected_emails.append({
                    "email": email,
                    "company": company,
                    "source_url": url
                })
                if len(collected_emails) >= max_emails:
                    break
        results_to_fetch += 10
        time.sleep(2)

    if collected_emails:
        doc = {
            "country": country,
            "job_profile": job_profile,
            "emails": collected_emails,
            "timestamp": datetime.utcnow()
        }
        collection.insert_one(doc)

    return collected_emails, False

def generate_referral_email(resume_text, job_role):
    prompt = f"""
You are an expert writer helping craft professional referral request emails.

Below is a resume:
\"\"\"{resume_text}\"\"\"

Use it to generate a **complete and polished email body** that the user can send directly when requesting a referral for the role of **{job_role}**.

The email should:
- Be self-contained and ready to send (no placeholders, no missing pieces)
- Not mention any resume being attached
- Sound polite, confident, and concise (max ~130 words)
- Be personalized based on the resume
- Be general enough to send to any employee from any company
- Focus only on requesting a referral (no job links or extra instructions)
- Avoid vague requests like “let me know if you can help”; assume the recipient is capable

Write only the **email body** — no subject line, no greeting like “Hi [Name]”. Start directly with the first sentence of the email.
"""
    response = gemini_model.generate_content(prompt)
    return response.text.strip()

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    job_profile = data.get("job_profile", "").strip()
    country = data.get("country", "").strip()
    resume_text = data.get("resume_text", "").strip()

    if not job_profile or not country or not resume_text:
        return jsonify({"error": "Missing job_profile, country, or resume_text"}), 400

    try:
        emails, from_cache = scrape_emails(job_profile, country)
        email_body = generate_referral_email(resume_text, job_profile)

        return jsonify({
            "job_profile": job_profile,
            "country": country,
            "cached": from_cache,
            "emails_found": emails,
            "referral_email": email_body
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Email scraper and referral generator API is running."})

if __name__ == "__main__":
    app.run(debug=True)
