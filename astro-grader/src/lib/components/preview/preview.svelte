<script lang="ts">
  import type { ImageData } from '$/lib/types/ImageData';
  import { getData } from '$/lib/utils';
  import { invoke } from '@tauri-apps/api/core';
  import { toast } from 'svelte-sonner';
  import type { File } from '../../types/File';
  import * as Resizable from '../ui/resizable';
  import fragmentShaderSource from './shaders/fragment.glsl?raw';
  import vertextShaderSource from './shaders/vertex.glsl?raw';
  import { previewState } from './state.svelte';

  let canvasElement = $state<HTMLCanvasElement | null>(null);
  let rawData = $state<{
    width: number;
    height: number;
    data: Float32Array;
    grayscale: boolean;
  } | null>(null);

  const loadImage = async (image: File) => {
    try {
      let start = Date.now();

      const previewData = await invoke<ImageData>('fits_read_image', {
        path: image.path
      });

      previewState.previewData = previewData;

      console.log('Time to read image:', Date.now() - start, 'ms');
      console.log('Downloading image...');
      start = Date.now();
      const data = await getData<ArrayBuffer>('astro-grader://preview');

      if (!data) {
        toast.error('Failed to load preview data');
        return;
      }

      rawData = {
        width: previewData.width,
        height: previewData.height,
        data: new Float32Array(data),
        grayscale: previewData.layout === 'Grayscale'
      };

      console.log(rawData);
    } catch (_err) {
      const err = _err as string;

      toast.error(image.name, {
        description: err
      });
    }
  };

  const compileShader = (gl: WebGLRenderingContext, type: number, source: string) => {
    const shader = gl.createShader(type);
    if (!shader) throw new Error('Could not create shader');
    gl.shaderSource(shader, source);
    gl.compileShader(shader);

    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(shader));
      gl.deleteShader(shader);
      throw new Error('Shader compilation failed');
    }
    return shader;
  };

  $effect(() => {
    if (previewState.previewImage) {
      loadImage(previewState.previewImage);
    }
  });

  //https://gemini.google.com/app/3d31b5f253a4e981
  let glContext = $state<WebGL2RenderingContext | null>(null);
  let glProgram = $state<WebGLProgram | null>(null);

  $effect(() => {
    if (!canvasElement || !rawData) return;

    const gl = canvasElement.getContext('webgl2') as WebGL2RenderingContext;
    if (!gl) return;

    // Setup canvas
    canvasElement.width = rawData.width;
    canvasElement.height = rawData.height;
    gl.viewport(0, 0, rawData.width, rawData.height);

    // Compile shaders
    const vertexShader = compileShader(gl, gl.VERTEX_SHADER, vertextShaderSource);
    const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, fragmentShaderSource);

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    gl.useProgram(program);

    const vertices = new Float32Array([
      -1.0, -1.0, 1.0, -1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0, 1.0
    ]);

    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

    const positionLocation = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    // Upload Texture
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);

    //Update the grayscale uniform
    const isGrayscale = rawData?.grayscale ? 1 : 0;
    const isGrayscaleLoc = gl.getUniformLocation(program, 'u_is_grayscale');

    gl.uniform1i(isGrayscaleLoc, isGrayscale);

    const internalFormat = isGrayscale ? gl.R32F : gl.RGB32F;
    const sourceFormat = isGrayscale ? gl.RED : gl.RGB;

    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      internalFormat,
      rawData.width,
      rawData.height,
      0,
      sourceFormat,
      gl.FLOAT,
      rawData.data
    );

    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Save the context and program for the render loop
    glContext = gl;
    glProgram = program;

    return () => {
      gl.deleteTexture(texture);
      gl.deleteBuffer(positionBuffer);
      gl.deleteProgram(program);
      gl.deleteShader(vertexShader);
      gl.deleteShader(fragmentShader);
      glContext = null;
      glProgram = null;
    };
  });

  // --- EFFECT 2: FAST RENDER LOOP ---
  // This runs continuously whenever previewState.R/G/B changes
  $effect(() => {
    if (!glContext || !glProgram) return;
    const gl = glContext;

    // 1. Transpose the SMH data into [R, G, B] vectors for WebGL
    // Index 0 = Shadows, Index 1 = Midtones, Index 2 = Highlights
    const shadows = new Float32Array([previewState.R[0], previewState.G[0], previewState.B[0]]);
    const midtones = new Float32Array([previewState.R[1], previewState.G[1], previewState.B[1]]);
    const highlights = new Float32Array([previewState.R[2], previewState.G[2], previewState.B[2]]);

    console.log(shadows, midtones, highlights);

    // 2. Get uniform locations
    const shadowLoc = gl.getUniformLocation(glProgram, 'u_shadows');
    const midtoneLoc = gl.getUniformLocation(glProgram, 'u_midtones');
    const highlightLoc = gl.getUniformLocation(glProgram, 'u_highlights');

    // 3. Push values to GPU
    gl.uniform3fv(shadowLoc, shadows);
    gl.uniform3fv(midtoneLoc, midtones);
    gl.uniform3fv(highlightLoc, highlights);

    // 4. Instantly draw the new frame
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  });
</script>

<Resizable.Pane defaultSize={80}>
  <canvas bind:this={canvasElement} class="mt-4 h-auto w-full border shadow-sm"></canvas>
</Resizable.Pane>
