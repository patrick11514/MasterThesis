precision mediump float;
uniform sampler2D u_image;

uniform vec3 u_shadows;
uniform vec3 u_midtones;
uniform vec3 u_highlights;

varying vec2 v_texCoord;

void main() {
    vec3 color = texture2D(u_image, v_texCoord).rgb;

    // 1. Clip Shadows and Highlights
    // GPU subtracts R from R, G from G, B from B automatically
    color = clamp((color - u_shadows) / (u_highlights - u_shadows), vec3(0.0), vec3(1.0));

    // 2. Apply Midtone Transfer Function (MTF)
    vec3 m_minus_1 = u_midtones - vec3(1.0);
    vec3 m_times_2_minus_1 = (vec3(2.0) * u_midtones) - vec3(1.0);
    vec3 denominator = (m_times_2_minus_1 * color) - u_midtones;

    // If midtone is 0.5, this evaluates to just 'color'
    color = (m_minus_1 * color) / denominator;

    // Output final color
    gl_FragColor = vec4(color, 1.0);
}