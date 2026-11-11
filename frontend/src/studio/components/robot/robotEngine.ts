/**
 * RobotEngine.ts
 * 
 * Bộ Engine dựng hình Canvas 2D 3D-Look cho Robot AI Trợ Lý C1SE.27
 * Dựa trên cấu trúc toán học của robot-heads (Fayaz Ahmed), được mở rộng toàn diện:
 * 1. Viewport-wide Pointer Tracking (không giới hạn 700px, theo dõi toàn màn hình).
 * 2. Target Look-At (hướng ánh nhìn về các phần tử DOM đang tương tác: textarea, nút bấm, agent cards).
 * 3. Micro-saccades & Eye Blinks (chuyển động vi mô tự nhiên khi chuột đứng yên & chớp mắt kép ngẫu nhiên).
 * 4. Phối hợp trạng thái hệ thống: idle, listening, thinking, searching, working, speaking, happy, error, sleeping.
 * 5. Cơ chế giải phóng bộ nhớ sạch, hỗ trợ prefers-reduced-motion và thiết bị cảm ứng mobile.
 */

export type RobotState = 
  | 'idle' 
  | 'receiving'
  | 'decomposing'
  | 'assigning'
  | 'retrieving'
  | 'executing'
  | 'synthesizing'
  | 'completed'
  | 'error' 
  | 'sleeping'
  | 'happy' 
  | 'thinking' 
  | 'searching' 
  | 'listening' 
  | 'speaking' 
  | 'working';

export type RobotShape = 'rectangle' | 'square' | 'circle' | 'hexagon';

export interface RobotColorConfig {
  shell: string;      // Màu vỏ ngoài bóng
  trim: string;       // Màu viền và núm tai kim loại
  screen: string;     // Màu ma trận LED hiển thị
}

export interface PointerTarget {
  x: number; // Tọa độ pixel tương đối so với tâm robot
  y: number;
}

const TWO_PI = Math.PI * 2;
const clamp = (val: number, min: number, max: number) => Math.min(max, Math.max(min, val));

// Lớp vật lý Lò xo Damping (Spring with velocity & damping)
export class DampedSpring {
  x: number = 0;
  v: number = 0;

  constructor(initial: number = 0) {
    this.x = initial;
  }

  step(target: number, dt: number, freq: number, damping: number) {
    const omega = freq * Math.PI * 2;
    this.v += (omega * omega * (target - this.x) - 2 * damping * omega * this.v) * dt;
    this.x += this.v * dt;
  }
}

// Bảng màu trạng thái đèn quả cầu antenna và LED
export const STATE_STYLES: Record<RobotState, { ball: [number, number, number]; pulse: (t: number) => number }> = {
  idle: { ball: [147, 197, 253], pulse: (t) => 0.75 + 0.15 * Math.sin(t * 1.5) },
  receiving: { ball: [52, 211, 153], pulse: () => 0.95 },
  decomposing: { ball: [251, 191, 36], pulse: (t) => 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(t * 5.0)) },
  assigning: { ball: [168, 85, 247], pulse: (t) => (t * 3 % 1 < 0.5 ? 1 : 0.4) },
  retrieving: { ball: [6, 182, 212], pulse: (t) => (t * 2.5 % 1 < 0.25 ? 1 : 0.35) },
  executing: { ball: [99, 102, 241], pulse: (t) => 0.6 + 0.4 * Math.sin(t * 6) },
  synthesizing: { ball: [236, 72, 153], pulse: (t) => 0.5 + 0.5 * Math.sin(t * 7) },
  completed: { ball: [34, 197, 94], pulse: (t) => 0.8 + 0.2 * Math.sin(t * 8) },
  thinking: { ball: [251, 191, 36], pulse: (t) => 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(t * 4.5)) },
  searching: { ball: [6, 182, 212], pulse: (t) => (t * 2.5 % 1 < 0.2 ? 1 : 0.3) },
  listening: { ball: [52, 211, 153], pulse: () => 0.95 },
  speaking: { ball: [255, 255, 255], pulse: (t) => 0.55 + 0.45 * Math.abs(Math.sin(t * 10)) },
  working: { ball: [139, 92, 246], pulse: (t) => (t * 2 % 1 < 0.5 ? 1 : 0.4) },
  happy: { ball: [244, 114, 182], pulse: (t) => 0.8 + 0.2 * Math.sin(t * 8) },
  error: { ball: [239, 68, 68], pulse: (t) => (t * 3 % 1 < 0.5 ? 1 : 0.2) },
  sleeping: { ball: [148, 163, 184], pulse: () => 0.15 },
};

// Phân giải ma trận LED mặt 22x14
const LED_COLS = 22;
const LED_ROWS = 14;

export interface RobotFaceData {
  lookX: number;
  lookY: number;
  blink: number;
  time: number;
  side: number;
}

export class RobotController {
  state: RobotState = 'idle';
  shownState: RobotState = 'idle';
  previousState: RobotState = 'idle';
  time: number = 0;
  switchedTime: number = 10;
  
  // Lò xo vật lý điều khiển góc quay
  yaw = new DampedSpring(0);
  pitch = new DampedSpring(0);
  roll = new DampedSpring(0);
  antennaX = new DampedSpring(0);
  antennaZ = new DampedSpring(0);
  squash = new DampedSpring(0);

  // Vị trí con trỏ & mục tiêu nhìn
  pointer: PointerTarget | null = null;
  targetLookAt: PointerTarget | null = null;
  lookAtTimer: number = 0;

  // Trạng thái chớp mắt & vi chuyển động
  nextBlinkTime: number = 2.0;
  blinkAge: number = -1;
  idleGazeTimer: number = 0;
  microGazeX: number = 0;
  microGazeY: number = 0;

  // Hoạt ảnh nhảy (Hop & Spin khi poke)
  jump: { age: number; height: number; spin: number; air: number } | null = null;
  speechWave: number = 0;

  constructor(initialState: RobotState = 'idle') {
    this.state = initialState;
    this.shownState = initialState;
  }

  setState(newState: RobotState) {
    if (newState !== this.state) {
      this.previousState = this.shownState;
      this.state = newState;
      this.switchedTime = 0;
      if (newState === 'happy') {
        this.poke();
      }
    }
  }

  poke() {
    this.jump = {
      age: 0,
      height: 0.22,
      spin: Math.random() < 0.5 ? 1 : -1,
      air: 0.52
    };
    this.antennaX.v += (Math.random() - 0.5) * 6;
    this.antennaZ.v += 4;
  }

  lookAtTarget(x: number, y: number, durationSec: number = 2.5) {
    this.targetLookAt = { x, y };
    this.lookAtTimer = durationSec;
  }

  update(dt: number) {
    if (dt < 0) return null;
    if (dt > 0) {
      this.time += dt;
      this.switchedTime += dt;
    }

    if (this.shownState !== this.state) {
      this.shownState = this.state;
    }

    // 1. Quản lý mục tiêu nhìn (Ưu tiên TargetLookAt trước, sau đó là Pointer)
    let activePointer = this.pointer;
    if (this.targetLookAt && this.lookAtTimer > 0) {
      this.lookAtTimer -= dt;
      activePointer = this.targetLookAt;
      if (this.lookAtTimer <= 0) {
        this.targetLookAt = null;
      }
    }

    // 2. Chớp mắt tự nhiên
    let blinkValue = 0;
    if (this.time > this.nextBlinkTime) {
      this.blinkAge = 0;
      // 20% khả năng chớp mắt kép (double-blink)
      const isDouble = Math.random() < 0.2;
      this.nextBlinkTime = this.time + (isDouble ? 0.35 : 2.5 + Math.random() * 3.5);
    }
    if (this.blinkAge >= 0) {
      this.blinkAge += dt;
      blinkValue = Math.sin(clamp(this.blinkAge / 0.16, 0, 1) * Math.PI);
      if (this.blinkAge > 0.16) {
        this.blinkAge = -1;
      }
    }

    // 3. Vi chuyển động ánh mắt (Micro-saccades khi con trỏ đứng yên)
    this.idleGazeTimer += dt;
    if (this.idleGazeTimer > 1.2) {
      this.idleGazeTimer = 0;
      this.microGazeX = (Math.random() - 0.5) * 0.4;
      this.microGazeY = (Math.random() - 0.5) * 0.25;
    }

    // 4. Tính toán góc quay mục tiêu dựa trên con trỏ chuột toàn viewport
    let targetYaw = 0;
    let targetPitch = 0;
    let targetRoll = 0;
    let eyeLookX = 0;
    let eyeLookY = 0;

    if (activePointer) {
      // Chuẩn hóa tọa độ trên toàn màn hình với đường cong mượt mà
      const normX = clamp(activePointer.x / 450, -1, 1);
      const normY = clamp(activePointer.y / 450, -1, 1);

      targetYaw = normX * 0.65;
      targetPitch = -normY * 0.42;
      targetRoll = -targetYaw * 0.12;

      eyeLookX = clamp(activePointer.x / 140 + this.microGazeX, -2.8, 2.8);
      eyeLookY = clamp(activePointer.y / 180 + this.microGazeY, -1.8, 1.8);
    } else {
      // Khi không có chuột hoặc rời viewport: thư giãn nhìn về phía trước kèm thở nhẹ
      targetYaw = Math.sin(this.time * 0.8) * 0.08;
      targetPitch = Math.sin(this.time * 1.2) * 0.04;
      eyeLookX = this.microGazeX;
      eyeLookY = this.microGazeY;
    }

    // 5. Điều chỉnh biểu cảm & cử chỉ theo trạng thái hệ thống
    const s = this.time;
    switch (this.shownState) {
      case 'idle':
        // Cử chỉ thở nhẹ và quan sát xung quanh
        break;
      case 'receiving':
      case 'listening':
        // Nghiêng đầu lắng nghe người dùng
        targetYaw += -0.15;
        targetRoll += 0.22;
        targetPitch += 0.06;
        break;
      case 'decomposing':
      case 'thinking':
        // Ngước nhìn lên trên suy tư
        targetYaw += 0.25 * Math.sin(s * 0.8);
        targetPitch += 0.22 + Math.sin(s * 1.5) * 0.05;
        targetRoll += -0.14;
        eyeLookY -= 1.2;
        break;
      case 'assigning':
        // Phân công tác tử: quay đầu nhẹ qua lại
        targetYaw += Math.sin(s * 2.8) * 0.28;
        targetPitch += 0.05;
        break;
      case 'retrieving':
      case 'searching':
        // Ánh mắt quét ngang qua lại tìm kiếm tài liệu
        eyeLookX = Math.sin(s * 4.5) * 2.5;
        targetYaw += Math.sin(s * 2.2) * 0.35;
        break;
      case 'executing':
      case 'working':
        // Tập trung nhìn xuống tác vụ
        targetPitch -= 0.18;
        targetYaw += Math.sin(s * 1.2) * 0.08;
        break;
      case 'synthesizing':
        // Đầu gật nhẹ khi tổng hợp
        targetPitch += Math.sin(s * 4) * 0.08;
        targetRoll += Math.sin(s * 2) * 0.05;
        break;
      case 'speaking':
        // Đầu gật nhẹ nhịp nhàng khi nói
        targetPitch += Math.sin(s * 8) * 0.04;
        this.speechWave = Math.abs(Math.sin(s * 12));
        break;
      case 'completed':
      case 'happy':
        // Lắc lư vui vẻ
        targetYaw += Math.sin(s * 3.5) * 0.2;
        targetRoll += Math.sin(s * 5) * 0.12;
        break;
      case 'error':
        // Lắc đầu bối rối
        targetYaw += Math.sin(s * 14) * 0.22 * Math.max(0, 1 - (s % 2));
        targetPitch -= 0.08;
        break;
      case 'sleeping':
        // Ngủ gục đầu
        targetPitch = -0.38;
        targetRoll = 0.14;
        eyeLookX = 0;
        eyeLookY = 1.0;
        blinkValue = 1; // Nhắm mắt hoàn toàn
        break;
    }

    // 6. Cập nhật lò xo vật lý
    const freq = this.shownState === 'error' ? 2.5 : 1.4;
    const damping = 0.65;
    this.yaw.step(targetYaw, dt, freq, damping);
    this.pitch.step(targetPitch, dt, freq, damping);
    this.roll.step(targetRoll, dt, freq, damping);

    // Xử lý bước nhảy poke
    let jumpLift = 0;
    let jumpSpin = 0;
    if (this.jump) {
      this.jump.age += dt;
      const progress = this.jump.age / this.jump.air;
      if (progress < 1) {
        jumpLift = 4 * this.jump.height * progress * (1 - progress);
        jumpSpin = this.jump.spin * Math.PI * 2 * Math.sin(progress * Math.PI * 0.5);
      } else {
        this.jump = null;
        this.squash.v += 3.2;
        this.antennaX.v += (Math.random() - 0.5) * 4;
      }
    }
    this.squash.step(0, dt, 3.2, 0.35);

    // Lắc lư anten theo chuyển động đầu
    this.antennaX.step(this.yaw.v * -0.15, dt, 2.2, 0.12);
    this.antennaZ.step(this.pitch.v * -0.15, dt, 2.2, 0.12);

    return {
      pose: {
        yaw: this.yaw.x + jumpSpin,
        pitch: this.pitch.x,
        roll: this.roll.x,
        lift: jumpLift + Math.sin(s * 2.0) * 0.008,
        sx: 1 + this.squash.x * 0.45,
        sy: 1 - this.squash.x * 0.8,
        antennaX: clamp(this.antennaX.x, -0.7, 0.7),
        antennaZ: clamp(this.antennaZ.x, -0.7, 0.7),
      },
      face: {
        lookX: eyeLookX,
        lookY: eyeLookY,
        blink: this.shownState === 'sleeping' ? 1 : blinkValue,
        time: this.time,
        side: 1
      }
    };
  }
}

/**
 * Vẽ khung mặt LED Matrix 22x14
 */
export function drawLEDMatrix(
  ctx: CanvasRenderingContext2D,
  face: RobotFaceData,
  state: RobotState,
  ledColor: string,
  width: number,
  height: number
) {
  ctx.save();
  ctx.clearRect(0, 0, width, height);

  // Nền kính đen mờ của màn hình CRT
  const bgGrad = ctx.createRadialGradient(width / 2, height / 2, 0, width / 2, height / 2, Math.max(width, height) * 0.7);
  bgGrad.addColorStop(0, '#0c1017');
  bgGrad.addColorStop(1, '#05070a');
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, width, height);

  const cellW = width / LED_COLS;
  const cellH = height / LED_ROWS;
  const dotSize = Math.min(cellW, cellH) * 0.75;
  const padX = (cellW - dotSize) / 2;
  const padY = (cellH - dotSize) / 2;

  // Lưới điểm LED thụ động mờ
  ctx.fillStyle = 'rgba(255, 255, 255, 0.035)';
  for (let r = 0; r < LED_ROWS; r++) {
    for (let c = 0; c < LED_COLS; c++) {
      ctx.fillRect(c * cellW + padX, r * cellH + padY, dotSize, dotSize);
    }
  }

  // Mảng trạng thái pixel sáng [0..1]
  const pixels = new Float32Array(LED_COLS * LED_ROWS);
  const setPix = (c: number, r: number, val: number = 1) => {
    const col = Math.round(c);
    const row = Math.round(r);
    if (col >= 0 && col < LED_COLS && row >= 0 && row < LED_ROWS) {
      const idx = row * LED_COLS + col;
      pixels[idx] = Math.max(pixels[idx], val);
    }
  };

  const drawRectLED = (startC: number, startR: number, w: number, h: number, val: number = 1) => {
    for (let r = startR; r < startR + h; r++) {
      for (let c = startC; c < startC + w; c++) {
        setPix(c, r, val);
      }
    }
  };

  // Vẽ mắt theo trạng thái & vị trí nhìn
  const eyeShiftX = Math.round(face.lookX);
  const eyeShiftY = Math.round(face.lookY);
  const eyeLeftC = 6 + eyeShiftX;
  const eyeRightC = 13 + eyeShiftX;
  const eyeBaseR = 5 + eyeShiftY;

  const eyeHeight = Math.max(1, Math.round(4 * (1 - face.blink)));

  if (state === 'sleeping') {
    // Hai vệt mắt nhắm khi ngủ
    drawRectLED(eyeLeftC, 7, 3, 1, 0.6);
    drawRectLED(eyeRightC, 7, 3, 1, 0.6);
    // Chữ Zzz bay lên
    const zOffset = (face.time * 1.5) % 3;
    setPix(18, 4 - zOffset, 0.8);
    setPix(19, 4 - zOffset, 0.8);
    setPix(18, 5 - zOffset, 0.6);
  } else if (state === 'error') {
    // Mắt hình chữ X khi lỗi
    const xPatterns = [
      [1, 0, 1],
      [0, 1, 0],
      [1, 0, 1]
    ];
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        if (xPatterns[i][j]) {
          setPix(eyeLeftC + j, 5 + i, 1);
          setPix(eyeRightC + j, 5 + i, 1);
        }
      }
    }
    // Miệng gợn sóng buồn
    for (let i = 0; i < 8; i++) {
      setPix(7 + i, i % 2 === 0 ? 11 : 12, 0.85);
    }
  } else if (state === 'happy') {
    // Khi được chạm/tương tác: mắt tròn to có đốm sáng long lanh, má hồng, miệng cười nhỏ, nhún nhẹ.
    const bob = Math.sin(face.time * 7) > 0.2 ? -1 : 0;
    const eyeR = 5 + bob;
    const h = Math.max(1, Math.round(3 * (1 - face.blink)));
    for (const c0 of [eyeLeftC, eyeRightC]) {
      drawRectLED(c0, eyeR + (3 - h), 3, h, 1);
      if (h === 3) setPix(c0 + 2, eyeR, 0.3); // đốm sáng ở góc mắt
    }
    // Má hồng hai bên (đèn mờ)
    drawRectLED(eyeLeftC - 2, 9 + bob, 2, 1, 0.4);
    drawRectLED(eyeRightC + 3, 9 + bob, 2, 1, 0.4);
    // Miệng cười nhỏ hình chữ U
    setPix(9, 10 + bob, 0.85);
    setPix(12, 10 + bob, 0.85);
    drawRectLED(10, 11 + bob, 2, 1, 0.95);
  } else if (state === 'completed') {
    // Mắt cong hình vòng cung cười ^ ^
    const happyEyes = [
      [0, 1, 0],
      [1, 0, 1]
    ];
    for (let i = 0; i < 2; i++) {
      for (let j = 0; j < 3; j++) {
        if (happyEyes[i][j]) {
          setPix(eyeLeftC + j, 5 + i, 1);
          setPix(eyeRightC + j, 5 + i, 1);
        }
      }
    }
    // Nụ cười LED rộng
    setPix(7, 10, 0.7);
    setPix(14, 10, 0.7);
    drawRectLED(8, 11, 6, 1, 0.95);
  } else {
    // Mắt chữ nhật bình thường có mí mắt chớp
    drawRectLED(eyeLeftC, eyeBaseR, 3, eyeHeight, 1);
    drawRectLED(eyeRightC, eyeBaseR, 3, eyeHeight, 1);

    // Hiệu ứng miệng theo trạng thái hệ thống
    if (state === 'speaking') {
      const mouthHeight = Math.max(1, Math.round(Math.abs(Math.sin(face.time * 12)) * 3));
      drawRectLED(8, 11 - Math.floor(mouthHeight / 2), 6, mouthHeight, 0.95);
    } else if (state === 'executing' || state === 'working') {
      // Thanh tiến trình chạy ngang phân đoạn
      const prog = Math.floor((face.time * 6) % 12);
      for (let i = 0; i < 12; i++) {
        setPix(5 + i, 11, i <= prog ? 0.95 : 0.2);
      }
    } else if (state === 'retrieving' || state === 'searching') {
      // Quét tia radar scanner
      const scanX = Math.round(5 + (Math.sin(face.time * 5) * 0.5 + 0.5) * 11);
      for (let r = 2; r < 12; r++) {
        setPix(scanX, r, 0.75);
      }
    } else if (state === 'decomposing' || state === 'thinking') {
      // 3 dấu chấm suy nghĩ nhấp nháy luân phiên
      for (let i = 0; i < 3; i++) {
        const dotAlpha = 0.3 + 0.7 * Math.max(0, Math.sin(face.time * 5 - i * 0.8));
        drawRectLED(7 + i * 3, 11, 2, 1, dotAlpha);
      }
    } else if (state === 'assigning') {
      // Mũi tên phân luồng tác tử ◄ ─── ►
      setPix(5, 11, 0.9);
      setPix(6, 10, 0.9);
      setPix(6, 12, 0.9);
      drawRectLED(7, 11, 8, 1, 0.8);
      setPix(16, 11, 0.9);
      setPix(15, 10, 0.9);
      setPix(15, 12, 0.9);
    } else if (state === 'synthesizing') {
      // Hai sóng LED hội tụ vào tâm
      const wave = Math.floor((face.time * 8) % 6);
      setPix(6 + wave, 11, 0.9);
      setPix(15 - wave, 11, 0.9);
    } else if (state === 'receiving' || state === 'listening') {
      // Nhịp đập tim lắng nghe
      const pulseH = Math.sin(face.time * 6) > 0.5 ? 2 : 1;
      drawRectLED(9, 11 - Math.floor(pulseH / 2), 4, pulseH, 0.85);
    }
  }

  // Vẽ các điểm pixel sáng lên Canvas kèm hiệu ứng Bloom Glow
  ctx.shadowColor = ledColor;
  ctx.shadowBlur = dotSize * 0.9;
  ctx.fillStyle = ledColor;

  for (let r = 0; r < LED_ROWS; r++) {
    for (let c = 0; c < LED_COLS; c++) {
      const alpha = pixels[r * LED_COLS + c];
      if (alpha > 0.02) {
        ctx.globalAlpha = alpha;
        ctx.fillRect(c * cellW + padX, r * cellH + padY, dotSize, dotSize);
      }
    }
  }

  ctx.restore();
}

/**
 * Vẽ vỏ đầu TV 3D bóng bẩy, núm tai và ăng-ten lò xo
 */
export function drawRobotHeadCanvas(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  pose: { yaw: number; pitch: number; roll: number; lift: number; sx: number; sy: number; antennaX: number; antennaZ: number },
  face: RobotFaceData,
  state: RobotState,
  colors: RobotColorConfig
) {
  const cx = width / 2;
  const cy = height / 2 + 12 - pose.lift * 40;
  const scale = (Math.min(width, height) / 160) * 0.88;

  ctx.save();
  ctx.clearRect(0, 0, width, height);

  // 1. Bóng đổ sàn (Floor Soft Shadow)
  const shadowY = height - 14;
  const shadowRadiusX = 52 * scale * pose.sx * (1 - Math.max(0, pose.lift) * 0.6);
  const shadowRadiusY = 12 * scale * (1 - Math.max(0, pose.lift) * 0.6);

  const shadowGrad = ctx.createRadialGradient(cx, shadowY, 0, cx, shadowY, shadowRadiusX);
  shadowGrad.addColorStop(0, 'rgba(15, 23, 42, 0.28)');
  shadowGrad.addColorStop(0.5, 'rgba(15, 23, 42, 0.08)');
  shadowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = shadowGrad;
  ctx.beginPath();
  ctx.ellipse(cx, shadowY, shadowRadiusX, shadowRadiusY, 0, 0, TWO_PI);
  ctx.fill();

  // 2. Chuyển đổi hệ tọa độ theo biến dạng Squash/Stretch và xoay đầu 3D
  ctx.translate(cx, cy);
  ctx.scale(pose.sx, pose.sy);
  ctx.rotate(pose.roll);

  // 3. Vẽ Ăng-ten lò xo và quả cầu phát sáng
  const antennaStemH = 34 * scale;
  const antennaBaseX = 0;
  const antennaBaseY = -52 * scale;
  const antennaTipX = antennaBaseX + pose.antennaX * 28 * scale;
  const antennaTipY = antennaBaseY - antennaStemH;

  // Trục ăng-ten kim loại cong mượt
  ctx.beginPath();
  ctx.moveTo(antennaBaseX, antennaBaseY);
  ctx.quadraticCurveTo(antennaBaseX, antennaBaseY - antennaStemH * 0.5, antennaTipX, antennaTipY);
  ctx.lineWidth = 3.5 * scale;
  ctx.lineCap = 'round';
  ctx.strokeStyle = '#64748b';
  ctx.stroke();

  ctx.lineWidth = 1.8 * scale;
  ctx.strokeStyle = '#94a3b8';
  ctx.stroke();

  // Quả cầu ăng-ten phát sáng theo trạng thái
  const ballRadius = 8.5 * scale;
  const stateStyle = STATE_STYLES[state] || STATE_STYLES.idle;
  const glowAlpha = stateStyle.pulse(face.time);
  const ballRgb = stateStyle.ball;

  // Quầng sáng tỏa ra (Aura Bloom)
  const auraGrad = ctx.createRadialGradient(antennaTipX, antennaTipY, ballRadius * 0.4, antennaTipX, antennaTipY, ballRadius * 3.2);
  auraGrad.addColorStop(0, `rgba(${ballRgb.join(',')}, ${0.7 * glowAlpha})`);
  auraGrad.addColorStop(0.5, `rgba(${ballRgb.join(',')}, ${0.25 * glowAlpha})`);
  auraGrad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = auraGrad;
  ctx.beginPath();
  ctx.arc(antennaTipX, antennaTipY, ballRadius * 3.2, 0, TWO_PI);
  ctx.fill();

  // Quả cầu sáng trung tâm
  const ballGrad = ctx.createRadialGradient(
    antennaTipX - ballRadius * 0.3,
    antennaTipY - ballRadius * 0.3,
    ballRadius * 0.1,
    antennaTipX,
    antennaTipY,
    ballRadius
  );
  ballGrad.addColorStop(0, '#ffffff');
  ballGrad.addColorStop(0.3, `rgb(${ballRgb.join(',')})`);
  ballGrad.addColorStop(1, '#1e293b');
  ctx.fillStyle = ballGrad;
  ctx.beginPath();
  ctx.arc(antennaTipX, antennaTipY, ballRadius, 0, TWO_PI);
  ctx.fill();

  // 4. Vẽ Núm tai 2 bên (Knob Ears)
  const earOffset = 52 * scale;
  const earW = 12 * scale;
  const earH = 22 * scale;
  const earShiftY = pose.pitch * 14 * scale;

  ctx.fillStyle = colors.trim;
  // Tai trái
  ctx.beginPath();
  ctx.roundRect(-earOffset - earW + pose.yaw * 8 * scale, -earH / 2 + earShiftY, earW, earH, 4 * scale);
  ctx.fill();
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Tai phải
  ctx.beginPath();
  ctx.roundRect(earOffset - pose.yaw * 8 * scale, -earH / 2 + earShiftY, earW, earH, 4 * scale);
  ctx.fill();
  ctx.stroke();

  // 5. Thân Vỏ Robot hình TV bo tròn góc (Moulded Glossy Shell)
  const headW = 96 * scale;
  const headH = 82 * scale;
  const headX = -headW / 2 + pose.yaw * 12 * scale;
  const headY = -headH / 2 + pose.pitch * 10 * scale;
  const cornerR = 24 * scale;

  // Lớp bóng đổ phía sau vỏ
  ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
  ctx.shadowBlur = 18 * scale;
  ctx.shadowOffsetY = 8 * scale;

  // Tô màu thân vỏ gradient 3D bóng
  const shellGrad = ctx.createLinearGradient(headX, headY, headX + headW, headY + headH);
  shellGrad.addColorStop(0, '#3b82f6');
  shellGrad.addColorStop(0.2, colors.shell);
  shellGrad.addColorStop(0.8, '#0f172a');
  shellGrad.addColorStop(1, '#020617');

  ctx.fillStyle = shellGrad;
  ctx.beginPath();
  ctx.roundRect(headX, headY, headW, headH, cornerR);
  ctx.fill();

  // Viền sáng bóng phản chiếu (Specular Rim Lighting)
  ctx.shadowColor = 'transparent';
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
  ctx.lineWidth = 2 * scale;
  ctx.stroke();

  // 6. Mặt kính màn hình LED Matrix âm vào thân (Recessed Screen Bezel)
  const screenPad = 12 * scale;
  const screenW = headW - screenPad * 2;
  const screenH = headH - screenPad * 2 - 4 * scale;
  const screenX = headX + screenPad + pose.yaw * 6 * scale;
  const screenY = headY + screenPad + pose.pitch * 6 * scale;
  const screenR = 14 * scale;

  // Viền đệm cao su viền màn hình (Gasket)
  ctx.fillStyle = '#090d16';
  ctx.beginPath();
  ctx.roundRect(screenX - 2.5 * scale, screenY - 2.5 * scale, screenW + 5 * scale, screenH + 5 * scale, screenR + 2 * scale);
  ctx.fill();

  // 7. Dựng màn hình LED bên trong vùng cắt (Clip Path)
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(screenX, screenY, screenW, screenH, screenR);
  ctx.clip();

  // Tạo một canvas ảo để vẽ LED ma trận và ánh xạ vào
  const offscreen = document.createElement('canvas');
  offscreen.width = 176;
  offscreen.height = 112;
  const offCtx = offscreen.getContext('2d');
  if (offCtx) {
    drawLEDMatrix(offCtx, face, state, colors.screen, offscreen.width, offscreen.height);
    ctx.drawImage(offscreen, screenX, screenY, screenW, screenH);
  }

  // Vệt chói phản quang mặt kính CRT (Glass Reflection Sheen)
  const glassReflect = ctx.createLinearGradient(screenX, screenY, screenX + screenW, screenY + screenH);
  glassReflect.addColorStop(0, 'rgba(255, 255, 255, 0.18)');
  glassReflect.addColorStop(0.35, 'rgba(255, 255, 255, 0.05)');
  glassReflect.addColorStop(0.5, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = glassReflect;
  ctx.fillRect(screenX, screenY, screenW, screenH);

  ctx.restore();

  // Vệt sáng lóa trên đỉnh vỏ TV
  const topSheen = ctx.createLinearGradient(headX, headY, headX + headW, headY);
  topSheen.addColorStop(0, 'rgba(255,255,255,0)');
  topSheen.addColorStop(0.5, 'rgba(255,255,255,0.4)');
  topSheen.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = topSheen;
  ctx.fillRect(headX + 10 * scale, headY + 1 * scale, headW - 20 * scale, 2 * scale);

  ctx.restore();
}
