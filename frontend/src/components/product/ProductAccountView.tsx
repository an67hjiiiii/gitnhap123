import type { ProductCurrentUser } from "./ProductHeader";
import "./product-account.css";

interface ProductAccountViewProps {
  view: "account" | "settings";
  currentUser: ProductCurrentUser;
}

export function ProductAccountView({ view, currentUser }: ProductAccountViewProps) {
  if (view === "settings") {
    return (
      <main className="product-account-page" aria-labelledby="product-settings-title">
        <div className="product-account-page-heading">
          <h1 id="product-settings-title">Cài đặt</h1>
        </div>
        <section className="product-account-empty" role="status">
          <h2>Chưa có cài đặt khả dụng</h2>
          <p>Chưa có tùy chọn cài đặt nào được cung cấp.</p>
        </section>
      </main>
    );
  }

  const fields = [
    { label: "Tên hiển thị", value: currentUser.display_name },
    { label: "Email", value: currentUser.email },
    { label: "Tên người dùng", value: currentUser.username },
  ].filter((field) => typeof field.value === "string" && field.value.trim());

  return (
    <main className="product-account-page" aria-labelledby="product-account-title">
      <div className="product-account-page-heading">
        <h1 id="product-account-title">Tài khoản</h1>
      </div>
      {fields.length > 0 ? (
        <dl className="product-account-fields">
          {fields.map((field) => (
            <div className="product-account-field" key={field.label}>
              <dt>{field.label}</dt>
              <dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <section className="product-account-empty" role="status">
          <h2>Thông tin chưa có</h2>
          <p>Chưa có thông tin tài khoản nào để hiển thị.</p>
        </section>
      )}
    </main>
  );
}
