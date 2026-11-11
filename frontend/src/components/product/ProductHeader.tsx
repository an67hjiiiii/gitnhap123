import { CaretDownIcon, PlusIcon } from "@phosphor-icons/react";
import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent } from "react";
import "./product-header.css";

export type ProductPage = "home" | "documents" | "recent";

interface ProductHeaderProps {
  activePage: ProductPage | null;
  onNavigate: (page: ProductPage) => void;
  onNewConversation: () => void;
  currentUser: ProductCurrentUser;
  onOpenAccount: () => void;
  onOpenSettings: () => void;
  onSignOut: () => void;
}

export interface ProductCurrentUser {
  display_name?: string | null;
  email?: string | null;
  username?: string | null;
}

const navigation = [
  { id: "home", label: "Trang chủ" },
  { id: "documents", label: "Tài liệu" },
  { id: "recent", label: "Gần đây" },
] as const;

export function ProductHeader({
  activePage,
  onNavigate,
  onNewConversation,
  currentUser,
  onOpenAccount,
  onOpenSettings,
  onSignOut,
}: ProductHeaderProps) {
  const accountLabel = currentUser.display_name?.trim()
    || currentUser.email?.trim()
    || currentUser.username?.trim()
    || "Tài khoản";
  const accountMenuRef = useRef<HTMLDetailsElement>(null);
  const displayNameParts = currentUser.display_name?.trim().split(/\s+/).filter(Boolean) ?? [];
  const initials = displayNameParts.length > 1
    ? `${displayNameParts[0][0]}${displayNameParts[displayNameParts.length - 1][0]}`.toLocaleUpperCase()
    : (displayNameParts[0]?.slice(0, 1) || currentUser.email?.trim().slice(0, 1) || currentUser.username?.trim().slice(0, 1) || "?").toLocaleUpperCase();

  useEffect(() => {
    function closeOnOutsidePointer(event: PointerEvent) {
      const menu = accountMenuRef.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
    }

    function closeOnEscape(event: KeyboardEvent) {
      const menu = accountMenuRef.current;
      if (event.key === "Escape" && menu?.open) {
        menu.open = false;
        menu.querySelector("summary")?.focus();
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  function closeAndRun(event: MouseEvent<HTMLButtonElement>, action: () => void) {
    const details = event.currentTarget.closest("details");
    if (details) details.open = false;
    action();
  }

  function navigateMenu(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role='menuitem']"));
    if (items.length === 0) return;
    event.preventDefault();
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : event.key === "ArrowDown"
          ? (currentIndex + 1 + items.length) % items.length
          : (currentIndex - 1 + items.length) % items.length;
    items[nextIndex].focus();
  }

  return (
    <header className="product-header">
      <a className="product-header-brand" href="#home" onClick={(event) => {
        event.preventDefault();
        onNavigate("home");
      }} aria-label="CAP1 AI, về trang chủ">
        <span>CAP1 AI</span>
      </a>

      <nav className="product-header-nav" aria-label="Điều hướng chính">
        {navigation.map(({ id, label }) => (
          <button
            className={`product-header-nav-item${activePage === id ? " is-active" : ""}`}
            type="button"
            key={id}
            aria-current={activePage === id ? "page" : undefined}
            onClick={() => onNavigate(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="product-header-actions">
        <button
          className="product-header-new"
          type="button"
          onClick={onNewConversation}
          aria-label="Tạo cuộc trò chuyện mới"
          title="Tạo cuộc trò chuyện mới"
        >
          <PlusIcon size={20} weight="regular" aria-hidden="true" />
        </button>
        <details className="product-account-menu" ref={accountMenuRef}>
          <summary className="product-header-account" aria-label="Tài khoản" title="Tài khoản">
            <span className="product-account-avatar" aria-hidden="true">{initials}</span>
            <CaretDownIcon size={15} aria-hidden="true" />
          </summary>
          <div className="product-account-popover" role="menu" aria-label="Tùy chọn tài khoản" onKeyDown={navigateMenu}>
            <div className="product-account-identity" role="group" aria-label="Thông tin tài khoản">
              <strong>{accountLabel}</strong>
              {currentUser.email?.trim() && currentUser.email.trim() !== accountLabel && <span>{currentUser.email}</span>}
              {currentUser.username?.trim() && currentUser.username.trim() !== accountLabel && <span>@{currentUser.username}</span>}
            </div>
            <div className="product-account-divider" role="separator" />
            <button type="button" role="menuitem" onClick={(event) => closeAndRun(event, onOpenAccount)}>Tài khoản</button>
            <button type="button" role="menuitem" onClick={(event) => closeAndRun(event, onOpenSettings)}>Cài đặt</button>
            <div className="product-account-divider" role="separator" />
            <button className="product-account-signout" type="button" role="menuitem" onClick={(event) => closeAndRun(event, onSignOut)}>Đăng xuất</button>
          </div>
        </details>
      </div>
    </header>
  );
}
