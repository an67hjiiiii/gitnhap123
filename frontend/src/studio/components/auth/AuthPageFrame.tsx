import { useEffect, useRef, useState, type ReactNode, type MouseEvent } from 'react';
import { flushSync } from 'react-dom';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { BrandLogo } from '../BrandLogo';
import { useRobotAssistant } from '../robot/RobotContext';
import '@fontsource-variable/inter-tight';
import '../../styles/auth-studio.css';

export function AuthPageFrame({mode,children}:{mode:'login'|'register'|'recovery';children:ReactNode}) {
  const root = useRef<HTMLDivElement>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  const navigate = useNavigate();
  const location = useLocation();
  const {setState:setRobotState,poke}=useRobotAssistant();
  // Chuyển giữa các trang tài khoản bằng View Transitions: khung thẻ đổi cỡ mượt, nửa trái đứng yên, form trượt chéo.
  // Trình duyệt không hỗ trợ (hoặc người dùng giảm chuyển động) thì dùng hiệu ứng trượt bằng Web Animations như cũ.
  const viewTransition = typeof document.startViewTransition === 'function' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const internal = Boolean(location.state?.authTransition);
  const [caps, setCaps] = useState(false);
  useEffect(() => {
    mounted.current = true;
    const panel = root.current?.querySelector<HTMLElement>('.auth-form-panel');
    const animation = viewTransition && internal ? undefined : panel?.animate([{opacity:0,transform:`translateX(${mode==='register'?'56':'-56'}px)`},{opacity:1,transform:'translateX(0)'}],{duration:360,easing:'cubic-bezier(.2,.7,.2,1)'});
    if (location.state?.authTransition) root.current?.querySelector<HTMLElement>('h1')?.focus({preventScroll:true});
    return () => { mounted.current=false; animation?.cancel(); };
  }, [mode,location.key]);
  const transition = async (event:MouseEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.button!==0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = (event.target as HTMLElement).closest<HTMLAnchorElement>('a');
    if (!link || link.target || link.hasAttribute('download')) return;
    const target = new URL(link.href);
    if (target.origin!==window.location.origin || !['/login','/register','/forgot-password'].includes(target.pathname)) return;
    event.preventDefault();
    if (pending.current || target.pathname===location.pathname) return;
    pending.current = true;
    poke();
    if (viewTransition) {
      const order = ['/login', '/register', '/forgot-password'];
      document.documentElement.dataset.authDir = order.indexOf(target.pathname) < order.indexOf(location.pathname) ? 'back' : 'fwd';
      // Trang đăng ký đặt nửa thương hiệu bên phải: khi đổi bên (màn hình rộng) thì nửa đó chảy sang như slime.
      const swap = window.matchMedia('(min-width: 850px)').matches && (location.pathname === '/register') !== (target.pathname === '/register');
      const from = swap ? document.querySelector('.auth-brand-panel')?.getBoundingClientRect() : undefined;
      if (from) document.documentElement.dataset.authSlime = '';
      // React Router cập nhật trong startTransition nên flushSync không đủ: chờ tới khi trang mới thật sự hiện (tối đa 1 giây) rồi mới chụp trạng thái mới.
      const nextMode = { '/login': 'login', '/register': 'register', '/forgot-password': 'recovery' }[target.pathname];
      const vt = document.startViewTransition(() => new Promise<void>(done => {
        flushSync(() => navigate(target.pathname, { state: { authTransition: true } }));
        // Trong lúc chờ, trình duyệt tạm ngừng vẽ (không có requestAnimationFrame) nên theo dõi DOM bằng MutationObserver.
        const finish = () => { observer.disconnect(); clearTimeout(timer); done(); };
        const observer = new MutationObserver(() => { if (document.querySelector<HTMLElement>('.auth-redesign')?.dataset.mode === nextMode) finish(); });
        const timer = setTimeout(finish, 1000);
        if (document.querySelector<HTMLElement>('.auth-redesign')?.dataset.mode === nextMode) finish();
        else observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-mode'] });
      }));
      vt.ready.then(() => { const to = document.querySelector('.auth-brand-panel')?.getBoundingClientRect(); if (from && to) slime(from, to); }).catch(() => {});
      vt.finished.finally(() => { pending.current = false; delete document.documentElement.dataset.authDir; delete document.documentElement.dataset.authSlime; });
      return;
    }
    const panel = root.current?.querySelector<HTMLElement>('.auth-form-panel');
    try {
      await panel?.animate([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:`translateX(${target.pathname==='/register'?'-44':'44'}px)`}],{duration:200,easing:'ease-in',fill:'forwards'}).finished;
    } catch { /* Hủy hoạt ảnh khi điều hướng bằng trình duyệt. */ }
    if (mounted.current) navigate(target.pathname,{state:{authTransition:true}});
  };
  return <div ref={root} className="auth-redesign" data-mode={mode} data-static={internal ? '' : undefined} data-caps={caps ? '' : undefined}
    onKeyUpCapture={event => { if (event.target instanceof HTMLInputElement && event.target.type === 'password') setCaps(event.getModifierState('CapsLock')); }}
    onClickCapture={transition} onFocusCapture={event=>{if(!(event.target instanceof HTMLInputElement))return;const pw=event.target.type==='password';window.dispatchEvent(new CustomEvent('auth-password-focus',{detail:pw}));if(!pw)setRobotState('listening');}} onBlurCapture={event=>{if(event.target instanceof HTMLInputElement&&event.target.type==='password'){window.dispatchEvent(new CustomEvent('auth-password-focus',{detail:false}));setCaps(false);}}} onSubmitCapture={()=>setRobotState('thinking')}>
    <header className="auth-topbar"><Link to="/" aria-label="OrchestrIQ Studio — trang chủ"><BrandLogo showSubtitle={false}/></Link><Link to="/" className="auth-home"><ArrowLeft size={15}/> Về trang giới thiệu</Link></header>
    <main className="auth-card">{children}</main>
    <footer className="auth-bottom"><span>© 2026 OrchestrIQ Studio</span><span>Nền tảng tri thức Multi-Agent RAG</span></footer>
  </div>;
}
// Slime: mép trước vươn dài về phía đích (đầu mép phình tròn), mép sau bị kéo theo, tới nơi nảy nhẹ rồi đứng yên.
// Thân hơi dẹt lại khi kéo dài. Toạ độ theo khung nhìn, đúng hệ toạ độ của nhóm View Transition.
function slime(a: DOMRect, b: DOMRect) {
  if (Math.abs(a.left - b.left) < 2) return;
  const s = b.left > a.left ? 1 : -1, R = '30px', w = b.width;
  const lead0 = s > 0 ? a.right : a.left, trail0 = s > 0 ? a.left : a.right, lead1 = s > 0 ? b.right : b.left, trail1 = s > 0 ? b.left : b.right;
  type C = [string, string];
  // [mốc, mép trước, mép sau, hệ số chiều cao, góc mép trước, góc mép sau]; mép ngoài của thẻ bo 30px, mép trong vuông
  const steps: [number, number, number, number, C, C][] = [
    [0, lead0, trail0, 1, ['0px', '0px'], [R, R]],
    [0.42, trail0 + (lead1 - trail0) * 0.88, trail0, 0.95, ['180px', '50%'], [R, R]],
    [0.64, lead1, trail1 - s * 0.2 * w, 0.97, [R, R], ['160px', '50%']],
    [0.8, lead1, trail1 + s * 0.04 * w, 1.012, [R, R], ['50px', '35%']],
    [0.91, lead1, trail1 - s * 0.012 * w, 0.998, [R, R], ['14px', '12%']],
    [1, lead1, trail1, 1, [R, R], ['0px', '0px']],
  ];
  // Chiều cao và mép trên đi theo cùng đường cong với khung thẻ (cubic-bezier(.65,0,.35,1) ≈ ease-in-out bậc ba).
  const lerp = (x: number, y: number, t: number) => x + (y - x) * t;
  document.documentElement.animate(steps.map(([t, lead, trail, k, cl, ct]) => {
    const e = t < .5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2, left = Math.min(lead, trail), h = lerp(a.height, b.height, e), [l, r] = s > 0 ? [ct, cl] : [cl, ct];
    return { offset: t, easing: 'cubic-bezier(.45,0,.4,1)', transform: `translate(${left}px, ${lerp(a.top, b.top, e) + (h - h * k) / 2}px)`, width: `${Math.abs(lead - trail)}px`, height: `${h * k}px`,
      borderRadius: `${l[0]} ${r[0]} ${r[0]} ${l[0]} / ${l[1]} ${r[1]} ${r[1]} ${l[1]}` };
  }), { duration: 900, fill: 'both', pseudoElement: '::view-transition-group(auth-brand)' });
}
export function AuthTabs({active}:{active:'login'|'register'|'recovery'}) {
  return <nav className="auth-tabs" aria-label="Tài khoản"><span className="auth-tab-indicator" data-register={active==='register'} aria-hidden="true"/><Link to="/login" aria-current={active==='login'?'page':undefined}>Đăng nhập</Link><Link to="/register" aria-current={active==='register'?'page':undefined}>Đăng ký</Link></nav>;
}
