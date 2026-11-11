import React, { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { RobotState } from './robotEngine';

interface RobotContextType {
  state: RobotState;
  setState: (state: RobotState) => void;
  speechText: string;
  setSpeechText: (text: string) => void;
  speak: (text: string, mood?: RobotState) => void;
  targetLook: { x: number; y: number } | null;
  lookAtElement: (elementId: string, durationSec?: number) => void;
  pokeTrigger: number;
  poke: () => void;
  soundEnabled: boolean;
  setSoundEnabled: (enabled: boolean) => void;
  toggleSound: () => void;
  robotPositionRef: React.RefObject<HTMLDivElement | null>;
}

const RobotContext = createContext<RobotContextType | null>(null);

// Trình tổng hợp âm thanh Web Audio API nhẹ nhàng (Không phụ thuộc file mp3 ngoài)
class RetroAudioSynth {
  private ctx: AudioContext | null = null;

  private init() {
    if (!this.ctx && typeof window !== 'undefined') {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
  }

  playChirp() {
    try {
      this.init();
      if (!this.ctx) return;
      if (this.ctx.state === 'suspended') {
        this.ctx.resume();
      }
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(440, this.ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(880, this.ctx.currentTime + 0.12);

      gain.gain.setValueAtTime(0.08, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.12);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start();
      osc.stop(this.ctx.currentTime + 0.12);
    } catch (e) {
      // Bỏ qua nếu trình duyệt chặn autoplay
    }
  }

  playHappyChime() {
    try {
      this.init();
      if (!this.ctx) return;
      if (this.ctx.state === 'suspended') {
        this.ctx.resume();
      }
      const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
      notes.forEach((freq, idx) => {
        const time = this.ctx!.currentTime + idx * 0.08;
        const osc = this.ctx!.createOscillator();
        const gain = this.ctx!.createGain();

        osc.type = 'triangle';
        osc.frequency.setValueAtTime(freq, time);

        gain.gain.setValueAtTime(0.06, time);
        gain.gain.exponentialRampToValueAtTime(0.001, time + 0.2);

        osc.connect(gain);
        gain.connect(this.ctx!.destination);

        osc.start(time);
        osc.stop(time + 0.2);
      });
    } catch (e) {}
  }
}

const synth = new RetroAudioSynth();

const POKE_LINES = [
  'Chào bạn, mình là C27. Cần tìm gì cứ hỏi nhé.',
  'Hửm? Bạn muốn xem tài liệu nào?',
  'Ồ, mình đây! Mình vẫn đang sẵn sàng.',
  'Hôm nay làm việc cùng bạn vui ghê.',
  'Nhỏ thôi nhé: mình chỉ đọc tài liệu trong máy của bạn.',
]

export const RobotProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<RobotState>('idle');
  const [speechText, setSpeechText] = useState<string>(
    'Chào bạn! Tôi là RoboAgent C27, trợ lý kiến trúc phần mềm Multi-Agent cục bộ.'
  );
  const [targetLook, setTargetLook] = useState<{ x: number; y: number } | null>(null);
  const [pokeTrigger, setPokeTrigger] = useState<number>(0);
  const [soundEnabled, setSoundEnabled] = useState<boolean>(false);
  const robotPositionRef = useRef<HTMLDivElement>(null);
  const idleTimerRef = useRef<number | null>(null);

  // Phát tiếng nói và đổi biểu cảm
  const speak = useCallback((text: string, mood?: RobotState) => {
    setSpeechText(text);
    if (mood) {
      setState(mood);
    }
  }, []);

  // Chức năng Poke: Nhảy xoay vòng và vui vẻ
  const pokeCount = useRef(0);
  const poke = useCallback(() => {
    // Câu nói đi theo biểu cảm sẽ hiện (cùng thứ tự với robotEngine: tròn, cười tít, trái tim, ngôi sao, nháy mắt).
    setSpeechText(POKE_LINES[pokeCount.current % POKE_LINES.length]);
    pokeCount.current += 1;
    setPokeTrigger(pokeCount.current);
    setState('happy');
    if (soundEnabled) {
      synth.playChirp();
    }
  }, [soundEnabled]);

  // Hướng ánh nhìn về một phần tử cụ thể trên giao diện (Target Look-At)
  const lookAtElement = useCallback((elementId: string, durationSec: number = 2.5) => {
    const el = document.getElementById(elementId);
    if (el && robotPositionRef.current) {
      const elRect = el.getBoundingClientRect();
      const elCenter = {
        x: elRect.left + elRect.width / 2,
        y: elRect.top + elRect.height / 2,
      };

      const robotRect = robotPositionRef.current.getBoundingClientRect();
      const robotCenter = {
        x: robotRect.left + robotRect.width / 2,
        y: robotRect.top + robotRect.height / 2,
      };

      setTargetLook({
        x: elCenter.x - robotCenter.x,
        y: elCenter.y - robotCenter.y,
      });

      // Reset sau duration
      setTimeout(() => {
        setTargetLook(null);
      }, durationSec * 1000);
    }
  }, []);

  // Âm thanh khi chuyển sang trạng thái Happy
  useEffect(() => {
    if (state === 'happy' && soundEnabled) {
      synth.playHappyChime();
    }
  }, [state, soundEnabled]);

  // Tự động chuyển về trạng thái ngủ (sleeping) khi không có tương tác trong 60 giây
  useEffect(() => {
    const resetIdleTimer = () => {
      if (idleTimerRef.current) {
        window.clearTimeout(idleTimerRef.current);
      }
      if (state === 'sleeping') {
        setState('idle');
        setSpeechText('Tôi đã thức dậy và sẵn sàng hỗ trợ phân tích!');
      }
      idleTimerRef.current = window.setTimeout(() => {
        if (state === 'idle') {
          setState('sleeping');
          setSpeechText('Zzz... Hệ thống đang ở chế độ nghỉ. Di chuyển chuột để đánh thức tôi.');
        }
      }, 50000);
    };

    window.addEventListener('pointermove', resetIdleTimer, { passive: true });
    window.addEventListener('keydown', resetIdleTimer, { passive: true });
    resetIdleTimer();

    return () => {
      if (idleTimerRef.current) {
        window.clearTimeout(idleTimerRef.current);
      }
      window.removeEventListener('pointermove', resetIdleTimer);
      window.removeEventListener('keydown', resetIdleTimer);
    };
  }, [state]);

  const toggleSound = () => setSoundEnabled(prev => !prev);

  return (
    <RobotContext.Provider
      value={{
        state,
        setState,
        speechText,
        setSpeechText,
        speak,
        targetLook,
        lookAtElement,
        pokeTrigger,
        poke,
        soundEnabled,
        setSoundEnabled,
        toggleSound,
        robotPositionRef,
      }}
    >
      {children}
    </RobotContext.Provider>
  );
};

export const useRobotAssistant = () => {
  const context = useContext(RobotContext);
  if (!context) {
    throw new Error('useRobotAssistant must be used within a RobotProvider');
  }
  return context;
};
