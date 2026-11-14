import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useResearchApp } from "./app/useResearchApp";
import { ChatPanel } from "./components/ChatPanel";
import { Inspector } from "./components/Inspector";
import { Sidebar } from "./components/Sidebar";
import { StatusBadge } from "./components/StatusBadge";
import { RegisterForm } from "./components/RegisterForm";
import { LoginForm } from "./components/LoginForm";
import { ProductSidebar } from "./components/product/ProductSidebar";
import type { ProductPage, ProductCurrentUser } from "./components/product/ProductHeader";
import { ProductHomeView } from "./components/product/ProductHomeView";
import { ProductDocumentsView } from "./components/product/ProductDocumentsView";
import { ProductRecentView } from "./components/product/ProductRecentView";
import { ProductAccountView } from "./components/product/ProductAccountView";
import { ProductSourcesPanel } from "./components/product/ProductSourcesPanel";
import "./components/product/product-shell.css";
import { ProductAuthPage } from "./components/product/ProductAuthPage";
import { api, ApiError } from "./lib/api";
import { researchModeFromFlag } from "./app/chatModel.mjs";
import { XIcon } from "@phosphor-icons/react";
import type { RunRecord } from "./types/api";

const researchMode = researchModeFromFlag(import.meta.env.VITE_RESEARCH_MODE);
const PRODUCT_AUTH_SESSION_KEY = "cap1.product.authenticated-session";
const PRODUCT_SESSION_EXPIRED_MESSAGE = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.";

function hasPreviousProductSession(): boolean {
  try {
    return window.sessionStorage.getItem(PRODUCT_AUTH_SESSION_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberProductSession(): void {
  try {
    window.sessionStorage.setItem(PRODUCT_AUTH_SESSION_KEY, "1");
  } catch {
    // Session storage can be unavailable in restricted browser contexts.
  }
}

function forgetProductSession(): void {
  try {
    window.sessionStorage.removeItem(PRODUCT_AUTH_SESSION_KEY);
  } catch {
    // Session storage can be unavailable in restricted browser contexts.
  }
}

export function App() {
  const research = useResearchApp({ researchMode });
  const [condition, setCondition] = useState("A");
  const [provider, setProvider] = useState("fake");
  const [authScreen, setAuthScreen] = useState<"register" | "login" | null>(null);
  const [registrationNotice, setRegistrationNotice] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [productPage, setProductPage] = useState<ProductPage | "conversation" | "account" | "settings">("home");
  const [productSourcesOpen, setProductSourcesOpen] = useState(false);
  const [productSourcesRun, setProductSourcesRun] = useState<RunRecord | null>(null);
  const sourceActionRef = useRef<HTMLButtonElement | null>(null);
  const allowedConditions = useMemo(
    () => research.health?.allowed_conditions?.length ? research.health.allowed_conditions : ["A"],
    [research.health],
  );
  const productCurrentUser: ProductCurrentUser = {
    email: research.currentUser?.email,
    username: research.currentUser?.username,
  };
  const productHeaderUser: ProductCurrentUser = {
    display_name: research.currentUser?.username,
    email: research.currentUser?.email,
  };
  const hasReadySources = research.sources.some((source) =>
    (source.status ?? source.index_status ?? "").trim().toUpperCase() === "READY",
  );
  const showProductHome = productPage === "home"
    || (productPage === "conversation" && !research.activeConversationId && !research.pendingQuestion);

  useEffect(() => {
    if (!researchMode && research.isAuthenticated) rememberProductSession();
  }, [research.isAuthenticated]);

  const closeProductSources = useCallback(() => {
    setProductSourcesOpen(false);
    window.requestAnimationFrame(() => sourceActionRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!productSourcesOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeProductSources();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [closeProductSources, productSourcesOpen]);

  async function submitQuestion(message: string) {
    await research.submitQuestion(message, condition, provider);
  }

  async function signOut() {
    setLogoutError(null);
    if (!researchMode) forgetProductSession();
    try {
      await api.logout();
      window.location.reload();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        window.location.reload();
        return;
      }
      setLogoutError("Không thể đăng xuất lúc này. Vui lòng thử lại.");
    }
  }

  return (
    <div className={`app-shell${!researchMode ? " product-app-shell" : ""}`}>
      {research.isAuthenticated ? (
        researchMode ? (
        <>
          <Sidebar
            researchMode={researchMode}
            history={research.history}
            conversations={research.conversations}
            sources={research.sources}
            activeRunId={research.activeRun?.run_id}
            activeConversationId={research.activeConversationId}
            onNewRun={research.startNewRun}
            onSelectRun={(runId) => void research.selectRun(runId)}
            onNewConversation={research.startNewConversation}
            onSelectConversation={(conversationId) => void research.selectConversation(conversationId)}
          />
          <div className="workspace-column">
            <header className="topbar">
              <div className="topbar-context">
                <span className="topbar-title">{researchMode ? "Research chat" : "CAP1_AI"}</span>
                <span className="topbar-separator" aria-hidden="true">/</span>
                <span className="topbar-subtitle">{research.currentUser?.email ?? research.currentUser?.username ?? "Private workspace"}</span>
              </div>
              <div className="topbar-controls">
                <button type="button" className="button-secondary" onClick={() => void signOut()}>
                  Sign out
                </button>
                {researchMode && (
                  <>
                    <label className="select-control">
                      <span>Condition</span>
                      <select value={condition} onChange={(event) => setCondition(event.target.value)} aria-label="Run condition">
                        {allowedConditions.map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </label>
                    <label className="select-control">
                      <span>Provider</span>
                      <select value={provider} onChange={(event) => setProvider(event.target.value)} aria-label="Run provider">
                        <option value="fake">Fake wiring</option>
                        <option value="ollama">Local Ollama</option>
                      </select>
                    </label>
                  </>
                )}
                <StatusBadge status={research.isBooting ? "CONNECTING" : research.health?.ok ? "READY" : "OFFLINE"} compact />
              </div>
            </header>

            {research.error && (
              <div className="global-alert" role="alert">
                <span>{research.error}</span>
                <button type="button" onClick={research.dismissError} aria-label="Dismiss notification">×</button>
              </div>
            )}
            {logoutError && <div className="global-alert" role="alert">{logoutError}</div>}

            <ChatPanel
              researchMode={researchMode}
              run={research.activeRun}
              conversation={research.activeConversation}
              conversationRuns={research.conversationRuns}
              activeConversationId={research.activeConversationId}
              onSelectRun={(runId) => void research.selectRun(runId)}
              pendingQuestion={research.pendingQuestion}
              condition={condition}
              provider={provider}
              isRunning={research.isRunning}
              isImporting={research.isImporting}
              sourceNotice={research.sourceNotice}
              onSubmit={submitQuestion}
              onImport={async (file) => { await research.importSource(file); }}
            />
          </div>
          <Inspector researchMode={researchMode} run={research.activeRun} sources={research.sources} activeTab={research.activeTab} onTabChange={research.setActiveTab} />
        </>
        ) : (
          <>
            <ProductSidebar
              activePage={productPage === "home" || productPage === "documents" || productPage === "recent" ? productPage : null}
              activeConversationId={research.activeConversationId}
              conversations={research.conversations}
              onNavigate={(page) => {
                setProductSourcesOpen(false);
                setProductPage(page);
              }}
              currentUser={productHeaderUser}
              onSelectConversation={(conversationId) => {
                setProductPage("conversation");
                void research.selectConversation(conversationId);
              }}
              onNewConversation={() => {
                research.startNewConversation();
                setProductSourcesOpen(false);
                setProductPage("conversation");
              }}
              onOpenAccount={() => setProductPage("account")}
              onOpenSettings={() => setProductPage("settings")}
              onSignOut={() => void signOut()}
            />
            <div className="product-app-content">
              <div className="product-main-content">
                {(research.error || logoutError) && (
                  <div className="global-alert" role="alert">
                    <span>{research.error ?? logoutError}</span>
                    <button type="button" onClick={() => { research.dismissError(); setLogoutError(null); }} aria-label="Đóng thông báo" title="Đóng">
                      <XIcon size={18} weight="regular" aria-hidden="true" />
                    </button>
                  </div>
                )}
                {showProductHome && (
                  <ProductHomeView
                    hasReadySources={hasReadySources}
                    isRunning={research.isRunning}
                    isImporting={research.isImporting}
                    sourceNotice={research.sourceNotice}
                    onImport={(file) => research.importSource(file)}
                    onSubmit={async (message) => {
                      research.startNewConversation();
                      setProductPage("conversation");
                      await research.submitQuestion(message, "A", "local");
                    }}
                  />
                )}
                {productPage === "documents" && (
                  <ProductDocumentsView
                    sources={research.sources}
                    isLoading={research.isBooting}
                    isImporting={research.isImporting}
                    error={research.error}
                    notice={research.sourceNotice}
                    onImport={async (file) => { await research.importSource(file); }}
                  />
                )}
                {productPage === "recent" && (
                  <ProductRecentView
                    conversations={research.conversations}
                    isLoading={research.isBooting}
                    onOpenConversation={(conversationId) => {
                      setProductPage("conversation");
                      void research.selectConversation(conversationId);
                    }}
                  />
                )}
                {(productPage === "account" || productPage === "settings") && (
                  <ProductAccountView view={productPage} currentUser={productCurrentUser} />
                )}
                {productPage === "conversation" && !showProductHome && (
                  <ChatPanel
                    researchMode={false}
                    run={research.activeRun}
                    conversation={research.activeConversation}
                    conversationRuns={research.conversationRuns}
                    activeConversationId={research.activeConversationId}
                    onSelectRun={(runId) => void research.selectRun(runId)}
                    onOpenSources={(run, trigger) => {
                      sourceActionRef.current = trigger;
                      setProductSourcesRun(run);
                      setProductSourcesOpen(true);
                    }}
                    pendingQuestion={research.pendingQuestion}
                    condition="A"
                    provider="local"
                    isRunning={research.isRunning}
                    isImporting={research.isImporting}
                    sourceNotice={research.sourceNotice}
                    onSubmit={async (message) => { await research.submitQuestion(message, "A", "local"); }}
                    onImport={(file) => research.importSource(file)}
                  />
                )}
              </div>
              {productSourcesOpen && <button className="product-source-panel-backdrop" type="button" aria-label="Đóng nguồn tham khảo" onClick={closeProductSources} />}
              {productSourcesOpen && productSourcesRun && (
                <ProductSourcesPanel run={productSourcesRun} onClose={closeProductSources} />
              )}
            </div>
          </>
        )
      ) : researchMode ? (
        <main className="auth-required" aria-busy={research.isBooting}>
          <section className="auth-required-panel" aria-labelledby="auth-required-title">
            <p className="eyebrow">Local workspace</p>
            <h1 id="auth-required-title">{research.isBooting ? "Đang khôi phục phiên đăng nhập…" : "Đăng nhập để tiếp tục"}</h1>
            <p className="dialog-description">
              {research.isBooting
                ? "We are checking your local session before opening private sources and runs."
                : "Your private knowledge and conversations are available after sign in."}
            </p>
            {research.error && <p role="alert" className="form-error">{research.error}</p>}
            {!research.isBooting && (
              <div className="form-actions">
                <button type="button" className="button-secondary" onClick={() => setAuthScreen("register")}>Create account</button>
                <button type="button" className="button-primary" onClick={() => setAuthScreen("login")}>Sign in</button>
              </div>
            )}
          </section>
        </main>
      ) : (
        <ProductAuthPage
          screen={authScreen ?? "login"}
          isBooting={research.isBooting}
          sessionExpired={hasPreviousProductSession() && research.error === PRODUCT_SESSION_EXPIRED_MESSAGE}
          errorNotice={research.error === PRODUCT_SESSION_EXPIRED_MESSAGE ? null : research.error}
          registrationNotice={registrationNotice}
          onScreenChange={(screen) => {
            setRegistrationNotice(null);
            setAuthScreen(screen);
          }}
          onRegistered={(registeredEmail) => {
            setRegistrationNotice(registeredEmail);
            setAuthScreen("login");
          }}
          onSignedIn={() => {
            rememberProductSession();
            window.location.reload();
          }}
        />
      )}
      {researchMode && authScreen && (
        <div className="dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setAuthScreen(null);
        }}>
          <section className="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title">
            <button type="button" className="dialog-close" aria-label={researchMode ? "Close sign in" : "Đóng hộp thoại"} title={researchMode ? "Close" : "Đóng"} onClick={() => setAuthScreen(null)}>
              {researchMode ? "×" : <XIcon size={20} weight="regular" aria-hidden="true" />}
            </button>
            {researchMode && <p className="eyebrow">Local workspace</p>}
            <h1 id="auth-title">{researchMode
              ? authScreen === "register" ? "Tạo tài khoản" : "Đăng nhập"
              : authScreen === "register" ? "Tạo tài khoản" : "Đăng nhập"}</h1>
            {researchMode && <p className="dialog-description">Access your private sources and conversations.</p>}
            {authScreen === "register" ? (
              <>
                {registrationNotice && (
                  <div className="registration-success" role="status">
                    {researchMode
                      ? `Account created for ${registrationNotice}. Sign in to continue.`
                      : `Tài khoản ${registrationNotice} đã được tạo. Hãy đăng nhập để tiếp tục.`}
                  </div>
                )}
                <RegisterForm
                  productMode={!researchMode}
                  onCancel={() => setAuthScreen(null)}
                  onRegistered={(registeredEmail) => {
                    setRegistrationNotice(registeredEmail);
                    setAuthScreen("login");
                  }}
                />
              </>
            ) : (
              <LoginForm
                productMode={!researchMode}
                onCancel={() => setAuthScreen(null)}
                onCreateAccount={() => setAuthScreen("register")}
                onSignedIn={() => window.location.reload()}
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
