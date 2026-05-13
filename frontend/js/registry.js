// Widget registry — populated as widget modules are dynamically imported.
// A widget class must:
//   - declare `static modules = ["<module-name>", ...]` so the dispatcher can route
//   - implement mount(el, initialData, meta), update(data, moduleName, ts), destroy()

const _widgets = new Map();

export function registerWidget(name, cls) {
  if (_widgets.has(name)) {
    console.warn(`[registry] '${name}' re-registered, replacing previous class`);
  }
  _widgets.set(name, cls);
}

export function getWidget(name) {
  return _widgets.get(name);
}

export function listWidgets() {
  return [..._widgets.keys()];
}
