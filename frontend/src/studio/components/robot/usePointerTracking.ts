import { useEffect, useRef, useCallback } from 'react';
import { PointerTarget } from './robotEngine';

interface UsePointerTrackingOptions {
  robotElementRef: React.RefObject<HTMLElement | null>;
  enabled?: boolean;
}

export function usePointerTracking({ robotElementRef, enabled = true }: UsePointerTrackingOptions) {
  // Dữ liệu từng khung hình chỉ dành cho canvas, không cần render lại React.
  const relativePointer = useRef<PointerTarget | null>(null);
  const targetPosRef = useRef<PointerTarget | null>(null);
  const currentPosRef = useRef<PointerTarget>({ x: 0, y: 0 });
  const isInsideWindowRef = useRef<boolean>(true);
  const rafIdRef = useRef<number | null>(null);

  // Cập nhật vị trí chuột thực tế tương đối với tâm phần tử Robot
  const handlePointerMove = useCallback((e: PointerEvent) => {
    if (!enabled || !robotElementRef.current) return;

    isInsideWindowRef.current = true;
    const rect = robotElementRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    targetPosRef.current = {
      x: e.clientX - centerX,
      y: e.clientY - centerY,
    };
  }, [enabled, robotElementRef]);

  // Xử lý khi chuột rời khỏi màn hình hoặc cửa sổ bị blur
  const handlePointerLeave = useCallback(() => {
    isInsideWindowRef.current = false;
    targetPosRef.current = null;
  }, []);

  // Xử lý tương tác cảm ứng trên điện thoại / tablet
  const handleTouchMove = useCallback((e: TouchEvent) => {
    if (!enabled || !robotElementRef.current || e.touches.length === 0) return;
    const touch = e.touches[0];
    const rect = robotElementRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    targetPosRef.current = {
      x: touch.clientX - centerX,
      y: touch.clientY - centerY,
    };
  }, [enabled, robotElementRef]);

  // Vòng lặp nội suy mượt mà (Linear Interpolation Lerp với độ trễ tự nhiên)
  useEffect(() => {
    if (!enabled) {
      relativePointer.current = null;
      targetPosRef.current = null;
      currentPosRef.current = { x: 0, y: 0 };
      return;
    }

    const prefersReducedMotion = typeof window !== 'undefined' && 
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Hệ số lerp: nếu reduced motion thì phản ứng trực tiếp không tạo độ trễ
    const lerpFactor = prefersReducedMotion ? 0.35 : 0.12;

    let isRunning = true;
    const tick = () => {
      if (!isRunning) return;

      if (targetPosRef.current && isInsideWindowRef.current) {
        // Nội suy từ vị trí hiện tại đến vị trí mục tiêu
        currentPosRef.current.x += (targetPosRef.current.x - currentPosRef.current.x) * lerpFactor;
        currentPosRef.current.y += (targetPosRef.current.y - currentPosRef.current.y) * lerpFactor;

        relativePointer.current = {
          x: currentPosRef.current.x,
          y: currentPosRef.current.y,
        };
      } else {
        // Dần dần trở về vị trí nhìn thẳng (0, 0)
        currentPosRef.current.x += (0 - currentPosRef.current.x) * 0.08;
        currentPosRef.current.y += (0 - currentPosRef.current.y) * 0.08;

        if (Math.hypot(currentPosRef.current.x, currentPosRef.current.y) < 1.5) {
          currentPosRef.current = { x: 0, y: 0 };
          relativePointer.current = null;
        } else {
          relativePointer.current = {
            x: currentPosRef.current.x,
            y: currentPosRef.current.y,
          };
        }
      }

      rafIdRef.current = requestAnimationFrame(tick);
    };

    rafIdRef.current = requestAnimationFrame(tick);

    // Đăng ký các sự kiện pointer toàn cục trên viewport
    window.addEventListener('pointermove', handlePointerMove, { passive: true });
    document.addEventListener('pointerleave', handlePointerLeave);
    window.addEventListener('blur', handlePointerLeave);
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('touchend', handlePointerLeave);

    return () => {
      isRunning = false;
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
      window.removeEventListener('pointermove', handlePointerMove);
      document.removeEventListener('pointerleave', handlePointerLeave);
      window.removeEventListener('blur', handlePointerLeave);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('touchend', handlePointerLeave);
    };
  }, [enabled, handlePointerMove, handlePointerLeave, handleTouchMove]);

  return relativePointer;
}
