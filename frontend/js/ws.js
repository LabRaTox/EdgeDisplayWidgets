// WebSocket client with auto-reconnect.
// Mirrors `body[data-ws-status]` so CSS can react without JS plumbing.
// Acceptance criterion: backend restart -> reconnect within ~2s.

const RECONNECT_BASE_MS = 250;
const RECONNECT_MAX_MS = 2000;

export class WSClient extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this._closed = false;
    this._attempt = 0;
    this.status = "connecting";
    this._setStatus("connecting");
    this._connect();
  }

  _connect() {
    let socket;
    try {
      socket = new WebSocket(this.url);
    } catch (err) {
      console.error("[ws] construct failed:", err);
      this._scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.addEventListener("open", () => {
      this._attempt = 0;
      this._setStatus("connected");
    });

    socket.addEventListener("message", (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (err) {
        console.warn("[ws] non-JSON frame", err);
        return;
      }
      this.dispatchEvent(new CustomEvent("message", { detail: msg }));
    });

    socket.addEventListener("close", () => {
      this._setStatus(this._closed ? "closed" : "connecting");
      this._scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      // 'close' will follow; reconnection is handled there.
    });
  }

  _scheduleReconnect() {
    if (this._closed) return;
    this._attempt += 1;
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** (this._attempt - 1), RECONNECT_MAX_MS);
    setTimeout(() => this._connect(), delay);
  }

  _setStatus(status) {
    this.status = status;
    document.body.dataset.wsStatus = status;
    this.dispatchEvent(new CustomEvent("status", { detail: status }));
  }

  close() {
    this._closed = true;
    try {
      this.socket?.close();
    } catch (_) {
      /* noop */
    }
  }
}
