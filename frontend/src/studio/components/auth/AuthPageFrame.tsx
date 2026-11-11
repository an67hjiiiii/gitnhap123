import { useEffect, useRef, type ReactNode, type MouseEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { BrandLogo } from '../BrandLogo';
import { useRobotAssistant } from '../robot/RobotContext';
import '../../styles/auth-studio.css';

export function AuthPageFrame({mode,children}:{mode:'login'|'register'|'recovery';children:ReactNode}) {
  const root = useRef<HTMLDivElement>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  const navigate = useNavigate();
  const location = useLocation();
  const {setState:setRobotState,poke}=useRobotAssistant();
  useEffect(() => {
    mounted.current = true;
    const panel = root.current?.querySelector<HTMLElement>('.auth-form-panel');
    const animation = panel?.animate([{opacity:0,transform:`translateX(${mode==='register'?'56':'-56'}px)`},{opacity:1,transform:'translateX(0)'}],{duration:360,easing:'cubic-bezier(.2,.7,.2,1)'});
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
    const panel = root.current?.querySelector<HTMLElement>('.auth-form-panel');
    try {
      await panel?.animate([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:`translateX(${target.pathname==='/register'?'-44':'44'}px)`}],{duration:200,easing:'ease-in',fill:'forwards'}).finished;
    } catch { /* Hủy hoạt ảnh khi điều hướng bằng trình duyệt. */ }
    if (mounted.current) navigate(target.pathname,{state:{authTransition:true}});
  };
  return <div ref={root} className="auth-redesign" data-mode={mode} onClickCapture={transition} onFocusCapture={event=>{if(event.target instanceof HTMLInputElement)setRobotState('listening');}} onSubmitCapture={()=>setRobotState('thinking')}>
    <header className="auth-topbar"><Link to="/" aria-label="OrchestrIQ Studio — trang chủ"><BrandLogo showSubtitle={false}/></Link><Link to="/" className="auth-home"><ArrowLeft size={15}/> Về trang giới thiệu</Link></header>
    <main className="auth-card">{children}</main>
    <footer className="auth-bottom"><span>C1SE.27 · Đại học Duy Tân</span><span>Không gian nghiên cứu Multi-Agent RAG</span></footer>
  </div>;
}
export function AuthTabs({active}:{active:'login'|'register'|'recovery'}) {
  return <nav className="auth-tabs" aria-label="Tài khoản"><span className="auth-tab-indicator" data-register={active==='register'} aria-hidden="true"/><Link to="/login" aria-current={active==='login'?'page':undefined}>Đăng nhập</Link><Link to="/register" aria-current={active==='register'?'page':undefined}>Đăng ký</Link></nav>;
}
