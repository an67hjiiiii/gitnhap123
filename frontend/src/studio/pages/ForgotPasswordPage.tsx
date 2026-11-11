import React, { useState } from 'react';
import { AuthPageFrame, AuthTabs } from '../components/auth/AuthPageFrame';
import { AuthBrandSide } from '../components/auth/AuthBrandSide';
import {  KeyRound, Mail, Check, Database } from 'lucide-react';

export const ForgotPasswordPage: React.FC = () => {
  const [identifier, setIdentifier] = useState('');
  const [isSubmitted, setIsSubmitted] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!identifier.trim()) return;
    setIsSubmitted(true);
  };

  return (
    <AuthPageFrame mode="recovery">
      {/* 1. Left Visual Brand Side */}
      <AuthBrandSide quote="Quản lý tài khoản trong môi trường nghiên cứu cục bộ của nhóm C1SE.27." />

      {/* 2. Right Form Area */}
      <div className="auth-form-panel">
        <AuthTabs active="recovery"/>

        {/* Central Content */}
        <div className="max-w-md w-full mx-auto my-auto py-8 space-y-6">
          <div className="space-y-1.5">
            <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight text-slate-900">
              Khôi phục quyền truy cập
            </h1>
            <p className="text-xs sm:text-sm text-slate-500">
              Cơ chế bảo vệ và hướng dẫn đặt lại mật khẩu trong môi trường cục bộ On-Premise.
            </p>
          </div>

          {!isSubmitted ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label 
                  htmlFor="recovery-input" 
                  className="text-xs font-semibold text-slate-700"
                >
                  Email hoặc Tên đăng nhập
                </label>
                <div className="relative rounded-xl border border-slate-300 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-100 bg-white transition-all shadow-2xs">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                    <Mail className="w-4 h-4" />
                  </div>
                  <input
                    id="recovery-input"
                    type="text"
                    value={identifier}
                    onChange={(e) => setIdentifier(e.target.value)}
                    placeholder="ví dụ: chung_dev hoặc chung.kieu@c1se27.edu.vn"
                    required
                    className="w-full pl-10 pr-4 py-2.5 text-sm text-slate-900 placeholder-slate-400 outline-none rounded-xl"
                  />
                </div>
              </div>

              <button
                type="submit"
                className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-xs transition-all cursor-pointer"
              >
                <KeyRound className="w-4 h-4" />
                <span>Xem hướng dẫn khôi phục</span>
              </button>
            </form>
          ) : (
            <div className="p-4 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 space-y-2 animate-subtle-in">
              <div className="flex items-center gap-2 font-bold text-sm text-emerald-950">
                <Check className="w-4 h-4 text-emerald-600" />
                <span>Liên hệ quản trị viên để khôi phục</span>
              </div>
              <p className="leading-relaxed">
                Vui lòng cung cấp tên tài khoản ({identifier}) cho quản trị viên dự án. Trang này chưa gửi yêu cầu hoặc thay đổi dữ liệu tài khoản.
              </p>
            </div>
          )}

          {/* Local Deployment Architectural Notice */}
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-600 space-y-2">
            <div className="flex items-center gap-1.5 font-bold text-slate-800">
              <Database className="w-3.5 h-3.5 text-indigo-600" />
              <span>Quy trình Quản trị Cơ sở Dữ liệu Nội bộ (Local On-Premise):</span>
            </div>
            <p className="leading-relaxed text-[11px] text-slate-500">Chức năng tự đặt lại mật khẩu chưa được kết nối API. Liên hệ quản trị viên dự án để xác minh tài khoản và nhận hướng dẫn hỗ trợ.</p>
          </div>
        </div>

        {/* Footer */}
        <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <span>Hỗ trợ: quản trị viên dự án C1SE.27</span>
          <span>ĐH Duy Tân</span>
        </div>
      </div>
    </AuthPageFrame>
  );
};
