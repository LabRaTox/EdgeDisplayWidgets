// Lightweight 60-sample Canvas sparkline.
// Theme-aware: stroke colour falls back to CSS `--accent` of the canvas.
//
// Usage:
//   const s = new Sparkline(canvas, { max: 100, samples: 60 });
//   s.push(value);

export class Sparkline {
  constructor(canvas, {
    max = 100,
    samples = 60,
    color = null,
    fill = null,
    axisEl = null,        // optional HTMLElement to render the Y-axis into
    axisTicks = 5,        // how many tick labels (including 0 and max)
    axisFormat = null,    // fn(value) => string; defaults to Math.round + ""
  } = {}) {
    this.canvas = canvas;
    this.max = max;
    this.samples = samples;
    this.color = color;
    this.fill = fill;
    this.axisEl = axisEl;
    this.axisTicks = axisTicks;
    this.axisFormat = axisFormat || ((v) => String(Math.round(v)));
    this._buf = new Float32Array(samples);
    this._head = 0;
    this._count = 0;
    this._resizeIfNeeded();
    this._renderAxis();
  }

  _resizeIfNeeded() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, rect.width);
    const h = Math.max(1, rect.height);
    const targetW = Math.round(w * dpr);
    const targetH = Math.round(h * dpr);
    if (this.canvas.width !== targetW) this.canvas.width = targetW;
    if (this.canvas.height !== targetH) this.canvas.height = targetH;
    this._w = w;
    this._h = h;
    this._dpr = dpr;
  }

  push(value) {
    this._buf[this._head] = value;
    this._head = (this._head + 1) % this.samples;
    this._count = Math.min(this._count + 1, this.samples);
    this.draw();
  }

  setMax(max) {
    if (max === this.max) return;
    this.max = max;
    this._renderAxis();
    this.draw();
  }

  _renderAxis() {
    if (!this.axisEl) return;
    const n = Math.max(2, this.axisTicks);
    const out = [];
    // Highest tick on top, zero at bottom — flex column with space-between
    for (let i = 0; i < n; i++) {
      const ratio = (n - 1 - i) / (n - 1);
      out.push(`<span class="axis-tick">${this.axisFormat(ratio * this.max)}</span>`);
    }
    this.axisEl.innerHTML = out.join("");
  }

  _values() {
    const out = new Array(this._count);
    for (let i = 0; i < this._count; i++) {
      const idx = (this._head - this._count + i + this.samples) % this.samples;
      out[i] = this._buf[idx];
    }
    return out;
  }

  draw() {
    this._resizeIfNeeded();
    const ctx = this.canvas.getContext("2d");
    const { _w: w, _h: h, _dpr: dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const values = this._values();
    if (values.length < 2) return;

    const cs = getComputedStyle(this.canvas);
    const stroke =
      this.color || cs.getPropertyValue("--accent").trim() || "#00e0ff";
    const fillStyle = this.fill ?? this._withAlpha(stroke, 0.15);

    const max = this.max || 1;
    const stepX = w / (this.samples - 1);
    const yFor = (v) => {
      const clamped = Math.max(0, Math.min(max, v));
      return h - (clamped / max) * h;
    };

    // Latest sample on the right edge: leave the left blank until we have
    // enough samples to fill the buffer.
    const startIdx = this.samples - values.length;

    ctx.beginPath();
    ctx.moveTo(startIdx * stepX, yFor(values[0]));
    for (let i = 1; i < values.length; i++) {
      ctx.lineTo((startIdx + i) * stepX, yFor(values[i]));
    }
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = stroke;
    ctx.stroke();

    ctx.lineTo((startIdx + values.length - 1) * stepX, h);
    ctx.lineTo(startIdx * stepX, h);
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
  }

  _withAlpha(color, alpha) {
    const c = color.trim();
    let m = c.match(/^#([0-9a-f]{3})$/i);
    if (m) {
      const [r, g, b] = m[1].split("").map((ch) => parseInt(ch + ch, 16));
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    m = c.match(/^#([0-9a-f]{6})$/i);
    if (m) {
      const r = parseInt(m[1].slice(0, 2), 16);
      const g = parseInt(m[1].slice(2, 4), 16);
      const b = parseInt(m[1].slice(4, 6), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    return c;
  }
}
