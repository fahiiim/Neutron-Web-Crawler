import { useEffect, useRef } from 'react';
import * as THREE from 'three';

interface NeutronStarCanvasProps {
  dimmed: boolean;
  pulseSignal: number;
}

const STAR_VERTEX_SHADER = /* glsl */ `
  varying vec3 vNormalWorld;
  varying vec3 vViewDir;
  varying vec3 vLocalPos;

  void main() {
    vLocalPos = normalize(position);
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vNormalWorld = normalize(mat3(modelMatrix) * normal);
    vViewDir = normalize(cameraPosition - worldPos.xyz);
    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`;

const STAR_FRAGMENT_SHADER = /* glsl */ `
  uniform float uTime;
  uniform vec3 uMagAxis;
  uniform float uOpacity;

  varying vec3 vNormalWorld;
  varying vec3 vViewDir;
  varying vec3 vLocalPos;

  float hash3(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }

  float noise3(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash3(i + vec3(0,0,0)), hash3(i + vec3(1,0,0)), f.x),
          mix(hash3(i + vec3(0,1,0)), hash3(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash3(i + vec3(0,0,1)), hash3(i + vec3(1,0,1)), f.x),
          mix(hash3(i + vec3(0,1,1)), hash3(i + vec3(1,1,1)), f.x), f.y),
      f.z
    );
  }

  float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; i++) {
      v += a * noise3(p);
      p = p * 2.05 + vec3(1.7, 9.2, 4.3);
      a *= 0.5;
    }
    return v;
  }

  void main() {
    vec3 N = normalize(vNormalWorld);
    vec3 V = normalize(vViewDir);
    float ndotv = clamp(dot(N, V), 0.0, 1.0);

    float swirl = fbm(vLocalPos * 4.2 + vec3(uTime * 0.22, -uTime * 0.14, uTime * 0.1));
    float magAlign = abs(dot(normalize(vLocalPos), normalize(uMagAxis)));
    float polarCap = smoothstep(0.72, 0.99, magAlign);
    float fresnel = pow(1.0 - ndotv, 2.4);

    vec3 plasmaBlue = vec3(0.45, 0.72, 1.0);
    vec3 coreWhite = vec3(0.98, 0.99, 1.0);

    vec3 color = mix(plasmaBlue, coreWhite, 0.65 + 0.35 * swirl + polarCap * 0.5);
    color += vec3(0.75, 0.88, 1.0) * fresnel * 1.1;

    gl_FragColor = vec4(color, uOpacity);
  }
`;

const CORONA_VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const CORONA_FRAGMENT_SHADER = /* glsl */ `
  uniform float uPulse;
  uniform float uOpacity;
  varying vec2 vUv;

  void main() {
    vec2 centered = (vUv - 0.5) * 2.0;
    float r = length(centered);
    float inner = exp(-r * r * 16.0) * 1.05;
    float mid = exp(-r * 3.6) * 0.48;
    float outer = exp(-r * 1.7) * 0.16;
    float mask = smoothstep(1.0, 0.12, r);
    float intensity = (inner + mid + outer) * mask * (0.95 + 0.07 * uPulse);
    vec3 col = mix(vec3(0.42, 0.58, 1.0), vec3(0.98, 0.99, 1.0), clamp(inner * 1.15, 0.0, 1.0));
    gl_FragColor = vec4(col * intensity, intensity * uOpacity);
  }
`;

const POINT_VERTEX_SHADER = /* glsl */ `
  attribute float aSize;
  attribute vec3 aColor;
  attribute float aAlpha;
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * (250.0 / max(1.0, -mvPos.z));
    gl_Position = projectionMatrix * mvPos;
  }
`;

const POINT_FRAGMENT_SHADER = /* glsl */ `
  uniform float uMasterOpacity;
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d2 = dot(c, c);
    if (d2 > 0.25) discard;
    float soft = exp(-d2 * 18.0);
    gl_FragColor = vec4(vColor, soft * vAlpha * uMasterOpacity);
  }
`;

interface Streamer {
  kind: 'orbit' | 'flux';
  r: number;
  angle: number;
  angularSpeed: number;
  tiltPlane: number;
  yAmp: number;
  phase: number;
  curlAmp: number;
  curlFreq: number;
  // For magnetic flux ribbons
  phi: number;
  theta: number;
  thetaSpeed: number;
  loopScale: number;
  // Trail history ring (TRAIL_LEN * 3)
  trail: Float32Array;
  color: THREE.Color;
}

export function NeutronStarCanvas({ dimmed, pulseSignal }: NeutronStarCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef({ dimmed });
  stateRef.current = { dimmed };

  const pulseTargetRef = useRef(0);
  useEffect(() => {
    if (pulseSignal > 0) pulseTargetRef.current = 1.0;
  }, [pulseSignal]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const prefersReducedMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)'
    ).matches;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
      });
    } catch {
      return;
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x000000, 1);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      44,
      container.clientWidth / Math.max(1, container.clientHeight),
      0.1,
      100
    );
    camera.position.set(0, 0, 12.5);

    // Master system group (continuously drifting)
    const systemGroup = new THREE.Group();
    scene.add(systemGroup);

    // Tilted spin frame matching the reference perspective (~24 deg tilt)
    const axisPivot = new THREE.Group();
    axisPivot.rotation.z = 0.22;
    axisPivot.rotation.x = 0.44;
    systemGroup.add(axisPivot);

    const spinGroup = new THREE.Group();
    axisPivot.add(spinGroup);

    const magAxisLocal = new THREE.Vector3(Math.sin(0.62), Math.cos(0.62), 0).normalize();

    // 1. Central White-Blue Luminous Star Core
    const starUniforms = {
      uTime: { value: 0 },
      uMagAxis: { value: magAxisLocal },
      uOpacity: { value: 1.0 },
    };
    const starGeo = new THREE.SphereGeometry(0.84, 48, 48);
    const starMat = new THREE.ShaderMaterial({
      vertexShader: STAR_VERTEX_SHADER,
      fragmentShader: STAR_FRAGMENT_SHADER,
      uniforms: starUniforms,
      transparent: true,
    });
    const starMesh = new THREE.Mesh(starGeo, starMat);
    spinGroup.add(starMesh);

    // 2. Soft Volumetric White-Blue Corona Halo
    const coronaUniforms = {
      uPulse: { value: 0 },
      uOpacity: { value: 0.95 },
    };
    const coronaGeo = new THREE.PlaneGeometry(5.8, 5.8);
    const coronaMat = new THREE.ShaderMaterial({
      vertexShader: CORONA_VERTEX_SHADER,
      fragmentShader: CORONA_FRAGMENT_SHADER,
      uniforms: coronaUniforms,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const coronaMesh = new THREE.Mesh(coronaGeo, coronaMat);
    systemGroup.add(coronaMesh);

    // 3. Swirling Ribbon Streamlines + Leading Particles (like the reference GIF!)
    const isMobile = container.clientWidth < 768;
    const STREAMER_COUNT = isMobile ? 120 : 220;
    const TRAIL_LEN = 32; // vertices per ribbon
    const SEGMENTS_PER_STREAMER = TRAIL_LEN - 1;
    const TOTAL_SEG_VERTS = STREAMER_COUNT * SEGMENTS_PER_STREAMER * 2;

    const paletteBlue = [
      new THREE.Color('#e0f2fe'),
      new THREE.Color('#93c5fd'),
      new THREE.Color('#818cf8'),
      new THREE.Color('#60a5fa'),
      new THREE.Color('#a5b4fc'),
    ];
    const paletteCrimson = [
      new THREE.Color('#f87171'),
      new THREE.Color('#ef4444'),
      new THREE.Color('#fb7185'),
      new THREE.Color('#fca5a5'),
    ];

    const streamers: Streamer[] = [];

    const computeStreamerPos = (s: Streamer, t: number, out: [number, number, number]) => {
      if (s.kind === 'orbit') {
        const wob = Math.sin(s.angle * s.curlFreq + t * 1.4 + s.phase) * s.curlAmp;
        const rx = s.r + wob;
        const rz = (s.r * 0.88) + wob * 0.7;
        const x = Math.cos(s.angle) * rx;
        const z = Math.sin(s.angle) * rz;
        const y =
          Math.sin(s.angle * 2.0 + s.phase) * s.yAmp +
          Math.sin(s.angle) * s.tiltPlane * s.r * 0.35;
        out[0] = x;
        out[1] = y;
        out[2] = z;
      } else {
        // Curved 3D magnetic flux & reconnection filament arcing from polar region
        const sinT = Math.sin(s.theta);
        const r = s.loopScale * sinT * sinT + 0.65;
        const curl =
          Math.sin(s.theta * 7.0 + t * 3.0 + s.phase) *
          s.curlAmp *
          Math.sin(s.theta);
        const x = (r + curl) * sinT * Math.cos(s.phi);
        const y = r * Math.cos(s.theta) + curl * 0.45;
        const z = (r + curl) * sinT * Math.sin(s.phi);
        // Align roughly along the horizontal magnetic lobe axis for the butterfly vortex look
        out[0] = y * 0.92 - x * 0.38;
        out[1] = x * 0.92 + y * 0.38;
        out[2] = z;
      }
    };

    const tempPos: [number, number, number] = [0, 0, 0];

    for (let i = 0; i < STREAMER_COUNT; i++) {
      const isOrbit = i < Math.floor(STREAMER_COUNT * 0.64);
      const isCrimson = isOrbit ? Math.random() < 0.34 : Math.random() < 0.18;
      const color = isCrimson
        ? paletteCrimson[Math.floor(Math.random() * paletteCrimson.length)]
        : paletteBlue[Math.floor(Math.random() * paletteBlue.length)];

      const frac = Math.pow(Math.random(), 0.9);
      const r = 1.25 + frac * 4.4;
      const s: Streamer = {
        kind: isOrbit ? 'orbit' : 'flux',
        r,
        angle: Math.random() * Math.PI * 2,
        angularSpeed: (isOrbit ? 1.55 / Math.pow(r, 0.8) : 0) * (Math.random() * 0.4 + 0.8),
        tiltPlane: (Math.random() - 0.5) * 0.65,
        yAmp: (Math.random() - 0.5) * 0.55,
        phase: Math.random() * Math.PI * 2,
        curlAmp: isOrbit ? Math.random() * 0.22 : 0.18 + Math.random() * 0.28,
        curlFreq: 2 + Math.floor(Math.random() * 3),
        phi: Math.random() * Math.PI * 2,
        theta: 0.18 + Math.random() * (Math.PI - 0.36),
        thetaSpeed: (0.75 + Math.random() * 0.85) * (Math.random() < 0.5 ? 1 : -1),
        loopScale: 1.8 + Math.random() * 3.4,
        trail: new Float32Array(TRAIL_LEN * 3),
        color,
      };

      // Pre-fill smooth initial curved trail so first frame already shows full vortex!
      for (let k = TRAIL_LEN - 1; k >= 0; k--) {
        computeStreamerPos(s, k * 0.02, tempPos);
        s.trail[k * 3] = tempPos[0];
        s.trail[k * 3 + 1] = tempPos[1];
        s.trail[k * 3 + 2] = tempPos[2];
        if (s.kind === 'orbit') {
          s.angle += s.angularSpeed * 0.018;
        } else {
          s.theta += s.thetaSpeed * 0.018;
          s.phi += 0.01;
          if (s.theta > Math.PI - 0.15) s.theta = 0.2;
          if (s.theta < 0.15) s.theta = Math.PI - 0.2;
        }
      }
      streamers.push(s);
    }

    const linePositions = new Float32Array(TOTAL_SEG_VERTS * 3);
    const lineColors = new Float32Array(TOTAL_SEG_VERTS * 3);

    // Pre-populate static fade gradient in lineColors
    for (let i = 0; i < STREAMER_COUNT; i++) {
      const col = streamers[i].color;
      for (let seg = 0; seg < SEGMENTS_PER_STREAMER; seg++) {
        const t0 = Math.pow(1 - seg / SEGMENTS_PER_STREAMER, 1.55) * 0.88;
        const t1 = Math.pow(1 - (seg + 1) / SEGMENTS_PER_STREAMER, 1.55) * 0.88;
        const baseIdx = (i * SEGMENTS_PER_STREAMER + seg) * 6;
        lineColors[baseIdx] = col.r * t0;
        lineColors[baseIdx + 1] = col.g * t0;
        lineColors[baseIdx + 2] = col.b * t0;
        lineColors[baseIdx + 3] = col.r * t1;
        lineColors[baseIdx + 4] = col.g * t1;
        lineColors[baseIdx + 5] = col.b * t1;
      }
    }

    const lineGeo = new THREE.BufferGeometry();
    const linePosAttr = new THREE.BufferAttribute(linePositions, 3);
    linePosAttr.setUsage(THREE.DynamicDrawUsage);
    lineGeo.setAttribute('position', linePosAttr);
    lineGeo.setAttribute('color', new THREE.BufferAttribute(lineColors, 3));

    const lineMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const ribbonLines = new THREE.LineSegments(lineGeo, lineMat);
    axisPivot.add(ribbonLines);

    // Leading glowing particle heads for each streamer
    const headPositions = new Float32Array(STREAMER_COUNT * 3);
    const headColors = new Float32Array(STREAMER_COUNT * 3);
    const headSizes = new Float32Array(STREAMER_COUNT);
    const headAlphas = new Float32Array(STREAMER_COUNT);
    for (let i = 0; i < STREAMER_COUNT; i++) {
      const c = streamers[i].color;
      headColors[i * 3] = c.r;
      headColors[i * 3 + 1] = c.g;
      headColors[i * 3 + 2] = c.b;
      headSizes[i] = 0.22 + Math.random() * 0.14;
      headAlphas[i] = 0.95;
    }

    const headGeo = new THREE.BufferGeometry();
    const headPosAttr = new THREE.BufferAttribute(headPositions, 3);
    headPosAttr.setUsage(THREE.DynamicDrawUsage);
    headGeo.setAttribute('position', headPosAttr);
    headGeo.setAttribute('aColor', new THREE.BufferAttribute(headColors, 3));
    headGeo.setAttribute('aSize', new THREE.BufferAttribute(headSizes, 1));
    headGeo.setAttribute('aAlpha', new THREE.BufferAttribute(headAlphas, 1));

    const pointUniforms = { uMasterOpacity: { value: 1.0 } };
    const headMat = new THREE.ShaderMaterial({
      vertexShader: POINT_VERTEX_SHADER,
      fragmentShader: POINT_FRAGMENT_SHADER,
      uniforms: pointUniforms,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const headPoints = new THREE.Points(headGeo, headMat);
    axisPivot.add(headPoints);

    // 4. Dense Fine Concentric Dust Specks (matching the subtle granular galaxy halo)
    const dustCount = isMobile ? 420 : 880;
    const dustRadii = new Float32Array(dustCount);
    const dustAngles = new Float32Array(dustCount);
    const dustSpeeds = new Float32Array(dustCount);
    const dustPositions = new Float32Array(dustCount * 3);
    const dustColors = new Float32Array(dustCount * 3);
    const dustSizes = new Float32Array(dustCount);
    const dustAlphas = new Float32Array(dustCount);
    const dustY = new Float32Array(dustCount);

    for (let i = 0; i < dustCount; i++) {
      const frac = Math.pow(Math.random(), 1.2);
      const r = 1.2 + frac * 5.2;
      const a = Math.random() * Math.PI * 2;
      const y = (Math.random() - 0.5) * (0.3 + frac * 1.1);
      dustRadii[i] = r;
      dustAngles[i] = a;
      dustSpeeds[i] = 0.65 / Math.pow(r, 0.9);
      dustY[i] = y;
      dustPositions[i * 3] = Math.cos(a) * r;
      dustPositions[i * 3 + 1] = y;
      dustPositions[i * 3 + 2] = Math.sin(a) * r * 0.88;

      const isWarm = Math.random() < 0.2;
      const col = isWarm ? paletteCrimson[0] : paletteBlue[i % paletteBlue.length];
      dustColors[i * 3] = col.r;
      dustColors[i * 3 + 1] = col.g;
      dustColors[i * 3 + 2] = col.b;
      dustSizes[i] = 0.09 + Math.random() * 0.08;
      dustAlphas[i] = 0.25 + (1 - frac) * 0.42;
    }

    const dustGeo = new THREE.BufferGeometry();
    const dustPosAttr = new THREE.BufferAttribute(dustPositions, 3);
    dustPosAttr.setUsage(THREE.DynamicDrawUsage);
    dustGeo.setAttribute('position', dustPosAttr);
    dustGeo.setAttribute('aColor', new THREE.BufferAttribute(dustColors, 3));
    dustGeo.setAttribute('aSize', new THREE.BufferAttribute(dustSizes, 1));
    dustGeo.setAttribute('aAlpha', new THREE.BufferAttribute(dustAlphas, 1));

    const dustPoints = new THREE.Points(dustGeo, headMat);
    axisPivot.add(dustPoints);

    // Mouse parallax
    let mouseX = 0;
    let mouseY = 0;
    const onMouseMove = (e: MouseEvent) => {
      mouseX = (e.clientX / Math.max(1, window.innerWidth) - 0.5) * 2;
      mouseY = (e.clientY / Math.max(1, window.innerHeight) - 0.5) * 2;
    };
    window.addEventListener('mousemove', onMouseMove, { passive: true });

    const onResize = () => {
      if (!container) return;
      const w = container.clientWidth;
      const h = Math.max(1, container.clientHeight);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', onResize);

    let rafId: number | null = null;
    let lastTime = performance.now();
    let elapsed = 0;
    let spinBoost = 0;
    let currentDimFactor = 1.0;

    const writeTrailsToBuffers = () => {
      for (let i = 0; i < STREAMER_COUNT; i++) {
        const tBuf = streamers[i].trail;
        headPositions[i * 3] = tBuf[0];
        headPositions[i * 3 + 1] = tBuf[1];
        headPositions[i * 3 + 2] = tBuf[2];

        for (let seg = 0; seg < SEGMENTS_PER_STREAMER; seg++) {
          const outIdx = (i * SEGMENTS_PER_STREAMER + seg) * 6;
          const p0 = seg * 3;
          const p1 = (seg + 1) * 3;
          linePositions[outIdx] = tBuf[p0];
          linePositions[outIdx + 1] = tBuf[p0 + 1];
          linePositions[outIdx + 2] = tBuf[p0 + 2];
          linePositions[outIdx + 3] = tBuf[p1];
          linePositions[outIdx + 4] = tBuf[p1 + 1];
          linePositions[outIdx + 5] = tBuf[p1 + 2];
        }
      }
      linePosAttr.needsUpdate = true;
      headPosAttr.needsUpdate = true;
    };

    writeTrailsToBuffers();

    const animate = (now: number) => {
      const dt = Math.min(0.05, Math.max(0.001, (now - lastTime) / 1000));
      lastTime = now;

      if (!prefersReducedMotion) {
        elapsed += dt;
      }

      if (pulseTargetRef.current > 0.01) {
        spinBoost = 1.5;
        pulseTargetRef.current = 0;
      }
      spinBoost += (0 - spinBoost) * Math.min(1, dt * 1.5);

      const { dimmed: isDimmed } = stateRef.current;
      const targetDim = isDimmed ? 0.34 : 1.0;
      currentDimFactor += (targetDim - currentDimFactor) * Math.min(1, dt * 3.0);

      // Continuous moving orbital drift
      const driftX = Math.cos(elapsed * 0.16) * 1.15 + mouseX * 0.42;
      const baseTargetY = isDimmed ? 1.25 : -0.15;
      const driftY = baseTargetY + Math.sin(elapsed * 0.22) * 0.38 - mouseY * 0.3;
      const driftZ = (isDimmed ? -2.4 : 0.0) + Math.sin(elapsed * 0.14) * 0.4;

      systemGroup.position.x += (driftX - systemGroup.position.x) * Math.min(1, dt * 2.2);
      systemGroup.position.y += (driftY - systemGroup.position.y) * Math.min(1, dt * 2.2);
      systemGroup.position.z += (driftZ - systemGroup.position.z) * Math.min(1, dt * 2.2);

      axisPivot.rotation.x = 0.44 + Math.sin(elapsed * 0.2) * 0.07 - mouseY * 0.1;
      axisPivot.rotation.z = 0.22 + Math.cos(elapsed * 0.16) * 0.05 + mouseX * 0.1;

      if (!prefersReducedMotion) {
        const speedMult = 1.0 + spinBoost * 1.4;
        spinGroup.rotation.y += dt * (1.8 + spinBoost * 2.0);

        // Advance every streaming filament + shift ring history cleanly
        for (let i = 0; i < STREAMER_COUNT; i++) {
          const s = streamers[i];
          let wrapped = false;

          if (s.kind === 'orbit') {
            s.angle += dt * s.angularSpeed * speedMult;
          } else {
            s.theta += dt * s.thetaSpeed * speedMult;
            s.phi += dt * 0.45 * speedMult;
            if (s.theta > Math.PI - 0.12) {
              s.theta = 0.16;
              wrapped = true;
            } else if (s.theta < 0.12) {
              s.theta = Math.PI - 0.16;
              wrapped = true;
            }
          }

          computeStreamerPos(s, elapsed, tempPos);
          const tBuf = s.trail;
          if (wrapped) {
            // Reset entire trail on pole wrap to avoid straight-line artifact
            for (let k = 0; k < TRAIL_LEN; k++) {
              tBuf[k * 3] = tempPos[0];
              tBuf[k * 3 + 1] = tempPos[1];
              tBuf[k * 3 + 2] = tempPos[2];
            }
          } else {
            tBuf.copyWithin(3, 0, (TRAIL_LEN - 1) * 3);
            tBuf[0] = tempPos[0];
            tBuf[1] = tempPos[1];
            tBuf[2] = tempPos[2];
          }
        }
        writeTrailsToBuffers();

        // Advance background micro-dust
        for (let i = 0; i < dustCount; i++) {
          dustAngles[i] += dt * dustSpeeds[i] * speedMult;
          const a = dustAngles[i];
          const r = dustRadii[i];
          dustPositions[i * 3] = Math.cos(a) * r;
          dustPositions[i * 3 + 2] = Math.sin(a) * r * 0.88;
        }
        dustPosAttr.needsUpdate = true;
      }

      coronaMesh.quaternion.copy(camera.quaternion);

      starUniforms.uTime.value = elapsed;
      starUniforms.uOpacity.value = Math.min(1.0, currentDimFactor + 0.25);
      coronaUniforms.uPulse.value = Math.sin(elapsed * 4.0);
      coronaUniforms.uOpacity.value = 0.92 * currentDimFactor;
      lineMat.opacity = 0.88 * currentDimFactor;
      pointUniforms.uMasterOpacity.value = currentDimFactor;

      renderer.render(scene, camera);

      if (!prefersReducedMotion) {
        rafId = requestAnimationFrame(animate);
      }
    };

    const onVisibility = () => {
      if (document.hidden && rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      } else if (!document.hidden && rafId === null && !prefersReducedMotion) {
        lastTime = performance.now();
        rafId = requestAnimationFrame(animate);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    rafId = requestAnimationFrame(animate);

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('resize', onResize);
      starGeo.dispose();
      starMat.dispose();
      coronaGeo.dispose();
      coronaMat.dispose();
      lineGeo.dispose();
      lineMat.dispose();
      headGeo.dispose();
      headMat.dispose();
      dustGeo.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="fixed inset-0 pointer-events-none z-[1] overflow-hidden"
    />
  );
}
