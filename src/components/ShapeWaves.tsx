// Inspired by React Bits ShapeWaves & Vercel Labs
import { useEffect, useRef, useState } from 'react';
import './ShapeWaves.css';

export interface ShapeWavesProps {
  text?: string;
  fontFamily?: string;
  fontWeight?: string | number;
  textSize?: number;
  shapes?: 'mixed' | 'squares' | 'circles' | 'triangles';
  cellSize?: number;
  dotSize?: number;
  color?: string;
  hoverColor?: string;
  backgroundColor?: string;
  speed?: number;
  scale?: number;
  contrast?: number;
  brightness?: number;
  flow?: number;
  direction?: number;
  fade?: number;
  interactive?: boolean;
  splashRadius?: number;
  splashStrength?: number;
  glow?: number;
  intro?: boolean;
  introDuration?: number;
  introKey?: string | number;
  paused?: boolean;
  onError?: (error: Error) => void;
  className?: string;
}

// 3D Perlin noise generator for wave field animation
function createNoise3D() {
  const p = new Uint8Array(512);
  const permutation = [
    151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,103,30,69,142,
    8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,219,203,117,
    35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,74,165,71,
    134,139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,105,92,41,
    55,46,245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,208,89,
    18,169,200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,217,226,
    250,124,123,5,202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,17,182,
    189,28,42,223,183,170,213,119,248,152,2,44,154,163,70,221,153,101,155,167,43,
    172,9,129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,218,246,97,
    228,251,34,242,193,238,210,144,12,191,179,162,241,81,51,145,235,249,14,239,
    107,49,192,214,31,181,199,106,157,184,84,204,176,115,121,50,45,127,4,150,254,
    138,236,205,93,222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180
  ];
  for (let i = 0; i < 256; i++) {
    p[i] = permutation[i];
    p[256 + i] = permutation[i];
  }
  const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
  const lerp = (t: number, a: number, b: number) => a + t * (b - a);
  const grad = (hash: number, x: number, y: number, z: number) => {
    const h = hash & 15;
    const u = h < 8 ? x : y;
    const v = h < 4 ? y : h === 12 || h === 14 ? x : z;
    return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
  };
  return function noise3d(x: number, y: number, z: number): number {
    const X = Math.floor(x) & 255;
    const Y = Math.floor(y) & 255;
    const Z = Math.floor(z) & 255;
    x -= Math.floor(x);
    y -= Math.floor(y);
    z -= Math.floor(z);
    const u = fade(x);
    const v = fade(y);
    const w = fade(z);
    const A = p[X] + Y, AA = p[A] + Z, AB = p[A + 1] + Z;
    const B = p[X + 1] + Y, BA = p[B] + Z, BB = p[B + 1] + Z;
    return lerp(
      w,
      lerp(
        v,
        lerp(u, grad(p[AA], x, y, z), grad(p[BA], x - 1, y, z)),
        lerp(u, grad(p[AB], x, y - 1, z), grad(p[BB], x - 1, y - 1, z))
      ),
      lerp(
        v,
        lerp(u, grad(p[AA + 1], x, y, z - 1), grad(p[BA + 1], x - 1, y, z - 1)),
        lerp(u, grad(p[AB + 1], x, y - 1, z - 1), grad(p[BB + 1], x - 1, y - 1, z - 1))
      )
    );
  };
}

const noise3d = createNoise3D();

function fbm(x: number, y: number, z: number): number {
  let total = 0;
  let amplitude = 1;
  let weight = 0;
  let freq = 1;
  for (let i = 0; i < 2; i++) {
    total += amplitude * noise3d(x * freq, y * freq, z * freq);
    weight += amplitude;
    amplitude *= 0.5;
    freq *= 2;
  }
  return total / weight;
}

function parseColorToRgb(colorStr: string, fallback: [number, number, number]): [number, number, number] {
  if (!colorStr || colorStr === 'transparent') return fallback;
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(colorStr.trim()) ||
                /^#?([a-f\d])([a-f\d])([a-f\d])$/i.exec(colorStr.trim());
  if (!match) return fallback;
  if (match[1].length === 1) {
    return [
      parseInt(match[1] + match[1], 16),
      parseInt(match[2] + match[2], 16),
      parseInt(match[3] + match[3], 16),
    ];
  }
  return [
    parseInt(match[1], 16),
    parseInt(match[2], 16),
    parseInt(match[3], 16),
  ];
}

const WAVE_SPEED = 0.42;
const WAVE_FRICTION = 0.94;
const WAVE_DECAY = 0.972;
const SETTLED_THRESHOLD = 0.005;

export default function ShapeWaves({
  text = '',
  fontFamily = 'Geist, "Geist Sans", system-ui, sans-serif',
  fontWeight = 500,
  textSize = 0.6,
  shapes = 'mixed',
  cellSize = 12,
  dotSize = 0.75,
  color = '#A855F7',
  hoverColor = '#ffffff',
  backgroundColor = 'transparent',
  speed = 1,
  scale = 1,
  contrast = 1,
  brightness = 0.4,
  flow = 0,
  direction = 0,
  fade = 0.25,
  interactive = true,
  splashRadius = 40,
  splashStrength = 0.4,
  glow = 0.35,
  intro = true,
  introDuration = 1.6,
  introKey = 0,
  paused = false,
  onError,
  className = '',
}: ShapeWavesProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);

  const propsRef = useRef({
    text,
    fontFamily,
    fontWeight,
    textSize,
    shapes,
    cellSize,
    dotSize,
    color,
    hoverColor,
    backgroundColor,
    speed,
    scale,
    contrast,
    brightness,
    flow,
    direction,
    fade,
    interactive,
    splashRadius,
    splashStrength,
    glow,
    intro,
    introDuration,
    introKey,
    paused,
  });

  propsRef.current = {
    text,
    fontFamily,
    fontWeight,
    textSize,
    shapes,
    cellSize,
    dotSize,
    color,
    hoverColor,
    backgroundColor,
    speed,
    scale,
    contrast,
    brightness,
    flow,
    direction,
    fade,
    interactive,
    splashRadius,
    splashStrength,
    glow,
    intro,
    introDuration,
    introKey,
    paused,
  };

  useEffect(() => {
    const root = rootRef.current;
    const canvas = canvasRef.current;
    if (!root || !canvas) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) {
      onError?.(new Error('Canvas 2D context is not available'));
      return;
    }

    let animationFrameId = 0;
    let disposed = false;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let cols = 1;
    let rows = 1;
    let actualCellPx = cellSize;
    let originX = 0;
    let originY = 0;

    let charges = new Float32Array(1);
    let heights = new Float32Array(1);
    let previousHeights = new Float32Array(1);
    let chargesActive = false;

    let time = 0;
    let driftX = 0;
    let driftY = 0;
    let lastTime = performance.now();
    let introStartTime = performance.now();

    // Text mask canvas
    const maskCanvas = document.createElement('canvas');
    const maskCtx = maskCanvas.getContext('2d');
    let hasMask = false;

    const updateMask = () => {
      const current = propsRef.current;
      const content = current.text.trim();
      hasMask = content.length > 0;
      if (!hasMask || !maskCtx) return;

      const maskW = Math.max(1, Math.round(width));
      const maskH = Math.max(1, Math.round(height));
      maskCanvas.width = maskW;
      maskCanvas.height = maskH;

      maskCtx.clearRect(0, 0, maskW, maskH);
      maskCtx.fillStyle = '#000000';
      maskCtx.fillRect(0, 0, maskW, maskH);

      let fontPx = Math.max(12, current.textSize * maskH);
      maskCtx.font = `${current.fontWeight} ${fontPx}px ${current.fontFamily}`;
      const measured = maskCtx.measureText(content).width;
      const maxW = maskW * 0.9;
      if (measured > maxW) {
        fontPx = Math.max(10, (fontPx * maxW) / measured);
        maskCtx.font = `${current.fontWeight} ${fontPx}px ${current.fontFamily}`;
      }
      maskCtx.textAlign = 'center';
      maskCtx.textBaseline = 'middle';
      maskCtx.fillStyle = '#ffffff';
      maskCtx.fillText(content, maskW / 2, maskH / 2);
    };

    const setupDimensions = () => {
      const rect = root.getBoundingClientRect();
      width = Math.max(10, rect.width);
      height = Math.max(10, rect.height);
      dpr = Math.min(window.devicePixelRatio || 1, 2);

      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const targetCell = Math.max(4, propsRef.current.cellSize);
      cols = Math.max(1, Math.round(width / targetCell));
      actualCellPx = width / cols;
      rows = Math.max(1, Math.floor(height / actualCellPx));
      originX = 0;
      originY = (height - rows * actualCellPx) / 2;

      const totalCells = cols * rows;
      if (charges.length !== totalCells) {
        charges = new Float32Array(totalCells);
        heights = new Float32Array(totalCells);
        previousHeights = new Float32Array(totalCells);
      }

      updateMask();
    };

    setupDimensions();
    setReady(true);

    const resizeObserver = new ResizeObserver(() => {
      setupDimensions();
    });
    resizeObserver.observe(root);

    // Splash ripple physics
    const splash = (x: number, y: number, strength: number) => {
      const current = propsRef.current;
      const sigma = Math.max(0.5, (current.splashRadius / actualCellPx) * 0.5);
      const reach = Math.ceil(sigma * 2.5);
      const centerCol = (x - originX) / actualCellPx - 0.5;
      const centerRow = (y - originY) / actualCellPx - 0.5;

      const minRow = Math.max(0, Math.floor(centerRow - reach));
      const maxRow = Math.min(rows - 1, Math.ceil(centerRow + reach));
      const minCol = Math.max(0, Math.floor(centerCol - reach));
      const maxCol = Math.min(cols - 1, Math.ceil(centerCol + reach));

      for (let r = minRow; r <= maxRow; r++) {
        const dy = r - centerRow;
        for (let c = minCol; c <= maxCol; c++) {
          const dx = c - centerCol;
          const bump = strength * Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
          const idx = r * cols + c;
          heights[idx] = Math.min(1.5, heights[idx] + bump);
        }
      }
      chargesActive = true;
    };

    const handlePointerMove = (e: PointerEvent | MouseEvent) => {
      if (!propsRef.current.interactive) return;
      const rect = root.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (x >= 0 && x <= width && y >= 0 && y <= height) {
        splash(x, y, propsRef.current.splashStrength);
      }
    };

    window.addEventListener('pointermove', handlePointerMove, { passive: true });

    // Step ripple simulation
    const stepRipples = () => {
      const lastCol = cols - 1;
      const lastRow = rows - 1;
      let peak = 0;

      for (let r = 0; r < rows; r++) {
        const up = (r === 0 ? r : r - 1) * cols;
        const down = (r === lastRow ? r : r + 1) * cols;
        const base = r * cols;

        for (let c = 0; c < cols; c++) {
          const idx = base + c;
          const left = base + (c === 0 ? c : c - 1);
          const right = base + (c === lastCol ? c : c + 1);

          const h = heights[idx];
          const laplacian = heights[left] + heights[right] + heights[up + c] + heights[down + c] - 4 * h;
          const velocity = (h - previousHeights[idx]) * WAVE_FRICTION;
          const next = (h + velocity + WAVE_SPEED * laplacian) * WAVE_DECAY;

          previousHeights[idx] = next;
          const charge = Math.min(1, Math.max(0, next));
          charges[idx] = charge;
          if (charge > peak) peak = charge;
        }
      }

      const swap = heights;
      heights = previousHeights;
      previousHeights = swap;

      if (peak < SETTLED_THRESHOLD) {
        heights.fill(0);
        previousHeights.fill(0);
        charges.fill(0);
        chargesActive = false;
      }
    };

    // Main animation loop
    const render = (now: number) => {
      if (disposed) return;

      const current = propsRef.current;
      const deltaSeconds = Math.min(0.1, (now - lastTime) / 1000);
      lastTime = now;

      if (!current.paused && current.speed > 0) {
        time += deltaSeconds * 0.15 * current.speed;
        const angle = (current.direction * Math.PI) / 180;
        const dist = current.flow * actualCellPx * deltaSeconds;
        driftX += Math.cos(angle) * dist;
        driftY += Math.sin(angle) * dist;
      }

      if (chargesActive) {
        stepRipples();
      }

      const introProgress = current.intro
        ? Math.min(1.5, (now - introStartTime) / 1000 / current.introDuration)
        : 1.5;

      ctx.save();
      ctx.scale(dpr, dpr);

      // Background clearing / filling
      if (current.backgroundColor && current.backgroundColor !== 'transparent') {
        ctx.fillStyle = current.backgroundColor;
        ctx.fillRect(0, 0, width, height);
      } else {
        ctx.clearRect(0, 0, width, height);
      }

      const baseRgb = parseColorToRgb(current.color, [168, 85, 247]);
      const hoverRgb = parseColorToRgb(current.hoverColor, [244, 114, 182]);
      const baseDotFraction = Math.max(0.1, Math.min(1, current.dotSize));
      const mode = current.shapes;

      // Mask pixel data if text cutout is active
      let maskData: Uint8ClampedArray | null = null;
      if (hasMask && maskCtx) {
        try {
          maskData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height).data;
        } catch {
          maskData = null;
        }
      }

      const cxHalf = width * 0.5;
      const cyHalf = height * 0.5;
      const noiseScale = Math.max(0.001, 1 / (320 * current.scale));

      for (let r = 0; r < rows; r++) {
        const cellY = originY + (r + 0.5) * actualCellPx;
        const rIdx = r * cols;

        for (let c = 0; c < cols; c++) {
          const cellX = originX + (c + 0.5) * actualCellPx;
          const idx = rIdx + c;

          // Check text cutout mask
          if (hasMask && maskData) {
            const mx = Math.floor((cellX / width) * maskCanvas.width);
            const my = Math.floor((cellY / height) * maskCanvas.height);
            if (mx >= 0 && mx < maskCanvas.width && my >= 0 && my < maskCanvas.height) {
              const pIdx = (my * maskCanvas.width + mx) * 4;
              if (maskData[pIdx] > 128) {
                continue; // Cutout
              }
            }
          }

          // Radial edge fade
          let alphaLevel = 1.0;
          if (current.fade > 0) {
            const nx = Math.abs(cellX / width - 0.5) * 2;
            const ny = Math.abs(cellY / height - 0.5) * 2;
            const dist = Math.sqrt(nx * nx + ny * ny);
            alphaLevel = Math.max(0, 1 - Math.pow(dist, 2) * current.fade * 2);
          }
          if (alphaLevel <= 0.01) continue;

          // Perlin noise calculation
          const sampleX = (cellX + driftX) * noiseScale + 12.9898;
          const sampleY = (cellY + driftY) * noiseScale + 78.233;
          const nVal = fbm(sampleX, sampleY, time);
          const tone = Math.min(1, Math.max(0, (nVal * 0.5 + 0.5 - current.brightness) * current.contrast + 0.5));
          const band = Math.min(2, Math.floor(tone * 3));

          // Ripple charge calculation
          const charge = charges[idx] || 0;
          const stepped = (band + Math.floor(charge * 3)) % 3;

          // Shape and size determination
          let shapeType = 2 - stepped; // 0: square, 1: circle, 2: triangle
          let sizeMultiplier = 1.0;
          if (mode === 'squares') {
            shapeType = 0;
            sizeMultiplier = 0.5 + (stepped / 2) * 0.5;
          } else if (mode === 'circles') {
            shapeType = 1;
            sizeMultiplier = 0.5 + (stepped / 2) * 0.5;
          } else if (mode === 'triangles') {
            shapeType = 2;
            sizeMultiplier = 0.5 + (stepped / 2) * 0.5;
          }

          let drawSize = (actualCellPx * 0.5) * baseDotFraction * sizeMultiplier;

          // Intro pop-in animation
          if (current.intro && introProgress < 1.4) {
            const dxNorm = (cellX - cxHalf) / cxHalf;
            const dyNorm = (cellY - cyHalf) / cyHalf;
            const distFromCenter = Math.sqrt(dxNorm * dxNorm + dyNorm * dyNorm);
            const introDelay = distFromCenter * 0.5;
            const progress = Math.max(0, Math.min(1, (introProgress - introDelay) / 0.3));
            if (progress <= 0) continue;
            drawSize *= Math.sin(progress * Math.PI * 0.5);
          }

          if (drawSize < 0.5) continue;

          // Color interpolation
          const chargeFactor = Math.min(1, charge * 1.5);
          const rCol = Math.round(baseRgb[0] + (hoverRgb[0] - baseRgb[0]) * chargeFactor);
          const gCol = Math.round(baseRgb[1] + (hoverRgb[1] - baseRgb[1]) * chargeFactor);
          const bCol = Math.round(baseRgb[2] + (hoverRgb[2] - baseRgb[2]) * chargeFactor);
          const finalAlpha = alphaLevel * (0.55 + 0.45 * (tone * 0.6 + chargeFactor * 0.4));

          ctx.fillStyle = `rgba(${rCol}, ${gCol}, ${bCol}, ${finalAlpha})`;

          // Draw shape
          ctx.beginPath();
          if (shapeType === 0) {
            // Square / Rounded Rect
            const s = drawSize * 1.8;
            ctx.rect(cellX - s * 0.5, cellY - s * 0.5, s, s);
          } else if (shapeType === 1) {
            // Circle
            ctx.arc(cellX, cellY, drawSize, 0, Math.PI * 2);
          } else {
            // Triangle (Isosceles)
            const rTri = drawSize * 1.25;
            ctx.moveTo(cellX, cellY - rTri);
            ctx.lineTo(cellX + rTri * 0.866, cellY + rTri * 0.5);
            ctx.lineTo(cellX - rTri * 0.866, cellY + rTri * 0.5);
            ctx.closePath();
          }
          ctx.fill();
        }
      }

      ctx.restore();
      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      disposed = true;
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      window.removeEventListener('pointermove', handlePointerMove);
    };
  }, [introKey]);

  return (
    <div
      ref={rootRef}
      className={`shape-waves ${className}`}
      data-ready={ready}
      style={{ backgroundColor }}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} className="shape-waves__canvas" />
    </div>
  );
}
