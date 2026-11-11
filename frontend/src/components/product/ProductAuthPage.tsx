import { useEffect, useRef } from "react";
import { LoginForm } from "../LoginForm";
import { RegisterForm } from "../RegisterForm";
import "./product-auth.css";

export type ProductAuthScreen = "login" | "register";

interface ProductAuthPageProps {
  screen: ProductAuthScreen;
  isBooting: boolean;
  sessionExpired: boolean;
  errorNotice: string | null;
  registrationNotice: string | null;
  onScreenChange: (screen: ProductAuthScreen) => void;
  onRegistered: (email: string) => void;
  onSignedIn: () => void;
}

export function ProductAuthPage({
  screen,
  isBooting,
  sessionExpired,
  errorNotice,
  registrationNotice,
  onScreenChange,
  onRegistered,
  onSignedIn,
}: ProductAuthPageProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [screen]);

  const isLogin = screen === "login";

  return (
    <main className="product-auth-page" aria-busy={isBooting}>
      <section className="product-auth-card" aria-labelledby="product-auth-heading">
        <div className="product-auth-brand" aria-label="CAP1 AI">
          <span className="product-auth-brand-name">CAP1 AI</span>
        </div>

        <h1 id="product-auth-heading" ref={headingRef} tabIndex={-1}>
          {isLogin ? "Chào mừng trở lại" : "Tạo tài khoản"}
        </h1>
        <p className="product-auth-subtitle">
          {isLogin ? "Đăng nhập để tiếp tục" : "Tạo tài khoản mới để tiếp tục"}
        </p>

        {sessionExpired && (
          <p className="product-auth-notice" role="status">
            Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.
          </p>
        )}
        {registrationNotice && isLogin && (
          <p className="product-auth-notice product-auth-success" role="status">
            Tài khoản {registrationNotice} đã được tạo. Hãy đăng nhập để tiếp tục.
          </p>
        )}
        {errorNotice && (
          <p className="product-auth-notice product-auth-error" role="alert">
            {errorNotice}
          </p>
        )}

        {isLogin ? (
          <LoginForm
            productMode
            onCancel={() => undefined}
            onCreateAccount={() => onScreenChange("register")}
            onSignedIn={onSignedIn}
          />
        ) : (
          <RegisterForm
            productMode
            onCancel={() => onScreenChange("login")}
            onRegistered={onRegistered}
          />
        )}
      </section>
    </main>
  );
}