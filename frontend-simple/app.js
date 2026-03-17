import ReactMarkdown from "react-markdown";

const { useState } = React;

const API_BASE = "http://127.0.0.1:8000";

function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [question, setQuestion] = useState("");
  const [answerResult, setAnswerResult] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [uploadResult, setUploadResult] = useState(() => {
  const documentId = localStorage.getItem("document_id");
  const filename = localStorage.getItem("filename");

  if (documentId && filename) {
    return {
      document_id: documentId,
      filename: filename,
    };
  }

  return null;
});

  const handleUpload = async () => {
    if (!selectedFile) {
      setError("Please select a PDF first.");
      return;
    }

    setError("");
    setUploading(true);
    setUploadResult(null);
    setAnswerResult(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch(`${API_BASE}/api/upload`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed.");
      }

      setUploadResult(data);
      localStorage.setItem("document_id", data.document_id);
        localStorage.setItem("filename", data.filename);
    } catch (err) {
      setError(err.message || "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    if (!question.trim()) {
      setError("Please enter a question.");
      return;
    }

    setError("");
    setAsking(true);
    setAnswerResult(null);

    try {
      const response = await fetch(`${API_BASE}/api/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
       body: JSON.stringify({
        question,
        document_id: uploadResult?.document_id
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not generate answer.");
      }

      setAnswerResult(data);
    } catch (err) {
      setError(err.message || "Could not generate answer.");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="app">
      <div className="container">
        <header className="hero">
          <h1>PDF Q&A Assistant</h1>
          <p>Upload one PDF and ask natural-language questions about it.</p>
        </header>

        <div className="grid">
          <div className="card">
            <h2>Upload PDF</h2>
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setSelectedFile(e.target.files[0])}
              disabled={uploading}
            />
            <button onClick={handleUpload} disabled={uploading}>
              {uploading ? "Uploading PDF..." : "Upload"}
            </button>

            {uploading && (
              <div className="loading-box">
                <div className="spinner"></div>
                <p>Uploading and processing PDF...</p>
              </div>
            )}

            {uploadResult && (
              <div className="success-box">
                <p><strong>File:</strong> {uploadResult.filename}</p>
                <p><strong>Pages:</strong> {uploadResult.total_pages_extracted}</p>
                <p><strong>Chunks:</strong> {uploadResult.total_chunks}</p>
              </div>
            )}
          </div>

          <div className="card">
            <h2>Ask a Question</h2>
            <textarea
              rows="5"
              placeholder="Ask something about the uploaded PDF..."
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={asking}
            />
            <button onClick={handleAsk} disabled={asking}>
              {asking ? "Generating Answer..." : "Ask"}
            </button>

            {asking && (
              <div className="loading-box">
                <div className="spinner"></div>
                <p>Generating answer...</p>
              </div>
            )}
          </div>
        </div>

        {error && <div className="error-box">{error}</div>}

        {answerResult && (
          <div className="card answer-card">
            <h2>Answer</h2>
            <div className="meta-row">
              <span><strong>Question:</strong> {answerResult.question}</span>
            </div>
            <div className="answer-box">
                <ReactMarkdown>{answerResult.answer}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);