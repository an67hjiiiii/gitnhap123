import React, { useEffect, useState } from 'react';
import { useRobotAssistant } from '../components/robot/RobotContext';
import { useNavigate, Link } from 'react-router-dom';
import { AuthPageFrame, AuthTabs } from '../components/auth/AuthPageFrame';
import { AuthBrandSide } from '../components/auth/AuthBrandSide';
import { login } from '../services/api';
import { User } from '../types';
import { 
  User as UserIcon, 
  Lock, 
  Eye, 
  EyeOff, 
  ArrowRight, 
   
  AlertCircle, 
  Check
} from 'lucide-react';

interface LoginPageProps {
  onLoginSuccess: (user: User) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const navigate = useNavigate();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const {setState:setRobotState}=useRobotAssistant();
  // Đăng nhập bằng tài khoản tổ chức (Đợt 10): chỉ hiện khi máy chủ đã cấu hình OIDC (mặc định tắt)
  const [sso, setSso] = useState<{ id: string; label: string }[]>([]);
  useEffect(() => {
    fetch('/api/auth/oidc/providers', { credentials: 'same-origin' }).then(r => (r.ok ? r.json() : { providers: [] })).then(j => setSso(j.providers || [])).catch(() => setSso([]));
    const e = new URLSearchParams(window.location.search).get('sso_error');
    if (e) setError(`Nhà cung cấp tài khoản tổ chức không cho đăng nhập (${e}). Thử lại hoặc dùng mật khẩu.`);
  }, []);



  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('Vui lòng điền đầy đủ tên đăng nhập và mật khẩu.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const result = await login(username.trim(), password);
      setSuccess(true);
      setRobotState('happy');
      onLoginSuccess(result.user);
      setTimeout(() => {
        navigate('/studio');
      }, 500);
    } catch (err: any) {
      setError(err.message || 'Đăng nhập không thành công. Vui lòng kiểm tra lại thông tin.');
      setIsLoading(false);
      setRobotState('error');
    }
  };

  return (
    <AuthPageFrame mode="login">
      {/* 1. Left Visual Brand Side (42-45%) */}
      <AuthBrandSide quote="Tài liệu, tác tử và kết quả. Kết nối các góc nhìn chuyên môn trong một không gian làm việc." />

      {/* 2. Right Form Authentication Area (55-58%) */}
      <div 
        className="auth-form-panel"
      >
        <AuthTabs active="login"/>

        {/* Central Authentication Form */}
        <div className="max-w-md w-full mx-auto my-auto py-8 space-y-6">
          <div className="space-y-1.5">
            <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight text-slate-900">
              Chào mừng trở lại.
            </h1>
            <p className="text-xs sm:text-sm text-slate-500">
              Tiếp tục công việc của bạn trong OrchestrIQ Studio.
            </p>
          </div>

          {/* Error Notice */}
          {error && (
            <div role="alert" className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-start gap-2 animate-subtle-in">
              <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
              <div className="leading-relaxed">{error}</div>
            </div>
          )}

          {/* Form Controls */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username Field */}
            <div className="space-y-1.5">
              <label 
                htmlFor="login-username" 
                className="text-xs font-semibold text-slate-700 flex items-center justify-between"
              >
                <span>Email hoặc tên đăng nhập</span>

              </label>
              <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-colors shadow-2xs">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                  <UserIcon className="w-4 h-4" />
                </div>
                <input
                  id="login-username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="ví dụ: ban@congty.vn"
                  autoComplete="username"
                  required
                  className="w-full pl-10 pr-4 py-2.5 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl"
                />
              </div>
            </div>

            {/* Password Field */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label 
                  htmlFor="login-password" 
                  className="text-xs font-semibold text-slate-700"
                >
                  Mật khẩu
                </label>
                <Link 
                  to="/forgot-password" 
                  className="text-[11px] text-indigo-600 hover:text-indigo-700 font-medium"
                >
                  Quên mật khẩu?
                </Link>
              </div>

              <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-colors shadow-2xs">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                  className="w-full pl-10 pr-10 py-2.5 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600 transition-colors"
                  title={showPassword ? 'Ẩn mật khẩu' : 'Hiển thị mật khẩu'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:scale-[0.99] text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
            >
              {isLoading && !success ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Đang xác thực thông tin...</span>
                </>
              ) : success ? (
                <>
                  <Check className="w-4 h-4 text-emerald-300" />
                  <span>Xác thực thành công! Đang chuyển hướng...</span>
                </>
              ) : (
                <>
                  <span>Đăng nhập vào Studio</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
          {sso.length > 0 && <div className="auth-sso" aria-label="Đăng nhập bằng tài khoản tổ chức">
            <span>hoặc dùng tài khoản tổ chức</span>
            {sso.map(p => <a key={p.id} className="auth-sso-btn" href={`/api/auth/oidc/${encodeURIComponent(p.id)}/start`}>Đăng nhập bằng {p.label}</a>)}
          </div>}

        </div>

        {/* Thông tin bổ trợ */}
        <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <span>OrchestrIQ Studio · Multi-Agent RAG</span>
          <span>Tri thức · Phối hợp · Kiểm chứng</span>
        </div>
      </div>
    </AuthPageFrame>
  );
};
