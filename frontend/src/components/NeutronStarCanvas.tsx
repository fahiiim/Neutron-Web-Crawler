import { useEffect, useRef } from 'react';
import * as THREE from 'three';

interface NeutronStarCanvasProps {
  dimmed: boolean;
  pulseSignal: number;
  lightMode: boolean;
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

  // Lightweight 3D trigonometric FBM for smooth animated plasma surface
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

    // Latitude plasma crust banding + magnetic polar hot spots
    float swirl = fbm(vLocalPos * 4.2 + vec3(uTime * 0.18, -uTime * 0.12, uTime * 0.08));
    float bands = 0.5 + 0.5 * sin(vLocalPos.y * 11.0 + swirl * 4.5);
    float magAlign = abs(dot(normalize(vLocalPos), normalize(uMagAxis)));
    float polarCap = smoothstep(0.76, 0.99, magAlign);

    float fresnel = pow(1.0 - ndotv, 2.8);

    vec3 crustDark = vec3(0.06, 0.14, 0.28);
    vec3 plasmaBlue = vec3(0.32, 0.65, 0.98);
    vec3 coreWhite = vec3(0.92, 0.97, 1.00);

    vec3 color = mix(crustDark, plasmaBlue, smoothstep(0.25, 0.85, swirl * 0.7 + bands * 0.35));
    color = mix(color, coreWhite, polarCap * 0.92 + pow(swirl, 2.6) * 0.45);
    color += vec3(0.55, 0.80, 1.0) * fresnel * 1.15;

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
    float inner = exp(-r * r * 14.0) * 0.85;
    float mid = exp(-r * 3.8) * 0.42;
    float outer = exp(-r * 1.9) * 0.14;
    float mask = smoothstep(1.0, 0.15, r);
    float intensity = (inner + mid + outer) * mask * (0.94 + 0.08 * uPulse);
    vec3 col = mix(vec3(0.24, 0.56, 0.98), vec3(0.92, 0.97, 1.0), clamp(inner * 1.2, 0.0, 1.0));
    gl_FragColor = vec4(col * intensity, intensity * uOpacity);
  }
`;

const JET_VERTEX_SHADER = /* glsl */ `
  varying vec3 vNormalView;
  varying vec3 vViewDir;
  varying float vAxial;

  void main() {
    vAxial = clamp((position.y + 0.5), 0.0, 1.0); // 0 at base, 1 at far tip
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    vNormalView = normalize(normalMatrix * normal);
    vViewDir = normalize(-mvPos.xyz);
    gl_Position = projectionMatrix * mvPos;
  }
`;

const JET_FRAGMENT_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uFlare;
  uniform float uOpacity;

  varying vec3 vNormalView;
  varying vec3 vViewDir;
  varying float vAxial;

  void main() {
    vec3 N = normalize(vNormalView);
    vec3 V = normalize(vViewDir);
    // Volumetric soft cylinder profile: zero opacity at silhouette edges!
    float radialSoft = pow(abs(dot(N, V)), 2.4);
    float axialFade = exp(-vAxial * 3.2) * smoothstep(0.0, 0.06, vAxial);
    float endSoft = smoothstep(1.0, 0.72, vAxial);
    float wave = 0.88 + 0.12 * sin(vAxial * 22.0 - uTime * 7.5);
    float alpha = radialSoft * axialFade * endSoft * wave * 0.40 * uFlare * uOpacity;
    vec3 col = mix(vec3(0.32, 0.66, 1.0), vec3(0.92, 0.97, 1.0), exp(-vAxial * 6.0));
    gl_FragColor = vec4(col * alpha, alpha);
  }
`;

const DISK_VERTEX_SHADER = /* glsl */ `
  attribute float aSize;
  attribute float aHeat;
  varying float vHeat;

  void main() {
    vHeat = aHeat;
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * (220.0 / -mvPos.z);
    gl_Position = projectionMatrix * mvPos;
  }
`;

const DISK_FRAGMENT_SHADER = /* glsl */ `
  uniform float uOpacity;
  varying float vHeat;

  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d2 = dot(c, c);
    if (d2 > 0.25) discard;
    float soft = exp(-d2 * 18.0);
    vec3 cool = vec3(0.24, 0.52, 0.92);
    vec3 hot = vec3(0.88, 0.95, 1.0);
    vec3 col = mix(cool, hot, vHeat);
    gl_FragColor = vec4(col, soft * (0.28 + 0.52 * vHeat) * uOpacity);
  }
`;

export function NeutronStarCanvas({
  dimmed,
  pulseSignal,
  lightMode,
}: NeutronStarCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef({ dimmed, pulseSignal, lightMode });
  stateRef.current = { dimmed, pulseSignal, lightMode };

  const pulseTargetRef = useRef(0);
  useEffect(() => {
    if (pulseSignal > 0) {
      pulseTargetRef.current = 1.0;
    }
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
      return; // Graceful degradation if WebGL unavailable
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      42,
      container.clientWidth / Math.max(1, container.clientHeight),
      0.1,
      100
    );
    camera.position.set(0, 0, 12);

    // Sparse, crisp background stars
    const bgCount = 180;
    const bgPos = new Float32Array(bgCount * 3);
    for (let i = 0; i < bgCount; i++) {
      bgPos[i * 3] = (Math.random() - 0.5) * 32;
      bgPos[i * 3 + 1] = (Math.random() - 0.5) * 20;
      bgPos[i * 3 + 2] = -6 - Math.random() * 14;
    }
    const bgGeo = new THREE.BufferGeometry();
    bgGeo.setAttribute('position', new THREE.BufferAttribute(bgPos, 3));
    const bgMat = new THREE.PointsMaterial({
      color: 0xcbd5e1,
      size: 0.045,
      transparent: true,
      opacity: 0.38,
    });
    const bgStars = new THREE.Points(bgGeo, bgMat);
    scene.add(bgStars);

    // Master moving Neutron Star System group
    const systemGroup = new THREE.Group();
    scene.add(systemGroup);

    // Axial tilt ~23.5 deg
    const axisPivot = new THREE.Group();
    axisPivot.rotation.z = 0.41;
    axisPivot.rotation.x = 0.28;
    systemGroup.add(axisPivot);

    // Spin group rotates continuously around Y
    const spinGroup = new THREE.Group();
    axisPivot.add(spinGroup);

    // Magnetic axis tilted ~38 deg from spin axis
    const magTiltAngle = 0.66;
    const magAxisLocal = new THREE.Vector3(
      Math.sin(magTiltAngle),
      Math.cos(magTiltAngle),
      0
    ).normalize();

    const starUniforms = {
      uTime: { value: 0 },
      uMagAxis: { value: magAxisLocal },
      uOpacity: { value: 1.0 },
    };

    const starGeo = new THREE.SphereGeometry(0.92, 48, 48);
    const starMat = new THREE.ShaderMaterial({
      vertexShader: STAR_VERTEX_SHADER,
      fragmentShader: STAR_FRAGMENT_SHADER,
      uniforms: starUniforms,
      transparent: true,
    });
    const starMesh = new THREE.Mesh(starGeo, starMat);
    spinGroup.add(starMesh);

    // Soft additive volumetric corona billboard
    const coronaUniforms = {
      uPulse: { value: 0 },
      uOpacity: { value: 0.9 },
    };
    const coronaGeo = new THREE.PlaneGeometry(5.6, 5.6);
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

    // Magnetic Group aligned with magnetic axis (rotates with spinGroup)
    const magGroup = new THREE.Group();
    magGroup.rotation.z = -magTiltAngle;
    spinGroup.add(magGroup);

    // Volumetric Relativistic Pulsar Jets (soft Gaussian cylinders, zero hard edges)
    const jetUniforms = {
      uTime: { value: 0 },
      uFlare: { value: 1.0 },
      uOpacity: { value: 0.9 },
    };
    const jetLen = 9.5;
    // CylinderGeometry centered at 0: shift so base starts near core
    const jetGeoTop = new THREE.CylinderGeometry(0.95, 0.14, jetLen, 32, 1, true);
    jetGeoTop.translate(0, jetLen * 0.5 + 0.55, 0);
    // Normalize axial height into position.y [-0.5..0.5] helper attribute or compute in shader?
    // Wait: JET_VERTEX_SHADER expects position.y in [-0.5, 0.5], so keep unit cylinder and scale mesh!
    jetGeoTop.dispose();

    const unitJetGeo = new THREE.CylinderGeometry(0.92, 0.12, 1.0, 32, 1, true);
    const jetMat = new THREE.ShaderMaterial({
      vertexShader: JET_VERTEX_SHADER,
      fragmentShader: JET_FRAGMENT_SHADER,
      uniforms: jetUniforms,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
    });

    const northJet = new THREE.Mesh(unitJetGeo, jetMat);
    northJet.scale.set(1, jetLen, 1);
    northJet.position.y = jetLen * 0.5 + 0.65;
    magGroup.add(northJet);

    const southJet = new THREE.Mesh(unitJetGeo, jetMat);
    southJet.rotation.z = Math.PI;
    southJet.scale.set(1, jetLen, 1);
    southJet.position.y = -(jetLen * 0.5 + 0.65);
    magGroup.add(southJet);

    // 10 Delicate Dipole Magnetic Field Lines (r = L * sin^2(theta))
    const fieldLinesGroup = new THREE.Group();
    const fieldLineMat = new THREE.LineBasicMaterial({
      color: 0x7dd3fc,
      transparent: true,
      opacity: 0.16,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const lineCount = 10;
    const L = 3.2;
    const steps = 44;
    for (let l = 0; l < lineCount; l++) {
      const phi = (l / lineCount) * Math.PI * 2;
      const pts: THREE.Vector3[] = [];
      for (let s = 0; s <= steps; s++) {
        const theta = 0.24 + (s / steps) * (Math.PI - 0.48);
        const sinT = Math.sin(theta);
        const r = L * sinT * sinT;
        pts.push(
          new THREE.Vector3(
            r * sinT * Math.cos(phi),
            r * Math.cos(theta),
            r * sinT * Math.sin(phi)
          )
        );
      }
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
      fieldLinesGroup.add(new THREE.Line(lineGeo, fieldLineMat));
    }
    magGroup.add(fieldLinesGroup);

    // Equatorial Keplerian Accretion Torus (520 soft Gaussian points)
    const isMobile = container.clientWidth < 768;
    const diskCount = isMobile ? 260 : 520;
    const diskRadii = new Float32Array(diskCount);
    const diskAngles = new Float32Array(diskCount);
    const diskSpeeds = new Float32Array(diskCount);
    const diskY = new Float32Array(diskCount);
    const diskPositions = new Float32Array(diskCount * 3);
    const diskSizes = new Float32Array(diskCount);
    const diskHeats = new Float32Array(diskCount);

    for (let i = 0; i < diskCount; i++) {
      const frac = Math.pow(Math.random(), 1.45);
      const r = 1.55 + frac * 2.85;
      const a = Math.random() * Math.PI * 2;
      diskRadii[i] = r;
      diskAngles[i] = a;
      diskSpeeds[i] = 0.9 / Math.pow(r, 1.25);
      diskY[i] = (Math.random() - 0.5) * 0.14;
      diskSizes[i] = Math.random() < 0.08 ? 0.28 : 0.14 + (1 - frac) * 0.08;
      diskHeats[i] = 1.0 - frac * 0.8;

      diskPositions[i * 3] = Math.cos(a) * r;
      diskPositions[i * 3 + 1] = diskY[i];
      diskPositions[i * 3 + 2] = Math.sin(a) * r;
    }

    const diskGeo = new THREE.BufferGeometry();
    const diskPosAttr = new THREE.BufferAttribute(diskPositions, 3);
    diskGeo.setAttribute('position', diskPosAttr);
    diskGeo.setAttribute('aSize', new THREE.BufferAttribute(diskSizes, 1));
    diskGeo.setAttribute('aHeat', new THREE.BufferAttribute(diskHeats, 1));

    const diskUniforms = { uOpacity: { value: 0.85 } };
    const diskMat = new THREE.ShaderMaterial({
      vertexShader: DISK_VERTEX_SHADER,
      fragmentShader: DISK_FRAGMENT_SHADER,
      uniforms: diskUniforms,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const diskPoints = new THREE.Points(diskGeo, diskMat);
    axisPivot.add(diskPoints);

    // Search Shockwave Ring
    const waveGeo = new THREE.RingGeometry(0.95, 1.05, 64);
    const waveMat = new THREE.MeshBasicMaterial({
      color: 0x93c5fd,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const waveMesh = new THREE.Mesh(waveGeo, waveMat);
    waveMesh.rotation.x = Math.PI * 0.5;
    axisPivot.add(waveMesh);

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
    let waveScale = 1.0;
    let waveAlpha = 0.0;
    let currentDimFactor = 1.0;

    const animate = (now: number) => {
      const dt = Math.min(0.05, Math.max(0.001, (now - lastTime) / 1000));
      lastTime = now;

      if (!prefersReducedMotion) {
        elapsed += dt;
      }

      // Triggered search pulse
      if (pulseTargetRef.current > 0.01) {
        spinBoost = 1.6;
        waveScale = 1.0;
        waveAlpha = 0.55;
        pulseTargetRef.current = 0;
      }
      spinBoost += (0 - spinBoost) * Math.min(1, dt * 1.6);

      const { dimmed: isDimmed, lightMode: isLight } = stateRef.current;
      const targetDim = isDimmed ? 0.36 : 1.0;
      currentDimFactor += (targetDim - currentDimFactor) * Math.min(1, dt * 3.2);
      const themeMult = isLight ? 0.14 : 1.0;
      const masterOpacity = currentDimFactor * themeMult;

      // Continuous graceful orbital drift (always moving!)
      const driftX = Math.cos(elapsed * 0.18) * 1.35 + mouseX * 0.45;
      const baseTargetY = isDimmed ? 1.45 : -0.35;
      const driftY = baseTargetY + Math.sin(elapsed * 0.25) * 0.42 - mouseY * 0.35;
      const driftZ = (isDimmed ? -2.2 : 0.0) + Math.sin(elapsed * 0.14) * 0.45;

      systemGroup.position.x += (driftX - systemGroup.position.x) * Math.min(1, dt * 2.2);
      systemGroup.position.y += (driftY - systemGroup.position.y) * Math.min(1, dt * 2.2);
      systemGroup.position.z += (driftZ - systemGroup.position.z) * Math.min(1, dt * 2.2);

      // Gentle precessing tilt
      axisPivot.rotation.x = 0.28 + Math.sin(elapsed * 0.22) * 0.08 - mouseY * 0.12;
      axisPivot.rotation.z = 0.41 + Math.cos(elapsed * 0.17) * 0.06 + mouseX * 0.12;

      // Spin core + magnetic cage + jets
      if (!prefersReducedMotion) {
        spinGroup.rotation.y += dt * (1.65 + spinBoost * 2.4);
      }

      // Keplerian accretion disk particle orbit
      if (!prefersReducedMotion) {
        for (let i = 0; i < diskCount; i++) {
          diskAngles[i] += dt * diskSpeeds[i] * (1 + spinBoost * 0.7);
          const a = diskAngles[i];
          const r = diskRadii[i];
          diskPositions[i * 3] = Math.cos(a) * r;
          diskPositions[i * 3 + 2] = Math.sin(a) * r;
        }
        diskPosAttr.needsUpdate = true;
      }

      // Shockwave expansion
      if (waveAlpha > 0.005) {
        waveScale += dt * 5.2;
        waveAlpha *= Math.max(0, 1 - dt * 2.4);
        waveMesh.scale.setScalar(waveScale);
        waveMat.opacity = waveAlpha * masterOpacity;
      } else {
        waveMat.opacity = 0;
      }

      // Keep corona billboard facing camera
      coronaMesh.quaternion.copy(camera.quaternion);

      // Background subtle parallax
      bgStars.rotation.y = elapsed * 0.012 + mouseX * 0.03;
      bgStars.rotation.x = mouseY * 0.02;
      bgMat.opacity = isLight ? 0.05 : 0.35 * currentDimFactor;

      // Update shader uniforms
      starUniforms.uTime.value = elapsed;
      starUniforms.uOpacity.value = Math.min(1.0, masterOpacity + 0.25);
      coronaUniforms.uPulse.value = Math.sin(elapsed * 4.2);
      coronaUniforms.uOpacity.value = 0.82 * masterOpacity;
      jetUniforms.uTime.value = elapsed;
      jetUniforms.uFlare.value = 1.0 + spinBoost * 0.45;
      jetUniforms.uOpacity.value = 0.78 * masterOpacity;
      fieldLineMat.opacity = 0.15 * masterOpacity;
      diskUniforms.uOpacity.value = 0.85 * masterOpacity;

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
      unitJetGeo.dispose();
      jetMat.dispose();
      diskGeo.dispose();
      diskMat.dispose();
      bgGeo.dispose();
      bgMat.dispose();
      waveGeo.dispose();
      waveMat.dispose();
      fieldLineMat.dispose();
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
