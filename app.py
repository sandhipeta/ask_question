from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import os
import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from groq import Groq

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


chunks = []
index = None

model = SentenceTransformer("all-MiniLM-L6-v2")

client = Groq(
    api_key= os.getenv("GROQ_API_KEY")
)

def load_pdf(file_path):
    reader = PdfReader(file_path)
    text = ""
    
    for page in reader.pages:
        text += (page.extract_text() or "") + "\n"
    
    return text

def split_text_words(text, chunk_size=200, overlap= 15):
    words = text.split()
    chunks = []
    start = 0
    
    while start < len(words):
        end = start+chunk_size
        chunk = words[start:end]
        
        chunks.append(" ".join(chunk))
        
        start+= chunk_size-overlap
    
    return chunks

def process_pdf(file_path):
    global chunks, index
    
    text = load_pdf(file_path)
    
    chunks = split_text_words(text)
    
    if not chunks:
        raise ValueError("No text extracted from PDF")
    
    embeddings = model.encode(chunks)
    embeddings = np.array(embeddings).astype("float32")
    
    if embeddings.ndim != 2:
        embeddings = embeddings.reshape(
            embeddings.shape[0],
            -1
        )
    
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    
    index.add(
        np.ascontiguousarray(
            embeddings
        )
    )


def ask_llm(prompt):
    
    try:
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print("Groq Error:", str(e))
        return f"Error: {str(e)}"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/upload", methods = ["POST"])
def upload_pdf():
    
    try:
    
        if "pdf" not in request.files:
            return jsonify(
                {
                    "error": "No file uploaded"
                }
            )
        
        file = request.files["pdf"]
        
        if not file.filename:
            return jsonify({
                "error": "Invalid file"
            })
        
        filename = secure_filename(
            file.filename
        )
        
        if not filename.lower().endswith(".pdf"):
            return jsonify({
                "error": "Please upload PDF only"
            })
        
        file_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )
        
        file.save(file_path)
        
        process_pdf(file_path)
        
        return jsonify({
            "message": "PDF uploaded successfully"
        })
    except Exception as e:
        return jsonify({
            "error": str(e)
        })

@app.route("/ask", methods=["POST"])
def ask_question():
    global chunks, index
    
    if index is None:
        return jsonify({
            "answer": "Upload PDF first"
        })
    query = request.json.get(
        "question"
    )
    
    if not query:
        return jsonify({
            "answer": "Please ask something"
        })
    
    query_embedding = model.encode([query])
    query_embedding = np.array(query_embedding).astype("float32")
    
    k = 4
    
    distances, indices = index.search(
        np.ascontiguousarray(
            query_embedding
        ),
        k
    )
    
    retrived_chunks = [
        chunks[i]
        for i in indices[0]
    ]
    
    context = "\n".join(
        retrived_chunks
    )
    
    prompt = f"""
    You are an acedmic tutor.
    Answer the question using ONLY the context below.
    
    Give a detailed answer in simple langauge.
    
    Rules:
    1. Explain 10-15 lines.
    2. Include defination.
    3. Explain working/process
    4. Include important points if available.
    5. If answer is not found, say "I don't know"
    
    Context:
    {context}
    
    Question:
    {query}
    
    Detailed Answer:    
    """
    
    answer = ask_llm(prompt)
    
    return jsonify({
        "answer": answer
    })


if __name__=="__main__":
    app.run(debug=True)
    
    