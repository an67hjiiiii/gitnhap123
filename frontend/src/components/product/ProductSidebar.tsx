import {
  ClockCounterClockwiseIcon,
  FileTextIcon,
  GearSixIcon,
  HouseIcon,
  NotePencilIcon,
  SidebarSimpleIcon,
  SignOutIcon,
  UserCircleIcon,
  CaretDownIcon,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { conversationSidebarItems, displayConversationTitle } from "../../app/chatModel.mjs";
import type { ConversationSummary } from "../../types/api";
import type { ProductCurrentUser, ProductPage } from "./ProductHeader";
import "./product-sidebar.css";

interface ProductSidebarProps {
  activePage: ProductPage | null;
  activeConversationId: string | null;
  conversations: ConversationSummary[];
  currentUser: ProductCurrentUser;
  onNavigate: (page: ProductPage) => void;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onOpenAccount: () => void;
  onOpenSettings: () => void;
  onSignOut: () => void;
}

const navigation = [
  { id: "home", label: "Trang chủ", Icon: HouseIcon },
  { id: "documents", label: "Tài liệu", Icon: FileTextIcon },
  { id: "recent", label: "Gần đây", Icon: ClockCounterClockwiseIcon },
] as const;

function conversationTimestamp(conversation: ConversationSummary): number | null {
  for (const value of [conversation.updated_at, conversation.created_at]) {
    if (!value) continue;
    const timestamp = Date.parse(value);
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return null;
}

function accountName(user: ProductCurrentUser): string {
  return user.display_name?.trim() || user.email?.trim() || user.username?.trim() || "Tài khoản";
}

function accountInitials(user: ProductCurrentUser): string {
  const words = user.display_name?.trim().split(/\s+/).filter(Boolean) ?? [];
  if (words.length > 1) return `${words[0][0]}${words[words.length - 1][0]}`.toLocaleUpperCase();
  return (words[0]?.slice(0, 1) || user.email?.trim().slice(0, 1) || user.username?.trim().slice(0, 1) || "?").toLocaleUpperCase();
}

function Cap1BrandMark() {
  return (
    <span className="product-sidebar-logo" aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        <path d="M5 8.2 12 4l7 4.2v7.7L12 20l-7-4.1z" />
        <path d="M5 8.2 12 12l7-3.8M12 12v8" />
      </svg>
    </span>
  );
}

export function ProductSidebar({
  activePage,
  activeConversationId,
  conversations,
  currentUser,
  onNavigate,
  onSelectConversation,
  onNewConversation,
  onOpenAccount,
  onOpenSettings,
  onSignOut,
}: ProductSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const accountMenuRef = useRef<HTMLDetailsElement>(null);
  const displayName = accountName(currentUser);
  const initials = accountInitials(currentUser);
  const recentConversations = conversationSidebarItems(conversations)
    .map((conversation, index) => ({ conversation, index, timestamp: conversationTimestamp(conversation) }))
    .sort((left, right) => {
      if (left.timestamp !== null && right.timestamp !== null) return right.timestamp - left.timestamp || left.index - right.index;
      if (left.timestamp !== null) return -1;
      if (right.timestamp !== null) return 1;
      return left.index - right.index;
    })
    .slice(0, 6);

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

  return (
    <aside className="product-sidebar" data-collapsed={collapsed} aria-label="Điều hướng chính">
      <div className="product-sidebar-top">
        {collapsed ? (
          <button
            className="product-sidebar-collapsed-trigger"
            type="button"
            onClick={() => setCollapsed(false)}
            aria-label="Mở thanh bên"
            title="Mở thanh bên"
            aria-expanded={false}
          >
            <Cap1BrandMark />
            <SidebarSimpleIcon className="product-sidebar-collapsed-icon" size={20} aria-hidden="true" />
          </button>
        ) : (
          <>
            <div className="product-sidebar-brand" role="img" aria-label="CAP1 AI">
              <Cap1BrandMark />
              <span className="product-sidebar-brand-name">CAP1 AI</span>
            </div>
            <button
              className="product-sidebar-toggle"
              type="button"
              onClick={() => setCollapsed(true)}
              aria-label="Thu gọn thanh bên"
              title="Thu gọn thanh bên"
              aria-expanded={true}
            >
              <SidebarSimpleIcon size={19} aria-hidden="true" />
            </button>
          </>
        )}
      </div>

      <button
        className="product-sidebar-new"
        type="button"
        onClick={onNewConversation}
        aria-label="Trò chuyện mới"
        title={collapsed ? "Trò chuyện mới" : undefined}
      >
        <NotePencilIcon size={18} aria-hidden="true" />
        {!collapsed && <span>Trò chuyện mới</span>}
      </button>

      <nav className="product-sidebar-nav" aria-label="Khu vực">
        {navigation.map(({ id, label, Icon }) => (
          <button
            className={`product-sidebar-nav-item${activePage === id ? " is-active" : ""}`}
            type="button"
            key={id}
            onClick={() => onNavigate(id)}
            aria-current={activePage === id ? "page" : undefined}
            aria-label={collapsed ? label : undefined}
            title={collapsed ? label : undefined}
          >
            <Icon size={19} weight={activePage === id ? "fill" : "regular"} aria-hidden="true" />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}
      </nav>

      {!collapsed && (
        <section className="product-sidebar-recent" aria-labelledby="product-sidebar-recent-title">
          <h2 id="product-sidebar-recent-title">HỘI THOẠI GẦN ĐÂY</h2>
          <div className="product-sidebar-recent-list" aria-label="Cuộc trò chuyện gần đây">
            {recentConversations.map(({ conversation }) => (
              <button
                className={`product-sidebar-conversation${conversation.conversation_id === activeConversationId ? " is-active" : ""}`}
                key={conversation.conversation_id}
                type="button"
                onClick={() => onSelectConversation(conversation.conversation_id)}
                aria-current={conversation.conversation_id === activeConversationId ? "true" : undefined}
                title={displayConversationTitle(conversation)}
              >
                {displayConversationTitle(conversation)}
              </button>
            ))}
            {recentConversations.length === 0 && <p className="product-sidebar-empty">Chưa có cuộc trò chuyện</p>}
          </div>
        </section>
      )}

      <div className="product-sidebar-account-wrap">
        <details className="product-sidebar-account-menu" ref={accountMenuRef}>
          <summary className="product-sidebar-account" aria-label="Tài khoản" title={collapsed ? "Tài khoản" : undefined}>
            <span className="product-sidebar-avatar" aria-hidden="true">{initials}</span>
            {!collapsed && <span className="product-sidebar-account-name">{displayName}</span>}
            {!collapsed && <CaretDownIcon className="product-sidebar-account-chevron" size={15} aria-hidden="true" />}
          </summary>
          <div className="product-sidebar-account-popover" aria-label="Tùy chọn tài khoản">
            <div className="product-sidebar-account-identity">
              <span className="product-sidebar-avatar product-sidebar-account-popover-avatar" aria-hidden="true">{initials}</span>
              <div className="product-sidebar-account-identity-copy">
                <strong>{displayName}</strong>
                {currentUser.email?.trim() && currentUser.email.trim() !== displayName && <span>{currentUser.email}</span>}
                {currentUser.username?.trim() && currentUser.username.trim() !== displayName && <span>@{currentUser.username}</span>}
              </div>
            </div>
            <div className="product-sidebar-divider" />
            <button type="button" onClick={(event) => closeAndRun(event, onOpenAccount)}><UserCircleIcon size={18} aria-hidden="true" /><span>Tài khoản</span></button>
            <button type="button" onClick={(event) => closeAndRun(event, onOpenSettings)}><GearSixIcon size={18} aria-hidden="true" /><span>Cài đặt</span></button>
            <div className="product-sidebar-divider" />
            <button className="product-sidebar-signout" type="button" onClick={(event) => closeAndRun(event, onSignOut)}><SignOutIcon size={18} aria-hidden="true" /><span>Đăng xuất</span></button>
          </div>
        </details>
      </div>
    </aside>
  );
}
