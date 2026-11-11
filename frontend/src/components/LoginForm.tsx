import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";

interface LoginFormProps {
  productMode?: boolean;
  onCancel?: () => void;
  onCreateAccount: () => void;
  onSignedIn: () => void;
}

export function LoginForm({ productMode = false, onCancel, onCreateAccount, onSignedIn }: LoginFormProps) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await api.login({ identifier: identifier.trim(), password });
      onSignedIn();
    } catch (cause) {
      setError(productMode
        ? cause instanceof ApiError && cause.status === 401
          ? "Email hoặc mật khẩu chưa đúng. Hãy kiểm tra lại thông tin đăng nhập."
          : "Chưa thể đăng nhập lúc này. Vui lòng thử lại."
        : cause instanceof ApiError ? cause.message : "Could not sign in. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (productMode) {
    return (
      <form className="register-form product-auth-form" onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
        <div className="product-auth-field">
          <label htmlFor="login-identifier">Email</label>
          <input
            id="login-identifier"
            name="identifier"
            type="email"
            autoComplete="email"
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            required
          />
        </div>

        <div className="product-auth-field">
          <label htmlFor="login-password">Mật khẩu</label>
          <div className="product-auth-password-field">
            <input
              id="login-password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <button
              className="product-auth-password-toggle"
              type="button"
              aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((visible) => !visible)}
            >
              {showPassword ? "Ẩn" : "Hiện"}
            </button>
          </div>
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}

        <button className="button-primary product-auth-submit" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
        <p className="product-auth-switch">
          Chưa có tài khoản? <button type="button" onClick={onCreateAccount}>Đăng ký</button>
        </p>
      </form>
    );
  }

  return (
    <form className="register-form" onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
      <label htmlFor="login-identifier">Email or username</label>
      <input
        id="login-identifier"
        name="identifier"
        autoComplete="username"
        value={identifier}
        onChange={(event) => setIdentifier(event.target.value)}
        required
      />

      <label htmlFor="login-password">Password</label>
      <input
        id="login-password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        required
      />

      {error && <p className="form-error" role="alert">{error}</p>}

      <div className="form-actions">
        <button type="button" className="button-secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </button>
        <button type="submit" className="button-primary" disabled={isSubmitting}>
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </div>
      <p className="form-hint">
        New here? <button type="button" className="text-button" onClick={onCreateAccount}>Create an account</button>
      </p>
    </form>
  );
}