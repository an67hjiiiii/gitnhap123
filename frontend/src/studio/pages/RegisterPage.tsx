import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthPageFrame, AuthTabs } from '../components/auth/AuthPageFrame';
import { AuthBrandSide } from '../components/auth/AuthBrandSide';
import { useRobotAssistant } from '../components/robot/RobotContext';
import { register } from '../services/api';
import { User } from '../types';
import { 
  Eye, 
  EyeOff, 
  ArrowRight, 
   
  AlertCircle, 
  Check, 
  Shield, 
  Layers, 
  Sparkles 
} from 'lucide-react';

interface RegisterPageProps {
  onRegisterSuccess: (user: User) => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({ onRegisterSuccess }) => {
  const navigate = useNavigate();

  const [fullName, setFullName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation,setConfirmation]=useState('');
  const {setState:setRobotState}=useRobotAssistant();
  const [showPassword, setShowPassword] = useState(false);
  const [role, setRole] = useState<'tech_lead' | 'researcher' | 'developer'>('developer');

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);


  const validateForm = () => {
    if (!fullName.trim()) return 'Vui lòng nhập Họ và tên đầy đủ.';
    if (username.trim().length < 3) return 'Tên đăng nhập phải có ít nhất 3 ký tự.';
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email.trim())) return 'Địa chỉ Email không đúng định dạng.';
    if (!/^[a-zA-Z0-9_]{3,64}$/.test(username)) return 'Tên đăng nhập gồm 3–64 chữ, số hoặc dấu gạch dưới.';
    if (password.length < 8 || password.length > 128) return 'Mật khẩu phải có từ 8 đến 128 ký tự.';
    if(password!==confirmation)return 'Mật khẩu nhập lại chưa khớp.';
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      setRobotState('error');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const result = await register({
        full_name: fullName.trim(),
        username: username.trim(),
        email: email.trim(),
        password,
        role
      });

      setSuccess(true);
      setRobotState('happy');
      onRegisterSuccess(result.user);
      setTimeout(() => {
        navigate('/studio');
      }, 700);
    } catch (err: any) {
      setError(err.message || 'Đăng ký tài khoản không thành công. Vui lòng thử lại.');
      setIsLoading(false);
      setRobotState('error');
    }
  };

  return (
    <AuthPageFrame mode="register">
      {/* 1. Left Visual Brand Side */}
      <AuthBrandSide quote="Một yêu cầu, nhiều góc nhìn. Cùng xây dựng những kết quả có thể đối chiếu và kiểm chứng." />

      {/* 2. Right Registration Area */}
      <div 
        className="auth-form-panel"
      >
        <AuthTabs active="register"/>

        {/* Central Registration Form */}
        <div className="max-w-md w-full mx-auto my-auto py-6 space-y-5">
          <div className="space-y-1">
            <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight text-slate-900">
              Bắt đầu cùng Studio.
            </h1>
            <p className="text-xs sm:text-sm text-slate-500">
              Tạo tài khoản để tổ chức tri thức và khám phá các cơ chế điều phối.
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
          <form onSubmit={handleSubmit} className="space-y-3.5">
            {/* Full Name */}
            <div className="space-y-1">
              <label 
                htmlFor="reg-fullname" 
                className="text-xs font-semibold text-slate-700"
              >
                Họ và tên
              </label>
              <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-colors shadow-2xs">
                <input
                  id="reg-fullname"
                  autoComplete="name"
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="ví dụ: Kiều Đức Chung"
                  required
                  className="w-full px-3.5 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl"
                />
              </div>
            </div>

            {/* Username & Email in Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label 
                  htmlFor="reg-username" 
                  className="text-xs font-semibold text-slate-700"
                >
                  Tên đăng nhập
                </label>
                <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-colors shadow-2xs">
                  <input
                    id="reg-username"
                  autoComplete="username"
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/\s+/g, '_'))}
                    placeholder="chung_dev"
                    required
                    className="w-full px-3.5 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label 
                  htmlFor="reg-email" 
                  className="text-xs font-semibold text-slate-700"
                >
                  Email
                </label>
                <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-colors shadow-2xs">
                  <input
                    id="reg-email"
                  autoComplete="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="email@c1se27.edu.vn"
                    required
                    className="w-full px-3.5 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl"
                  />
                </div>
              </div>
            </div>

            {/* Password */}
            <div className="space-y-1">
              <label 
                htmlFor="reg-password" 
                className="text-xs font-semibold text-slate-700 flex items-center justify-between"
              >
                <span>Mật khẩu</span>
                <span className="text-[10px] text-slate-400">Tối thiểu 8 ký tự</span>
              </label>
              <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-colors shadow-2xs">
                <input
                  id="reg-password"
                  autoComplete="new-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="w-full pl-3.5 pr-10 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiển thị mật khẩu'}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600 transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Professional Role Selection */}
            <div className="space-y-1"><label htmlFor="reg-confirm">Nhập lại mật khẩu</label><div className="relative rounded-xl"><input id="reg-confirm" type={showPassword?'text':'password'} autoComplete="new-password" required value={confirmation} onChange={e=>setConfirmation(e.target.value)} className="w-full px-3.5" placeholder="Nhập lại mật khẩu của bạn"/></div></div>
            <div className="space-y-1.5 pt-1">
              <label className="text-xs font-semibold text-slate-700">
                Vai trò chuyên môn
              </label>

              <div className="grid grid-cols-3 gap-2">
                {/* Tech Lead */}
                <button
                  type="button"
                  onClick={() => setRole('tech_lead')}
                  aria-pressed={role === 'tech_lead'}
                  className={`p-2.5 rounded-xl border text-left transition-colors cursor-pointer ${
                    role === 'tech_lead'
                      ? 'border-indigo-600 bg-indigo-50/50 ring-1 ring-indigo-600'
                      : 'border-slate-200 hover:border-slate-300 bg-white'
                  }`}
                >
                  <Shield className="w-4 h-4 text-indigo-600 mb-1" />
                  <p className="text-xs font-bold text-slate-900 leading-none">Trưởng nhóm</p>
                  <p className="text-[10px] text-slate-500 mt-1 leading-tight">Kiến trúc & RBAC</p>
                </button>

                {/* AI Researcher */}
                <button
                  type="button"
                  onClick={() => setRole('researcher')}
                  aria-pressed={role === 'researcher'}
                  className={`p-2.5 rounded-xl border text-left transition-colors cursor-pointer ${
                    role === 'researcher'
                      ? 'border-indigo-600 bg-indigo-50/50 ring-1 ring-indigo-600'
                      : 'border-slate-200 hover:border-slate-300 bg-white'
                  }`}
                >
                  <Sparkles className="w-4 h-4 text-purple-600 mb-1" />
                  <p className="text-xs font-bold text-slate-900 leading-none">Nghiên cứu</p>
                  <p className="text-[10px] text-slate-500 mt-1 leading-tight">Mô hình RAG & Ablation</p>
                </button>

                {/* Developer */}
                <button
                  type="button"
                  onClick={() => setRole('developer')}
                  aria-pressed={role === 'developer'}
                  className={`p-2.5 rounded-xl border text-left transition-colors cursor-pointer ${
                    role === 'developer'
                      ? 'border-indigo-600 bg-indigo-50/50 ring-1 ring-indigo-600'
                      : 'border-slate-200 hover:border-slate-300 bg-white'
                  }`}
                >
                  <Layers className="w-4 h-4 text-emerald-600 mb-1" />
                  <p className="text-xs font-bold text-slate-900 leading-none">Phát triển</p>
                  <p className="text-[10px] text-slate-500 mt-1 leading-tight">Module & Kiểm thử</p>
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full mt-2 py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:scale-[0.99] text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
            >
              {isLoading && !success ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Đang khởi tạo tài khoản...</span>
                </>
              ) : success ? (
                <>
                  <Check className="w-4 h-4 text-emerald-300" />
                  <span>Khởi tạo thành công! Đang chuyển hướng...</span>
                </>
              ) : (
                <>
                  <span>Tạo tài khoản</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        </div>

        {/* Thông tin bổ trợ */}
        <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <span>Tài khoản dùng trong không gian nghiên cứu</span>
          <span>C1SE.27 DTU</span>
        </div>
      </div>
    </AuthPageFrame>
  );
};
