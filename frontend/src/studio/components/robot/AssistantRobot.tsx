import React, { useRef, useEffect, useMemo, useState } from 'react';
import { 
  RobotState, 
  RobotController, 
  drawRobotHeadCanvas, 
  RobotColorConfig 
} from './robotEngine';
import { usePointerTracking } from './usePointerTracking';
import { useRobotAssistant } from './RobotContext';

interface AssistantRobotProps {
  size?: number;
  state?: RobotState;
  interactive?: boolean;
  colorConfig?: Partial<RobotColorConfig>;
  className?: string;
  onClick?: () => void;
}

export const AssistantRobot: React.FC<AssistantRobotProps> = ({
  size = 140,
  state: propState,
  interactive = true,
  colorConfig,
  className = '',
  onClick,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    let intersecting = true;
    const update = () => setVisible(intersecting && !document.hidden);
    const observer = new IntersectionObserver(([entry]) => {
      intersecting = entry.isIntersecting;
      update();
    }, { rootMargin: '80px' });
    if (containerRef.current) observer.observe(containerRef.current);
    document.addEventListener('visibilitychange', update);
    update();
    return () => {
      observer.disconnect();
      document.removeEventListener('visibilitychange', update);
    };
  }, []);

  // Lấy ngữ cảnh chung từ RobotAssistant Context
  const { 
    state: contextState, 
    pokeTrigger, 
    targetLook, 
    poke: contextPoke 
  } = useRobotAssistant();

  const activeState = propState || contextState;

  // Cấu hình màu sắc mặc định mang phong cách Cyberpunk Sci-Fi
  const colors: RobotColorConfig = useMemo(() => ({
    shell: colorConfig?.shell || '#1e3a8a',    // Xanh sapphire bóng
    trim: colorConfig?.trim || '#94a3b8',      // Thép bóng mờ
    screen: colorConfig?.screen || '#38bdf8',  // LED Cyan rực rỡ
  }), [colorConfig]);

  // Bộ điều khiển vật lý cho Robot
  const controllerRef = useRef<RobotController | null>(null);
  if (!controllerRef.current) {
    controllerRef.current = new RobotController(activeState);
  }

  // Hook theo dõi con trỏ chuột trên toàn viewport
  const relativePointer = usePointerTracking({
    robotElementRef: containerRef,
    enabled: interactive && visible,
  });

  // Đồng bộ hóa trạng thái state
  useEffect(() => {
    if (controllerRef.current) {
      controllerRef.current.setState(activeState);
    }
  }, [activeState]);

  // Phản ứng với sự kiện Poke
  useEffect(() => {
    if (pokeTrigger > 0 && controllerRef.current) {
      controllerRef.current.poke();
    }
  }, [pokeTrigger]);

  // Đồng bộ mục tiêu nhìn TargetLookAt
  useEffect(() => {
    if (targetLook && controllerRef.current) {
      controllerRef.current.lookAtTarget(targetLook.x, targetLook.y);
    }
  }, [targetLook]);

  // Vòng lặp Render Canvas chính xác với requestAnimationFrame & WCAG Reduced Motion
  useEffect(() => {
    if (!visible) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const controller = controllerRef.current!;
    let lastTime = performance.now();
    let animationFrameId: number;

    // WCAG 2.1: Hỗ trợ người dùng thiết lập prefers-reduced-motion
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let prefersReducedMotion = motionQuery.matches;
    const onMotionChange = (e: MediaQueryListEvent) => {
      prefersReducedMotion = e.matches;
    };
    try {
      motionQuery.addEventListener('change', onMotionChange);
    } catch {
      // Fallback for older browsers
    }

    const render = (now: number) => {
      const elapsed = Math.min(0.08, (now - lastTime) / 1000);
      lastTime = now;
      // Khi prefers-reduced-motion bật: làm chậm và êm dịu chuyển động, không triệt tiêu việc vẽ robot!
      const dt = prefersReducedMotion ? elapsed * 0.35 : elapsed;

      // Cập nhật toán tử vật lý & góc nhìn
      controller.pointer = relativePointer.current;
      const updateResult = controller.update(dt);
      if (updateResult) {
        drawRobotHeadCanvas(
          ctx,
          canvas.width,
          canvas.height,
          updateResult.pose,
          updateResult.face,
          controller.shownState,
          colors
        );
      }

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animationFrameId);
      try {
        motionQuery.removeEventListener('change', onMotionChange);
      } catch {
        // Fallback
      }
    };
  }, [colors, visible, relativePointer]);

  const handleClick = () => {
    if (interactive) {
      contextPoke();
    }
    if (onClick) {
      onClick();
    }
  };

  return (
    <div
      ref={containerRef}
      onClick={handleClick}
      role={interactive ? 'button' : 'img'}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={event => {
        if (interactive && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          handleClick();
        }
      }}
      aria-label={`Trợ lý Robot AI, trạng thái: ${activeState}`}
      className={`relative select-none ${interactive ? 'cursor-pointer' : ''} ${className}`}
      style={{ width: size, height: size }}
    >
      <canvas
        ref={canvasRef}
        width={size * 1.5}
        height={size * 1.5}
        className="absolute -top-[15%] -left-[25%] pointer-events-none"
        style={{
          width: size * 1.5,
          height: size * 1.5,
        }}
      />
    </div>
  );
};
