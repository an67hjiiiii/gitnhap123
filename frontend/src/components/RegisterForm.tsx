import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";

interface RegisterFormProps {
  productMode?: boolean;
  onCancel?: () => void;
  onRegistered: (email: string) => void;
}

export function RegisterForm({ productMode = false, onCancel, onRegistered }: RegisterFormProps) {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (productMode && password !== confirmPassword) {
      setError("Mật khẩu xác nhận chưa khớp.");
      return;
    }
    setIsSubmitting(true);
    try {
      await api.register({
        email: email.trim(),
        username: username.trim() || undefined,
        display_name: displayName.trim() || undefined,
        password,
      });
      onRegistered(email.trim());
    } catch (cause) {
      setError(productMode
        ? cause instanceof ApiError && cause.status === 409
          ? "Email hoặc tên người dùng đã được sử dụng."
          : "Chưa thể tạo tài khoản lúc này. Vui lòng thử lại."
        : cause instanceof ApiError ? cause.message : "Could not create the account. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (productMode) {
    return (
      <form className="register-form product-auth-form" onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
        <div className="product-auth-field">
          <label htmlFor="register-email">Email</label>
          <input
            id="register-email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </div>

        <div className="product-auth-profile-fields">
          <div className="product-auth-field">
            <label htmlFor="register-username">Tên người dùng <span>(không bắt buộc)</span></label>
            <input
              id="register-username"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="product-auth-field">
            <label htmlFor="register-name">Họ tên <span>(không bắt buộc)</span></label>
            <input
              id="register-name"
              name="display_name"
              autoComplete="name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>
        </div>

        <div className="product-auth-field">
          <label htmlFor="register-password">Mật khẩu</label>
          <input
            id="register-password"
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <p className="form-hint">Mật khẩu cần có ít nhất 8 ký tự.</p>
        </div>

        <div className="product-auth-field">
          <label htmlFor="register-confirm-password">Xác nhận mật khẩu</label>
          <input
            id="register-confirm-password"
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
          />
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}

        <button className="button-primary product-auth-submit" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Đang tạo tài khoản…" : "Tạo tài khoản"}
        </button>
        <p className="product-auth-switch">
          Đã có tài khoản? <button type="button" onClick={onCancel}>Đăng nhập</button>
        </p>
      </form>
    );
  }

  return (
    <form className="register-form" onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
      <label htmlFor="register-email">Email</label>
      <input
        id="register-email"
        name="email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        required
      />

      <label htmlFor="register-username">Username <span>(optional)</span></label>
      <input
        id="register-username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />

      <label htmlFor="register-name">Display name <span>(optional)</span></label>
      <input
        id="register-name"
        name="display_name"
        autoComplete="name"
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
      />

      <label htmlFor="register-password">Password</label>
      <input
        id="register-password"
        name="password"
        type="password"
        autoComplete="new-password"
        minLength={8}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        required
      />
      <p className="form-hint">Use at least 8 characters.</p>

      {error && <p className="form-error" role="alert">{error}</p>}

      <div className="form-actions">
        <button type="button" className="button-secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </button>
        <button type="submit" className="button-primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating account…" : "Create account"}
        </button>
      </div>
    </form>
  );
}