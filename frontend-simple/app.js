const { useEffect, useRef, useState } = React;

const API_BASE = window.location.port === "5173" ? "http://127.0.0.1:8000" : "";
const GENERAL_COLLECTION_ID = "general";

const STORAGE_KEYS = {
  activeSessionId: "qa_active_session_id_v2",
  theme: "qa_theme_v2",
};

const DOCUMENT_PROMPTS = [
  "Summarize these PDFs",
  "Compare the uploaded files",
  "What are the key ideas?",
  "List examples from the documents",
];

const GENERAL_PROMPTS = [
  "What is Python?",
  "How many design patterns are there?",
  "Explain REST APIs simply",
  "What is RAG?",
];

function createMessageId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random()}`;
}

function getCollectionTitle(collection) {
  if (!collection) {
    return "General";
  }

  if (collection.total_files === 1) {
    return collection.documents?.[0]?.filename || "Uploaded PDF";
  }

  return `${collection.total_files} PDFs`;
}

function getInitialState() {
  return {
    collection: null,
    collections: [],
    sessions: [],
    activeSessionId: "",
    theme: localStorage.getItem(STORAGE_KEYS.theme) || "dark",
  };
}

function getActiveSessionStorageKey(user) {
  return `${STORAGE_KEYS.activeSessionId}:${user?.user_id || "anonymous"}`;
}

function apiFetch(path, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
  });
}

function truncateTitle(text) {
  return text.length > 44 ? `${text.slice(0, 41)}...` : text;
}

function formatCount(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function getSessionContextLabel(session, collections) {
  if (session.collectionId === GENERAL_COLLECTION_ID) {
    return "General";
  }

  const collection = collections.find((item) => item.collection_id === session.collectionId);
  return collection ? getCollectionTitle(collection) : "Documents";
}

function apiSessionToUiSession(session) {
  return {
    id: session.session_id,
    collectionId: session.collection_id || GENERAL_COLLECTION_ID,
    title: session.title || "Chat",
    messages: (session.messages || []).map((message) => ({
      id: message.id || createMessageId(),
      role: message.role,
      text: message.text,
      source: message.source,
      citations: message.citations || [],
      createdAt: message.created_at,
    })),
    createdAt: session.created_at,
    updatedAt: session.updated_at,
  };
}

function App() {
  const [initialState] = useState(getInitialState);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [question, setQuestion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [draggingFile, setDraggingFile] = useState(false);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState(initialState.theme);
  const [uploadResult, setUploadResult] = useState(initialState.collection);
  const [collections, setCollections] = useState(initialState.collections);
  const [sessions, setSessions] = useState(initialState.sessions);
  const [activeSessionId, setActiveSessionId] = useState(initialState.activeSessionId);
  const [auth, setAuth] = useState(null);
  const messagesEndRef = useRef(null);
  const questionRef = useRef(null);
  const fileInputRef = useRef(null);

  const isAuthenticated = Boolean(auth?.authenticated);
  const authIsReady = auth !== null;
  const currentUser = auth?.user || null;
  const authProviders = auth?.providers || [];
  const activeSession = sessions.find((session) => session.id === activeSessionId) || sessions[0] || null;
  const collectionId = activeSession?.collectionId || uploadResult?.collection_id || GENERAL_COLLECTION_ID;
  const activeCollection =
    collectionId === GENERAL_COLLECTION_ID
      ? null
      : collections.find((collection) => collection.collection_id === collectionId) ||
        (uploadResult?.collection_id === collectionId ? uploadResult : null);
  const hasCollection = Boolean(activeCollection?.collection_id);
  const messages = activeSession?.messages || [];
  const promptSuggestions = hasCollection ? DOCUMENT_PROMPTS : GENERAL_PROMPTS;

  const upsertSession = (nextSession) => {
    setSessions((current) => [
      nextSession,
      ...current.filter((session) => session.id !== nextSession.id),
    ]);
  };

  const createBackendSession = async (targetCollectionId = collectionId, title = "Chat") => {
    const response = await apiFetch("/api/sessions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        collection_id: targetCollectionId === GENERAL_COLLECTION_ID ? null : targetCollectionId,
        title,
      }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Could not create chat session.");
    }

    return apiSessionToUiSession(data);
  };

  const updateBackendSessionCollection = async (sessionId, targetCollectionId) => {
    const response = await apiFetch(`/api/sessions/${sessionId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        collection_id: targetCollectionId,
      }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Could not update chat document context.");
    }

    return apiSessionToUiSession(data);
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(STORAGE_KEYS.theme, theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;

    const loadSavedState = async () => {
      setHydrating(true);

      try {
        const authResponse = await apiFetch("/api/auth/status");
        const authData = await authResponse.json();

        if (!authResponse.ok) {
          throw new Error(authData.detail || "Could not check sign-in status.");
        }

        if (cancelled) {
          return;
        }

        setAuth(authData);

        if (!authData.authenticated) {
          setCollections([]);
          setSessions([]);
          setUploadResult(null);
          setActiveSessionId("");
          return;
        }

        const response = await apiFetch("/api/state");
        const data = await response.json();

        if (!response.ok) {
          if (response.status === 401) {
            setAuth({
              authenticated: false,
              required: true,
              configured: true,
              user: null,
            });
            return;
          }

          throw new Error(data.detail || "Could not load saved chats.");
        }

        let nextSessions = (data.sessions || []).map(apiSessionToUiSession);

        if (nextSessions.length === 0) {
          const firstSession = await createBackendSession(GENERAL_COLLECTION_ID);
          nextSessions = [firstSession];
        }

        if (cancelled) {
          return;
        }

        const nextCollections = data.collections || [];
        const storedActiveSessionId = localStorage.getItem(
          getActiveSessionStorageKey(authData.user)
        );
        const nextActiveSession =
          nextSessions.find((session) => session.id === storedActiveSessionId) ||
          nextSessions[0];
        const nextActiveCollection =
          nextActiveSession.collectionId === GENERAL_COLLECTION_ID
            ? null
            : nextCollections.find(
                (collection) => collection.collection_id === nextActiveSession.collectionId
              ) || null;

        setCollections(nextCollections);
        setSessions(nextSessions);
        setActiveSessionId(nextActiveSession.id);
        setUploadResult(nextActiveCollection);
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Could not load saved chats.");
        }
      } finally {
        if (!cancelled) {
          setHydrating(false);
        }
      }
    };

    loadSavedState();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (activeSessionId && currentUser) {
      localStorage.setItem(getActiveSessionStorageKey(currentUser), activeSessionId);
    }
  }, [activeSessionId, currentUser]);

  useEffect(() => {
    if (!sessions.some((session) => session.id === activeSessionId)) {
      setActiveSessionId(sessions[0]?.id || "");
    }
  }, [sessions, activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, asking]);

  const updateSession = (sessionId, updater) => {
    setSessions((current) =>
      current.map((session) => (
        session.id === sessionId ? updater(session) : session
      ))
    );
  };

  const selectFiles = (fileList) => {
    const files = Array.from(fileList || []);
    setError("");

    if (files.length === 0) {
      setSelectedFiles([]);
      return;
    }

    const invalidFile = files.find(
      (file) => file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")
    );

    if (invalidFile) {
      setSelectedFiles([]);
      setError("Please choose PDF files only.");
      return;
    }

    setSelectedFiles(files);
  };

  const usePrompt = (prompt) => {
    setQuestion(prompt);
    questionRef.current?.focus();
  };

  const openCollection = async (collection) => {
    setUploadResult(collection);
    const collectionSessions = sessions.filter(
      (session) => session.collectionId === collection.collection_id
    );

    if (collectionSessions.length > 0) {
      setActiveSessionId(collectionSessions[0].id);
    } else {
      try {
        const nextSession = await createBackendSession(collection.collection_id);
        upsertSession(nextSession);
        setActiveSessionId(nextSession.id);
      } catch (err) {
        setError(err.message || "Could not create chat session.");
        return;
      }
    }

    setError("");
  };

  const openSession = (session) => {
    setActiveSessionId(session.id);

    if (session.collectionId === GENERAL_COLLECTION_ID) {
      setUploadResult(null);
    } else {
      const collection = collections.find((item) => item.collection_id === session.collectionId);
      setUploadResult(collection || null);
    }

    setError("");
  };

  const createNewChat = async () => {
    try {
      const nextSession = await createBackendSession(collectionId);
      upsertSession(nextSession);
      setActiveSessionId(nextSession.id);
      setError("");
    } catch (err) {
      setError(err.message || "Could not create chat session.");
    }
  };

  const clearChat = async () => {
    if (!activeSession) {
      return;
    }

    const linkedCollection =
      activeSession.collectionId === GENERAL_COLLECTION_ID
        ? null
        : collections.find(
            (collection) => collection.collection_id === activeSession.collectionId
          );

    if (linkedCollection) {
      const title = getCollectionTitle(linkedCollection);
      const confirmed = window.confirm(
        `Clear this chat and delete "${title}" from your documents?`
      );

      if (!confirmed) {
        return;
      }
    }

    try {
      const response = await apiFetch(`/api/sessions/${activeSession.id}/messages`, {
        method: "DELETE",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not clear chat.");
      }

      upsertSession(apiSessionToUiSession(data));

      if (linkedCollection) {
        await deleteCollection(linkedCollection, {
          confirm: false,
          throwOnError: true,
        });
      }

      setError("");
    } catch (err) {
      setError(err.message || "Could not clear chat or delete document.");
    }
  };

  const renameChat = async (session) => {
    const nextTitle = window.prompt("Rename chat", session.title);

    if (nextTitle === null) {
      return;
    }

    const trimmedTitle = nextTitle.trim();

    if (!trimmedTitle) {
      setError("Chat title cannot be empty.");
      return;
    }

    try {
      const response = await apiFetch(`/api/sessions/${session.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: trimmedTitle }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not rename chat.");
      }

      upsertSession(apiSessionToUiSession(data));
      setError("");
    } catch (err) {
      setError(err.message || "Could not rename chat.");
    }
  };

  const deleteChat = async (session) => {
    if (!window.confirm(`Delete "${session.title}"?`)) {
      return;
    }

    try {
      const response = await apiFetch(`/api/sessions/${session.id}`, {
        method: "DELETE",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not delete chat.");
      }

      const remainingSessions = sessions.filter((item) => item.id !== session.id);
      setSessions(remainingSessions);

      if (session.id === activeSession?.id) {
        if (remainingSessions.length > 0) {
          const nextSession = remainingSessions[0];
          setActiveSessionId(nextSession.id);
          openSession(nextSession);
        } else {
          const nextSession = await createBackendSession(GENERAL_COLLECTION_ID);
          setSessions([nextSession]);
          setActiveSessionId(nextSession.id);
          setUploadResult(null);
        }
      }

      setError("");
    } catch (err) {
      setError(err.message || "Could not delete chat.");
    }
  };

  const removeCollectionFromUi = (collection) => {
    setCollections((current) =>
      current.filter((item) => item.collection_id !== collection.collection_id)
    );
    setSessions((current) =>
      current.map((session) => (
        session.collectionId === collection.collection_id
          ? { ...session, collectionId: GENERAL_COLLECTION_ID }
          : session
      ))
    );

    if (uploadResult?.collection_id === collection.collection_id) {
      setUploadResult(null);
    }

    setSelectedFiles([]);
  };

  const deleteCollection = async (collection, options = {}) => {
    const title = getCollectionTitle(collection);
    const shouldConfirm = options.confirm !== false;

    if (
      shouldConfirm &&
      !window.confirm(`Delete "${title}" from your documents? Chats will stay saved.`)
    ) {
      return false;
    }

    try {
      const response = await apiFetch(`/api/collections/${collection.collection_id}`, {
        method: "DELETE",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not delete document.");
      }

      removeCollectionFromUi(collection);
      setError("");
      return true;
    } catch (err) {
      setError(err.message || "Could not delete document.");

      if (options.throwOnError) {
        throw err;
      }

      return false;
    }
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) {
      setError("Please select at least one PDF first.");
      return;
    }

    setError("");
    setUploading(true);

    try {
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append("files", file);
      });

      const response = await apiFetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed.");
      }

      setUploadResult(data);
      setCollections((current) => [
        data,
        ...current.filter((collection) => collection.collection_id !== data.collection_id),
      ]);

      const sessionForUpload =
        sessions.find((session) => session.id === activeSessionId) ||
        activeSession ||
        sessions[0];

      if (!sessionForUpload) {
        throw new Error("Chat is still loading. Please try uploading again.");
      }

      const updatedSession = await updateBackendSessionCollection(
        sessionForUpload.id,
        data.collection_id
      );
      upsertSession(updatedSession);
      setActiveSessionId(updatedSession.id);

      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (err) {
      setError(err.message || "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    const trimmedQuestion = question.trim();

    if (!trimmedQuestion) {
      setError("Please enter a question.");
      return;
    }

    let session = activeSession;

    if (!session || session.collectionId !== collectionId) {
      try {
        session = await createBackendSession(collectionId);
        upsertSession(session);
        setActiveSessionId(session.id);
      } catch (err) {
        setError(err.message || "Could not create chat session.");
        return;
      }
    }

    const sessionId = session.id;
    setError("");
    setAsking(true);
    setQuestion("");
    updateSession(sessionId, (currentSession) => {
      const nextMessages = [
        ...currentSession.messages,
        {
          id: createMessageId(),
          role: "user",
          text: trimmedQuestion,
        },
      ];

      return {
        ...currentSession,
        title: currentSession.messages.length === 0
          ? truncateTitle(trimmedQuestion)
          : currentSession.title,
        messages: nextMessages,
      };
    });

    try {
      const response = await apiFetch("/api/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: trimmedQuestion,
          collection_id: activeCollection?.collection_id,
          session_id: sessionId,
        }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not generate answer.");
      }

      updateSession(sessionId, (currentSession) => ({
        ...currentSession,
        messages: [
          ...currentSession.messages,
          {
            id: createMessageId(),
            role: "assistant",
            text: data.answer,
            source: data.source,
            citations: data.citations || [],
          },
        ],
      }));
    } catch (err) {
      setError(err.message || "Could not generate answer.");
    } finally {
      setAsking(false);
    }
  };

  const signIn = (providerId = "huggingface") => {
    const path =
      providerId === "huggingface"
        ? "/api/auth/login"
        : `/api/auth/${providerId}/login`;
    window.location.href = `${API_BASE}${path}`;
  };

  const signOut = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      // The local UI should still clear even if the server session already expired.
    }

    if (currentUser) {
      localStorage.removeItem(getActiveSessionStorageKey(currentUser));
    }

    setAuth({
      authenticated: false,
      required: true,
      configured: true,
      user: null,
    });
    setCollections([]);
    setSessions([]);
    setUploadResult(null);
    setActiveSessionId("");
    setSelectedFiles([]);
    setQuestion("");
  };

  const totalFileSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  const activeDocumentNames = activeCollection?.documents?.map((document) => document.filename) || [];

  return (
    <div className="app">
      <div className="container">
        <header className="topbar">
          <div>
            <p className="eyebrow">Multi-document RAG</p>
            <h1>Docuery AI</h1>
          </div>
          <div className="topbar-actions">
            {isAuthenticated && (
              <>
                <button className="ghost-button" onClick={createNewChat} disabled={hydrating}>
                  New Chat
                </button>
                <button
                  className="ghost-button"
                  onClick={clearChat}
                  disabled={hydrating || !activeSession || messages.length === 0}
                >
                  Clear Chat
                </button>
              </>
            )}
            <button
              className="ghost-button"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            {isAuthenticated && currentUser && (
              <div className="user-pill">
                {currentUser.avatar_url && (
                  <img src={currentUser.avatar_url} alt="" />
                )}
                <span>{currentUser.username}</span>
              </div>
            )}
            {isAuthenticated && (
              <div className={`status-pill ${hasCollection ? "ready" : ""}`}>
                {hydrating
                  ? "Loading chats"
                  : uploading
                    ? "Indexing PDFs"
                    : hasCollection
                      ? "Documents ready"
                      : "General chat"}
              </div>
            )}
            {isAuthenticated && auth?.required && (
              <button className="ghost-button" onClick={signOut}>
                Sign Out
              </button>
            )}
          </div>
        </header>

        {error && <div className="error-box">{error}</div>}

        {!authIsReady ? (
          <section className="panel auth-panel">
            <div>
              <div className="loading-row centered">
                <div className="spinner"></div>
                <span>Loading private workspace...</span>
              </div>
            </div>
          </section>
        ) : !isAuthenticated ? (
          <section className="panel auth-panel">
            <div>
              <p className="eyebrow">Private Workspace</p>
              <h2>Sign in to use Docuery AI</h2>
              <p>
                Your uploaded PDFs, document collections, and chat history stay tied
                to your signed-in account.
              </p>
              {auth?.required && !auth?.configured && (
                <div className="error-box">
                  OAuth is not configured for this deployment yet.
                </div>
              )}
              <div className="auth-actions">
                {authProviders.map((provider) => (
                  <button
                    key={provider.id}
                    className="primary-button auth-button"
                    onClick={() => signIn(provider.id)}
                    disabled={auth?.required && !auth?.configured}
                  >
                    Sign in with {provider.label}
                  </button>
                ))}
              </div>
            </div>
          </section>
        ) : (
        <div className="workspace">
          <aside className="panel upload-panel">
            <div className="panel-header">
              <h2>Documents</h2>
            </div>

            <label
              className={`file-picker ${draggingFile ? "dragging" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDraggingFile(true);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                setDraggingFile(true);
              }}
              onDragLeave={() => setDraggingFile(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDraggingFile(false);
                selectFiles(event.dataTransfer.files);
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                multiple
                onChange={(event) => selectFiles(event.target.files)}
                disabled={hydrating || uploading}
              />
              <span className="file-picker-title">
                {selectedFiles.length > 0
                  ? `${selectedFiles.length} PDF${selectedFiles.length === 1 ? "" : "s"} selected`
                  : "Choose or Drop PDFs"}
              </span>
              <span className="file-picker-subtitle">
                {selectedFiles.length > 0
                  ? `${Math.max(totalFileSize / 1024 / 1024, 0.01).toFixed(2)} MB total`
                  : "Multiple PDFs supported"}
              </span>
            </label>

            {selectedFiles.length > 0 && (
              <div className="file-list">
                {selectedFiles.map((file) => (
                  <span key={`${file.name}-${file.size}`}>{file.name}</span>
                ))}
              </div>
            )}

            <button
              className="primary-button"
              onClick={handleUpload}
              disabled={hydrating || uploading || selectedFiles.length === 0}
            >
              {uploading ? "Indexing..." : "Upload and Index"}
            </button>

            {uploading && (
              <div className="upload-progress">
                <div className="spinner"></div>
                <div>
                  <strong>Preparing documents</strong>
                  <span>You can keep typing while this runs.</span>
                </div>
              </div>
            )}

            {activeCollection && (
              <div className="document-summary">
                <p className="summary-label">Selected Documents</p>
                <h3>
                  {activeCollection.total_files === 1
                    ? activeDocumentNames[0]
                    : `${activeCollection.total_files} PDFs`}
                </h3>
                <div className="metrics">
                  <span>
                    <strong>{activeCollection.total_pages_extracted || "-"}</strong>
                    Pages
                  </span>
                  <span>
                    <strong>{activeCollection.total_files || "-"}</strong>
                    Files
                  </span>
                </div>
                <div className="document-list">
                  {activeCollection.documents?.map((document) => (
                    <span key={document.document_id}>
                      {document.filename} · {document.total_pages_extracted} pages
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="collection-list">
              <div className="session-list-header">
                <p className="summary-label">Documents</p>
              </div>
              {collections.length === 0 && (
                <div className="empty-list">No PDFs uploaded yet.</div>
              )}
              {collections.map((collection) => {
                const collectionSessions = sessions.filter(
                  (session) => session.collectionId === collection.collection_id
                );

                return (
                  <div
                    key={collection.collection_id}
                    className={`collection-item ${
                      activeCollection?.collection_id === collection.collection_id ? "active" : ""
                    }`}
                    role="button"
                    tabIndex="0"
                    onClick={() => openCollection(collection)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openCollection(collection);
                      }
                    }}
                  >
                    <div className="collection-main">
                      <span>{getCollectionTitle(collection)}</span>
                      <small>
                        {formatCount(collection.total_files, "file")} ·{" "}
                        {formatCount(collectionSessions.length, "chat")}
                      </small>
                    </div>
                    <div className="session-actions">
                      <button
                        className="mini-button danger"
                        onClick={(event) => {
                          event.stopPropagation();
                          deleteCollection(collection);
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="session-list">
              <div className="session-list-header">
                <p className="summary-label">Chats</p>
                <button className="small-button" onClick={createNewChat} disabled={hydrating}>
                  New
                </button>
              </div>
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={`session-item ${session.id === activeSession?.id ? "active" : ""}`}
                  role="button"
                  tabIndex="0"
                  onClick={() => openSession(session)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      openSession(session);
                    }
                  }}
                >
                  <div className="session-main">
                    <span>{session.title}</span>
                    <small>
                      {formatCount(session.messages.length, "message")} ·{" "}
                      {getSessionContextLabel(session, collections)}
                    </small>
                  </div>
                  <div className="session-actions">
                    <button
                      className="mini-button"
                      onClick={(event) => {
                        event.stopPropagation();
                        renameChat(session);
                      }}
                    >
                      Rename
                    </button>
                    <button
                      className="mini-button danger"
                      onClick={(event) => {
                        event.stopPropagation();
                        deleteChat(session);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="prompt-bank">
              <p className="summary-label">Try</p>
              <div className="prompt-list">
                {promptSuggestions.map((prompt) => (
                  <button key={prompt} className="prompt-chip" onClick={() => usePrompt(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <main className="panel chat-panel">
            <div className="chat-header">
              <div>
                <h2>{activeSession?.title || "Ask Questions"}</h2>
                <p>
                  {hasCollection
                    ? activeDocumentNames.join(", ")
                    : "General chat without PDFs."}
                </p>
              </div>
              <div className="mini-stats">
                <span>{messages.filter((message) => message.role === "assistant").length}</span>
                {messages.filter((message) => message.role === "assistant").length === 1
                  ? "Answer"
                  : "Answers"}
              </div>
            </div>

            <div className="messages">
              {messages.length === 0 && (
                <div className="empty-state">
                  <h3>{hydrating ? "Loading chats..." : "Start a chat."}</h3>
                  <p>
                    {hydrating
                      ? "Saved chats and documents are loading from the backend."
                      : "Each chat keeps its own context. Select any chat on the left to continue it."}
                  </p>
                </div>
              )}

              {messages.map((message) => (
                <article key={message.id} className={`message ${message.role}`}>
                  <div className="message-label">
                    {message.role === "user" ? "You" : "Assistant"}
                  </div>
                  <div className="message-bubble">{message.text}</div>

                  {message.role === "assistant" && message.source && (
                    <div className={`source-badge ${message.source}`}>
                      {message.source === "general"
                        ? "General answer"
                        : message.source === "no_match"
                          ? "No document match"
                          : "Document answer"}
                    </div>
                  )}

                  {message.citations?.length > 0 && (
                    <div className="page-citations">
                      {message.citations.map((citation) => (
                        <span key={`${citation.filename}-${citation.page}`}>
                          {citation.filename}, p. {citation.page}
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              ))}

              {asking && (
                <div className="loading-row answer-loading">
                  <div className="spinner"></div>
                  <span>Thinking...</span>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <form
              className="ask-form"
              onSubmit={(event) => {
                event.preventDefault();
                handleAsk();
              }}
            >
              <textarea
                ref={questionRef}
                rows="3"
                placeholder={
                  hasCollection
                    ? "Ask across the uploaded PDFs or anything general..."
                    : "Ask a general question..."
                }
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    handleAsk();
                  }
                }}
                disabled={hydrating || asking}
              />
              <button className="primary-button" disabled={hydrating || asking}>
                {asking ? "Answering..." : "Ask"}
              </button>
            </form>
          </main>
        </div>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
